from __future__ import annotations

from datetime import timedelta
from typing import Any

from src.core.config import get_settings


def _enabled() -> bool:
    return bool(get_settings().TEMPORAL_ENABLED)


async def _client():
    if not _enabled():
        return None
    from temporalio.client import Client

    settings = get_settings()
    return await Client.connect(settings.TEMPORAL_TARGET, namespace=settings.TEMPORAL_NAMESPACE)


async def submit_document_ingest(document_id: str) -> dict[str, Any]:
    client = await _client()
    workflow_id = f"document-ingest:{document_id}"
    if client is None:
        return {"workflow_id": workflow_id, "enabled": False, "status": "local"}
    from src.workflows.temporal_definitions import DocumentIngestWorkflow

    handle = await client.start_workflow(
        DocumentIngestWorkflow.run,
        document_id,
        id=workflow_id,
        task_queue="membrane-engineering",
        execution_timeout=timedelta(minutes=30),
    )
    return {"workflow_id": handle.id, "enabled": True, "status": "queued"}


async def submit_package_review(review_id: str, document_ids: list[str], question: str) -> dict[str, Any]:
    client = await _client()
    workflow_id = f"package-review:{review_id}"
    if client is None:
        return {"workflow_id": workflow_id, "enabled": False, "status": "local"}
    from src.workflows.temporal_definitions import PackageReviewWorkflow

    handle = await client.start_workflow(
        PackageReviewWorkflow.run,
        {"review_id": review_id, "document_ids": document_ids, "question": question},
        id=workflow_id,
        task_queue="membrane-engineering",
        execution_timeout=timedelta(minutes=30),
    )
    return {"workflow_id": handle.id, "enabled": True, "status": "queued"}
