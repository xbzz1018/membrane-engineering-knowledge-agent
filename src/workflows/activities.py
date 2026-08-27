from __future__ import annotations

import asyncio
from collections.abc import Awaitable

from temporalio import activity

from src.core.config import get_settings
from src.engineering.deep_review import run_package_review
from src.engineering.parsing import parse_document
from src.engineering.schemas import PackageReviewRequest
from src.engineering.storage import storage
from src.events.kafka_events import publisher


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
async def parse_and_index_activity(document_id: str) -> dict:
    await _heartbeat_delay("document-ingest-start")
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
    local_path = await storage.resolve_document_path(document)
    activity.heartbeat({"stage": "parsing", "document_id": document_id})
    chunks, parser = await _await_with_heartbeat(parse_document(str(local_path)), "parsing")
    activity.heartbeat({"stage": "indexing", "chunks": len(chunks)})
    count = await _await_with_heartbeat(storage.save_chunks(document_id, chunks, parser), "indexing")
    await publisher.publish(
        "document.ingest.completed",
        document_id,
        {"document_id": document_id, "chunks": count, "parser": parser},
    )
    return {"document_id": document_id, "chunks": count, "parser": parser, "status": "indexed"}


@activity.defn
async def package_review_activity(payload: dict) -> dict:
    await _heartbeat_delay("package-review-start")
    existing = await storage.get_package_review(payload["review_id"])
    if existing and existing["status"] in {"completed", "approved", "rejected", "awaiting_approval"}:
        return {**existing, "idempotent_replay": True}
    request = PackageReviewRequest(
        user_id=payload.get("user_id", "temporal-worker"),
        project_id=payload.get("project_id", "default"),
        document_ids=payload["document_ids"],
        question=payload.get("question", "比较资料中的设计方案和膜材规格"),
    )
    activity.heartbeat({"stage": "deep-review", "review_id": payload["review_id"]})
    result = await _await_with_heartbeat(run_package_review(request), "deep-review")
    result["review_id"] = payload["review_id"]
    result["status"] = "awaiting_approval" if result.get("conflicts") else "completed"
    await storage.save_package_review(
        result,
        user_id=request.user_id,
        project_id=request.project_id,
        question=request.question,
    )
    await publisher.publish(
        "package.review.completed",
        result["review_id"],
        {"review_id": result["review_id"], "document_ids": request.document_ids},
    )
    return result


@activity.defn
async def finalize_package_review_activity(payload: dict) -> dict:
    activity.heartbeat({"stage": "finalize-review", "review_id": payload["review_id"]})
    updated = await storage.update_package_review_status(payload["review_id"], payload["status"])
    if not updated:
        raise ValueError(f"package review not found: {payload['review_id']}")
    return {"review_id": payload["review_id"], "status": payload["status"]}
