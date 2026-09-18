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
    from temporalio.common import WorkflowIDReusePolicy
    from temporalio.exceptions import WorkflowAlreadyStartedError

    from src.workflows.temporal_definitions import DocumentIngestWorkflow

    try:
        handle = await client.start_workflow(
            DocumentIngestWorkflow.run,
            {
                "document_id": document_id,
                "parse_task_queue": get_settings().TEMPORAL_PARSE_TASK_QUEUE,
            },
            id=workflow_id,
            task_queue=get_settings().TEMPORAL_TASK_QUEUE,
            execution_timeout=timedelta(minutes=30),
            run_timeout=timedelta(minutes=25),
            task_timeout=timedelta(seconds=10),
            id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
        )
        status = "queued"
    except WorkflowAlreadyStartedError:
        handle = client.get_workflow_handle(workflow_id)
        status = "existing"
    return {"workflow_id": handle.id, "enabled": True, "status": status}


async def submit_batch_ingest(
    batch_id: str,
    document_ids: list[str],
) -> dict[str, Any]:
    client = await _client()
    workflow_id = f"batch-ingest:{batch_id}"
    if client is None:
        return {"workflow_id": workflow_id, "enabled": False, "status": "local"}
    from temporalio.common import WorkflowIDReusePolicy
    from temporalio.exceptions import WorkflowAlreadyStartedError

    from src.workflows.temporal_definitions import BatchDocumentIngestWorkflow

    settings = get_settings()
    payload = {
        "batch_id": batch_id,
        "document_ids": document_ids,
        "concurrency": settings.BATCH_CHILD_CONCURRENCY,
        "workflow_task_queue": settings.TEMPORAL_TASK_QUEUE,
        "parse_task_queue": settings.TEMPORAL_PARSE_TASK_QUEUE,
        "maintenance_task_queue": settings.TEMPORAL_MAINTENANCE_TASK_QUEUE,
    }
    try:
        handle = await client.start_workflow(
            BatchDocumentIngestWorkflow.run,
            payload,
            id=workflow_id,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
            execution_timeout=timedelta(hours=4),
            run_timeout=timedelta(hours=3),
            task_timeout=timedelta(seconds=10),
            id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
        )
        status = "queued"
    except WorkflowAlreadyStartedError:
        handle = client.get_workflow_handle(workflow_id)
        status = "existing"
    return {"workflow_id": handle.id, "enabled": True, "status": status}


async def submit_package_review(
    review_id: str,
    document_ids: list[str],
    question: str,
    user_id: str,
    project_id: str,
    tenant_id: str,
    review_mode: str = "full",
) -> dict[str, Any]:
    client = await _client()
    workflow_id = f"package-review:{review_id}"
    if client is None:
        return {"workflow_id": workflow_id, "enabled": False, "status": "local"}
    from temporalio.common import WorkflowIDReusePolicy
    from temporalio.exceptions import WorkflowAlreadyStartedError

    from src.workflows.temporal_definitions import PackageReviewWorkflow

    payload = {
        "review_id": review_id,
        "document_ids": document_ids,
        "question": question,
        "user_id": user_id,
        "project_id": project_id,
        "tenant_id": tenant_id,
        "review_mode": review_mode,
        "review_task_queue": get_settings().TEMPORAL_REVIEW_TASK_QUEUE,
        "maintenance_task_queue": get_settings().TEMPORAL_MAINTENANCE_TASK_QUEUE,
    }
    try:
        handle = await client.start_workflow(
            PackageReviewWorkflow.run,
            payload,
            id=workflow_id,
            task_queue=get_settings().TEMPORAL_TASK_QUEUE,
            execution_timeout=timedelta(minutes=45),
            run_timeout=timedelta(minutes=40),
            task_timeout=timedelta(seconds=10),
            id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
        )
        status = "queued"
    except WorkflowAlreadyStartedError:
        handle = client.get_workflow_handle(workflow_id)
        status = "existing"
    return {"workflow_id": handle.id, "enabled": True, "status": status}


async def get_workflow_state(workflow_id: str) -> dict[str, Any]:
    client = await _client()
    if client is None:
        return {"workflow_id": workflow_id, "enabled": False, "status": "disabled"}
    handle = client.get_workflow_handle(workflow_id)
    description = await handle.describe()
    temporal_status = description.status.name.lower()
    try:
        state = await handle.query("state")
    except Exception:
        normalized = "cancelled" if temporal_status == "canceled" else temporal_status
        state = {"status": normalized, "result": None, "error": None}
    return {
        "workflow_id": workflow_id,
        "enabled": True,
        "temporal_status": temporal_status,
        **state,
    }


async def signal_workflow(workflow_id: str, decision: str, reason: str = "") -> dict[str, Any]:
    client = await _client()
    if client is None:
        raise RuntimeError("Temporal is disabled")
    if not workflow_id.startswith("package-review:"):
        raise ValueError("Approval signals are only valid for package review workflows")
    handle = client.get_workflow_handle(workflow_id)
    if decision == "approved":
        await handle.signal("approve")
    elif decision == "rejected":
        await handle.signal("reject", reason)
    else:
        raise ValueError(f"Unsupported workflow decision: {decision}")
    return await get_workflow_state(workflow_id)


async def cancel_workflow(workflow_id: str) -> dict[str, Any]:
    client = await _client()
    if client is None:
        raise RuntimeError("Temporal is disabled")
    handle = client.get_workflow_handle(workflow_id)
    await handle.cancel()
    return {"workflow_id": workflow_id, "status": "cancellation_requested"}
