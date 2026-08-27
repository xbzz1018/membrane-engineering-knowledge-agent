from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src.engineering.schemas import WorkflowDecisionRequest
from src.workflows.temporal_app import cancel_workflow, get_workflow_state, signal_workflow

router = APIRouter(prefix="/api/v1/workflows", tags=["workflows"])


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ValueError):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=502, detail=f"Temporal operation failed: {type(exc).__name__}")


@router.get("/{workflow_id}")
async def workflow_status(workflow_id: str) -> dict:
    try:
        return await get_workflow_state(workflow_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/{workflow_id}/approve")
async def approve_workflow(workflow_id: str) -> dict:
    try:
        return await signal_workflow(workflow_id, "approved")
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/{workflow_id}/reject")
async def reject_workflow(workflow_id: str, request: WorkflowDecisionRequest) -> dict:
    try:
        return await signal_workflow(workflow_id, "rejected", request.reason)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/{workflow_id}/cancel", status_code=202)
async def cancel_workflow_request(workflow_id: str) -> dict:
    try:
        return await cancel_workflow(workflow_id)
    except Exception as exc:
        raise _http_error(exc) from exc
