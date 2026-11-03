from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable

from temporalio import activity

from src.agents.prompts import get_prompt
from src.agents.review_agents import ReviewPlan, WorkerReview, get_package_review_service
from src.agents.subagent_tools import DomainAgentTools
from src.core.config import get_settings
from src.documents.parsing import ParserExecutionError, parse_document
from src.domain.schemas import PackageReviewRequest
from src.infrastructure.database import storage
from src.infrastructure.review_decisions import ReviewDecisionRepository
from src.infrastructure.review_lifecycle import set_review_terminal
from src.infrastructure.review_manifest import read_review_manifest


async def _collect_review_evidence(service, request, payload):
    if not payload.get("manifest_required"):
        # Compatibility with older demo workflow inputs; new submissions always
        # require a snapshot. Do not infer a successful historical migration.
        return await service.collect_evidence(request, payload["tenant_id"])
    manifest, _ = await read_review_manifest(storage, payload["review_id"], payload["tenant_id"], payload["project_id"])
    # Classification can become stricter after submission. Recheck it before any
    # cloud processing, while retaining the frozen original evidence bodies.
    current = await storage.list_documents(request.document_ids, project_id=request.project_id,
                                           tenant_id=payload["tenant_id"])
    if len(current) != len(set(request.document_ids)):
        raise ValueError("快照资料已不可访问")
    if service.provider.metadata.get("mode") == "api" and any(
        row["data_classification"] != "public" for row in current
    ):
        raise ValueError("快照资料当前分级禁止云端处理")
    return manifest["documents"], manifest["evidence"], manifest["sources"]


async def _heartbeat_delay(stage: str) -> None:
    delay = get_settings().TEMPORAL_ACTIVITY_TEST_DELAY_SECONDS
    activity.heartbeat({"stage": stage, "remaining_seconds": delay})
    for remaining in range(delay, 0, -1):
        await asyncio.sleep(1)
        activity.heartbeat({"stage": stage, "remaining_seconds": remaining - 1})


async def _await_with_heartbeat[T](awaitable: Awaitable[T], stage: str) -> T:
    task = asyncio.ensure_future(awaitable)
    try:
        while True:
            done, _ = await asyncio.wait({task}, timeout=10)
            if done:
                return await task
            activity.heartbeat({"stage": stage})
    except BaseException:
        task.cancel()
        raise


@activity.defn
async def parse_and_index_activity(payload: str | dict) -> dict:
    info = activity.info()
    claim = (f"{info.workflow_id}:{info.workflow_run_id}:{info.activity_id}", info.attempt)
    document_id = payload if isinstance(payload, str) else str(payload["document_id"])
    document = await storage.get_document(document_id)
    if not document:
        raise ValueError(f"document not found: {document_id}")
    existing = await storage.count_document_chunks(document_id)
    from src.infrastructure.model_provider import get_model_provider

    embedding_current = (get_settings().RUNTIME_MODE.lower() != "full"
                         or document.get("embedding_model", "") == get_model_provider().embedding_model)
    if document["status"] == "indexed" and existing and embedding_current:
        return {
            "document_id": document_id,
            "chunks": existing,
            "parser": document["parser"],
            "status": "indexed",
            "idempotent_replay": True,
        }
    acquired = await storage.acquire_document_ingest(
        document_id, refresh_embedding=not embedding_current, claim=claim,
    )
    if not acquired:
        document = await storage.get_document(document_id)
        if document and document["status"] == "indexed":
            return {
                "document_id": document_id,
                "chunks": await storage.count_document_chunks(document_id),
                "parser": document["parser"],
                "status": "indexed",
                "idempotent_replay": True,
            }
        raise RuntimeError(f"document ingest is already running: {document_id}")
    try:
        await _heartbeat_delay("document-ingest-acquired")
        local_path = await storage.resolve_document_path(document)
        activity.heartbeat({"stage": "parsing", "document_id": document_id})
        chunks, parser = await _await_with_heartbeat(
            parse_document(str(local_path), document["parse_method"]), "parsing",
        )
        if not chunks or not any(str(item.get("text", "")).strip() for item in chunks):
            raise ParserExecutionError("parser returned no evidence")
        activity.heartbeat({"stage": "indexing", "chunks": len(chunks)})
        count = await _await_with_heartbeat(storage.save_chunks(document_id, chunks, parser, claim=claim), "indexing")
        return {"document_id": document_id, "chunks": count, "parser": parser, "status": "indexed"}
    except asyncio.CancelledError:
        await asyncio.shield(storage.fail_document(document_id, "CancelledError", claim=claim))
        raise
    except Exception as exc:
        current = await storage.get_document(document_id)
        if not current or current["status"] != "index_failed":
            await storage.fail_document(document_id, type(exc).__name__, claim=claim)
        raise


