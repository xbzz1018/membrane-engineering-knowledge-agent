from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable

from temporalio import activity

from src.core.config import get_settings
from src.engineering.parsing import parse_document
from src.engineering.review_agents import WorkerReview, get_package_review_service
from src.engineering.schemas import PackageReviewRequest
from src.engineering.storage import storage


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
    await _heartbeat_delay("document-ingest-start")
    document_id = payload if isinstance(payload, str) else str(payload["document_id"])
    document = await storage.get_document(document_id)
    if not document:
        raise ValueError(f"document not found: {document_id}")
    existing = await storage.count_document_chunks(document_id)
    if document["status"] == "indexed" and existing:
        return {
            "document_id": document_id,
            "chunks": existing,
            "parser": document["parser"],
            "status": "indexed",
            "idempotent_replay": True,
        }
    acquired = await storage.acquire_document_ingest(document_id)
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
        local_path = await storage.resolve_document_path(document)
        activity.heartbeat({"stage": "parsing", "document_id": document_id})
        chunks, parser = await _await_with_heartbeat(
            parse_document(str(local_path), document["parse_method"]), "parsing",
        )
        activity.heartbeat({"stage": "indexing", "chunks": len(chunks)})
        count = await _await_with_heartbeat(storage.save_chunks(document_id, chunks, parser), "indexing")
        return {"document_id": document_id, "chunks": count, "parser": parser, "status": "indexed"}
    except Exception as exc:
        current = await storage.get_document(document_id)
        if not current or current["status"] != "index_failed":
            await storage.fail_document(document_id, type(exc).__name__)
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
    )
    try:
        request = PackageReviewRequest(
            project_id=payload["project_id"],
            document_ids=payload["document_ids"],
            question=payload["question"],
        )
        _, evidence, _ = await service.collect_evidence(request, payload["tenant_id"])
        memories = await service.memory.search(
            tenant_id=payload["tenant_id"],
            user_id=payload["user_id"],
            project_id=payload["project_id"],
            query=payload["question"],
        )
        review, usage = await _await_with_heartbeat(
            service.run_worker(worker, payload["question"], evidence, memories),
            f"{worker}-review",
        )
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
async def compose_package_review_activity(payload: dict) -> dict:
    activity.heartbeat({"stage": "compose-review", "review_id": payload["review_id"]})
    service = get_package_review_service()
    request = PackageReviewRequest(
        project_id=payload["project_id"],
        document_ids=payload["document_ids"],
        question=payload["question"],
    )
    _, _, sources = await service.collect_evidence(request, payload["tenant_id"])
    outputs = [
        (WorkerReview.model_validate(item["review"]), item.get("usage", {}))
        for item in payload["worker_outputs"]
    ]
    result = service.compose(outputs, sources)
    result["review_id"] = payload["review_id"]
    await storage.save_package_review(
        result,
        tenant_id=payload["tenant_id"],
        user_id=payload["user_id"],
        project_id=payload["project_id"],
        question=payload["question"],
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
async def finalize_package_review_activity(payload: dict) -> dict:
    activity.heartbeat({"stage": "finalize-review", "review_id": payload["review_id"]})
    updated = await storage.update_package_review_status(payload["review_id"], payload["status"])
    if not updated:
        raise ValueError("review was already decided or does not exist")
    return {"review_id": payload["review_id"], "status": payload["status"]}


@activity.defn
async def update_batch_activity(payload: dict) -> dict:
    activity.heartbeat({"stage": "batch-progress", "batch_id": payload["batch_id"]})
    await storage.update_batch_import(payload["batch_id"], payload["state"])
    return payload["state"]


@activity.defn
async def settle_review_budget_activity(payload: dict) -> dict:
    activity.heartbeat({"stage": "settle-budget", "review_id": payload["review_id"]})
    settled = await storage.settle_budget(
        f"package-review:{payload['review_id']}",
        int(payload.get("actual_tokens", 0)),
        status=str(payload.get("status", "failed")),
    )
    return {"review_id": payload["review_id"], "settled": settled}
