from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from src.api.dependencies import current_principal, require_project_role
from src.application.reviews import ReviewApplicationError, package_review_application
from src.core.security import Principal
from src.domain.schemas import WorkflowDecisionRequest
from src.infrastructure.database import storage
from src.workflows.temporal_app import cancel_workflow, get_workflow_state

router = APIRouter(prefix="/api/v1/workflows", tags=["长任务工作流"])


async def _authorize(workflow_id: str, principal: Principal, *, decision: bool = False) -> None:
    project_id = ""
    if workflow_id.startswith("package-review:"):
        review = await storage.get_package_review(workflow_id.split(":", 1)[1])
        project_id = review["project_id"] if review else ""
    elif workflow_id.startswith("batch-ingest:"):
        batch = await storage.get_batch_import(workflow_id.split(":", 1)[1], principal.tenant_id)
        project_id = batch["project_id"] if batch else ""
    elif workflow_id.startswith("document-ingest:"):
        document = await storage.get_document(workflow_id.split(":", 1)[1])
        project_id = document["project_id"] if document else ""
    if not project_id:
        raise HTTPException(status_code=404, detail="工作流业务对象不存在")
    roles = {"admin", "reviewer"} if decision else None
    await require_project_role(project_id, principal, roles)


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ValueError):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=502, detail=f"Temporal操作失败: {type(exc).__name__}")


@router.get("/{workflow_id}", summary="查询Temporal工作流状态")
async def workflow_status(
    workflow_id: str,
    principal: Principal = Depends(current_principal),
) -> dict:
    await _authorize(workflow_id, principal)
    try:
        return await get_workflow_state(workflow_id)
    except Exception as exc:
        raise _http_error(exc) from exc


async def _decide(workflow_id: str, request: WorkflowDecisionRequest, principal: Principal, decision: str) -> dict:
    await _authorize(workflow_id, principal, decision=True)
    if not workflow_id.startswith("package-review:"):
        raise HTTPException(status_code=404, detail="不是资料审查工作流")
    try:
        return await package_review_application.decide(
            workflow_id.split(":", 1)[1],
            principal,
            decision,
            expected_lock_version=request.expected_lock_version,
            reason=request.reason,
        )
    except ReviewApplicationError as exc:
        raise HTTPException(
            status_code={"not_found": 404, "conflict": 409, "forbidden": 403}.get(exc.code, 502), detail=str(exc)
        ) from exc


@router.post("/{workflow_id}/approve", summary="审核人按报告版本批准审查")
async def approve_workflow(
    workflow_id: str,
    request: WorkflowDecisionRequest,
    principal: Principal = Depends(current_principal),
) -> dict:
    return await _decide(workflow_id, request, principal, "approved")


@router.post("/{workflow_id}/reject", summary="审核人按报告版本退回审查")
async def reject_workflow(
    workflow_id: str,
    request: WorkflowDecisionRequest,
    principal: Principal = Depends(current_principal),
) -> dict:
    return await _decide(workflow_id, request, principal, "rejected")


@router.post("/{workflow_id}/cancel", status_code=202, summary="取消未完成工作流")
async def cancel_workflow_request(
    workflow_id: str,
    principal: Principal = Depends(current_principal),
) -> dict:
    await _authorize(workflow_id, principal)
    try:
        return await cancel_workflow(workflow_id)
    except Exception as exc:
        raise _http_error(exc) from exc