@activity.defn
async def review_worker_activity(payload: dict) -> dict:
    worker = str(payload["worker"])
    activity.heartbeat({"stage": "review-worker", "worker": worker})
    service = get_package_review_service()
    started = time.perf_counter()
    run_id = await storage.start_agent_run(
        tenant_id=payload["tenant_id"],
        project_id=payload["project_id"],
        user_id=payload["user_id"],
        run_type=f"package_review_{worker}",
        provider=str(service.provider.metadata.get("provider", "")),
        model=str(service.provider.metadata.get("model", "")),
        business_id=payload["review_id"],
        prompt_name=get_prompt(f"{worker}-review").name,
        prompt_version=get_prompt(f"{worker}-review").version,
        prompt_sha256=get_prompt(f"{worker}-review").digest,
    )
    try:
        request = PackageReviewRequest(
            project_id=payload["project_id"],
            document_ids=payload["document_ids"],
            question=payload["question"],
            review_mode=payload.get("review_mode", "full"),
        )
        _, evidence, _ = await _collect_review_evidence(service, request, payload)
        memories = await service.memory.search(
            tenant_id=payload["tenant_id"],
            user_id=payload["user_id"],
            project_id=payload["project_id"],
            query=payload["question"],
        )
        boundary = DomainAgentTools(service, [worker], payload["question"], evidence, memories)
        await _await_with_heartbeat(
            boundary.tools[0].ainvoke({}),
            f"{worker}-review",
        )
        review, usage = boundary.outputs[worker]
        usage["tool"] = boundary.tools[0].name
        usage["tool_events"] = boundary.events
        latency_ms = (time.perf_counter() - started) * 1000
        await storage.add_agent_step(
            run_id,
            f"{worker}_map_reduce",
            "invoke_agent",
            "completed",
            input_tokens=int(usage.get("input_tokens", 0) or 0),
            output_tokens=int(usage.get("output_tokens", 0) or 0),
            latency_ms=latency_ms,
        )
        await storage.finish_agent_run(
            run_id,
            status="completed",
            input_tokens=int(usage.get("input_tokens", 0) or 0),
            output_tokens=int(usage.get("output_tokens", 0) or 0),
            latency_ms=latency_ms,
            finish_reason=",".join(item for item in usage.get("finish_reasons", []) if item),
        )
        return {"review": review.model_dump(), "usage": usage}
    except Exception as exc:
        latency_ms = (time.perf_counter() - started) * 1000
        await storage.add_agent_step(
            run_id,
            f"{worker}_map_reduce",
            "invoke_agent",
            "failed",
            latency_ms=latency_ms,
            error_type=type(exc).__name__,
        )
        await storage.finish_agent_run(
            run_id,
            status="failed",
            latency_ms=latency_ms,
            error_type=type(exc).__name__,
        )
        raise


@activity.defn
async def plan_package_review_activity(payload: dict) -> dict:
    """Create and audit the LLM Supervisor plan before domain Workers run."""
    activity.heartbeat({"stage": "review-supervisor", "review_id": payload["review_id"]})
    service = get_package_review_service()
    started = time.perf_counter()
    run_id = await storage.start_agent_run(
        tenant_id=payload["tenant_id"],
        project_id=payload["project_id"],
        user_id=payload["user_id"],
        run_type="package_review_supervisor",
        provider=str(service.provider.metadata.get("provider", "")),
        model=str(service.provider.metadata.get("model", "")),
        business_id=payload["review_id"],
        prompt_name=get_prompt("review-supervisor").name,
        prompt_version=get_prompt("review-supervisor").version,
        prompt_sha256=get_prompt("review-supervisor").digest,
    )
    try:
        request = PackageReviewRequest(
            project_id=payload["project_id"],
            document_ids=payload["document_ids"],
            question=payload["question"],
            review_mode=payload.get("review_mode", "full"),
        )
        _, evidence, _ = await _collect_review_evidence(service, request, payload)
        plan, usage = await _await_with_heartbeat(
            service.plan_review(payload["question"], evidence, payload.get("review_mode", "full")),
            "review-supervisor",
        )
        latency_ms = (time.perf_counter() - started) * 1000
        await storage.add_agent_step(
            run_id,
            "review_supervisor_plan",
            "invoke_agent",
            "completed",
            input_tokens=int(usage.get("input_tokens", 0) or 0),
            output_tokens=int(usage.get("output_tokens", 0) or 0),
            latency_ms=latency_ms,
        )
        await storage.finish_agent_run(
            run_id,
            status="completed",
            input_tokens=int(usage.get("input_tokens", 0) or 0),
            output_tokens=int(usage.get("output_tokens", 0) or 0),
            latency_ms=latency_ms,
            finish_reason=str(usage.get("finish_reason", "")),
        )
        return {"plan": plan.model_dump(), "usage": usage}
    except Exception as exc:
        latency_ms = (time.perf_counter() - started) * 1000
        await storage.add_agent_step(
            run_id,
            "review_supervisor_plan",
            "invoke_agent",
            "failed",
            latency_ms=latency_ms,
            error_type=type(exc).__name__,
        )
        await storage.finish_agent_run(
            run_id,
            status="failed",
            latency_ms=latency_ms,
            error_type=type(exc).__name__,
        )
        raise


@activity.defn
async def repair_review_coverage_activity(payload: dict) -> dict:
    """Run at most one Evidence coverage repair pass after the first Worker fan-out."""
    activity.heartbeat({"stage": "review-coverage", "review_id": payload["review_id"]})
    service = get_package_review_service()
    request = PackageReviewRequest(
        project_id=payload["project_id"],
        document_ids=payload["document_ids"],
        question=payload["question"],
        review_mode=payload.get("review_mode", "full"),
    )
    _, evidence, _ = await _collect_review_evidence(service, request, payload)
    memories = await service.memory.search(
        tenant_id=payload["tenant_id"],
        user_id=payload["user_id"],
        project_id=payload["project_id"],
        query=payload["question"],
    )
    outputs = [
        (WorkerReview.model_validate(item["review"]), item.get("usage", {}))
        for item in payload["worker_outputs"]
    ]
    workers = [
        worker
        for worker in (payload.get("review_plan") or {}).get("workers", [])
        if worker in {"design", "material", "price"}
    ]
    repaired, coverage = await _await_with_heartbeat(
        service.repair_evidence_coverage(
            workers,
            payload["question"],
            evidence,
            memories,
            outputs,
        ),
        "review-coverage",
    )
    return {
        "worker_outputs": [
            {"review": review.model_dump(), "usage": usage}
            for review, usage in repaired
        ],
        "coverage": coverage,
    }


@activity.defn
async def compose_package_review_activity(payload: dict) -> dict:
    activity.heartbeat({"stage": "compose-review", "review_id": payload["review_id"]})
    service = get_package_review_service()
    request = PackageReviewRequest(
        project_id=payload["project_id"],
        document_ids=payload["document_ids"],
        question=payload["question"],
        review_mode=payload.get("review_mode", "full"),
    )
    _, evidence, sources = await _collect_review_evidence(service, request, payload)
    outputs = [
        (WorkerReview.model_validate(item["review"]), item.get("usage", {}))
        for item in payload["worker_outputs"]
    ]
    plan = ReviewPlan.model_validate(payload.get("review_plan") or {"workers": [item[0].worker for item in outputs]})
    result = service.compose(
        outputs,
        sources,
        plan=plan,
        supervisor_usage=payload.get("supervisor_usage"),
        evidence=evidence,
        coverage=payload.get("coverage"),
    )
    result["review_id"] = payload["review_id"]
    await storage.save_package_review(
        result,
        tenant_id=payload["tenant_id"],
        user_id=payload["user_id"],
        project_id=payload["project_id"],
        question=payload["question"],
        review_mode=payload.get("review_mode", "full"),
    )
    actual_tokens = sum(
        int(item.get("input_tokens", 0) or 0) + int(item.get("output_tokens", 0) or 0)
        for item in result.get("usage", {}).values()
        if isinstance(item, dict)
    )
    rate = get_settings().MODEL_ESTIMATED_COST_MICROS_PER_1K_TOKENS
    actual_cost = ((actual_tokens + 999) // 1000) * rate
    await storage.settle_budget(f"package-review:{payload['review_id']}", actual_tokens, actual_cost)
    return result


@activity.defn
async def finalize_package_review_activity(payload: dict) -> dict | None:
    activity.heartbeat({"stage": "finalize-review", "review_id": payload["review_id"]})
    return await ReviewDecisionRepository(storage).consume_pending_decision(payload["review_id"])


@activity.defn
async def update_batch_activity(payload: dict) -> dict:
    activity.heartbeat({"stage": "batch-progress", "batch_id": payload["batch_id"]})
    await storage.update_batch_import(payload["batch_id"], payload["state"])
    return payload["state"]


@activity.defn
async def settle_review_budget_activity(payload: dict) -> dict:
    activity.heartbeat({"stage": "settle-budget", "review_id": payload["review_id"]})
    # A committed reviewer command wins over a concurrent cancellation. Consume
    # it first so no command is left waiting on a workflow that has exited.
    receipt = await ReviewDecisionRepository(storage).consume_pending_decision(payload["review_id"])
    terminal_synced = await set_review_terminal(storage, payload["review_id"], payload.get("status", "failed"))
    if not terminal_synced and receipt is None:
        # Reviewer may have committed between our first read and terminal CAS.
        receipt = await ReviewDecisionRepository(storage).consume_pending_decision(payload["review_id"])
        row = await storage.get_package_review(payload["review_id"])
        if receipt is None and row and row["status"] == "decision_pending":
            raise RuntimeError("decision raced with terminal synchronization; retry")
    settled = await storage.settle_budget(
        f"package-review:{payload['review_id']}",
        int(payload.get("actual_tokens", 0)),
        status=str(payload.get("status", "failed")),
    )
    return {"review_id": payload["review_id"], "settled": settled,
            "terminal_synced": terminal_synced, "decision": receipt}
