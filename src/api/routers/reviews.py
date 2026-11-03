from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from src.api.dependencies import current_principal, rate_limited_principal, require_project_role
from src.application.reviews import ReviewApplicationError, package_review_application
from src.core.config import get_settings
from src.core.security import Principal
from src.domain.schemas import (
    PackageReviewRequest,
    PackageReviewResponse,
    ReviewDecisionRequest,
    ReviewIssueStatusRequest,
)
from src.infrastructure.database import storage
from src.infrastructure.review_decisions import ReviewDecisionRepository
from src.workflows.temporal_app import get_workflow_state

router = APIRouter(prefix="/api/v1/package-reviews", tags=["多智能体资料审查"])
TERMINAL = {"completed", "approved", "rejected", "failed", "cancelled", "canceled"}


@router.get("", summary="查看项目资料包审查列表")
async def list_package_reviews(
    project_id: str = "demo-project",
    status: str | None = None,
    limit: int = 50,
    principal: Principal = Depends(current_principal),
) -> list[dict]:
    await require_project_role(project_id, principal)
    return await storage.list_package_reviews(
        tenant_id=principal.tenant_id,
        project_id=project_id,
        status=status,
        limit=max(1, min(limit, 200)),
    )


@router.post("", response_model=PackageReviewResponse, summary="启动 Supervisor 与三领域智能体审查")
async def package_review(
    request: PackageReviewRequest,
    principal: Principal = Depends(rate_limited_principal),
) -> PackageReviewResponse:
    try:
        return PackageReviewResponse(**await package_review_application.start(request, principal))
    except ReviewApplicationError as exc:
        status = {"quota": 429, "agent": 422, "invalid_documents": 400}.get(exc.code, 400)
        raise HTTPException(status_code=status, detail=str(exc)) from exc


@router.get("/{review_id}", response_model=PackageReviewResponse, summary="查看资料包审查报告")
async def get_package_review(
    review_id: str,
    principal: Principal = Depends(current_principal),
) -> PackageReviewResponse:
    result = await storage.get_package_review(review_id)
    if result is None:
        raise HTTPException(status_code=404, detail="资料包审查不存在")
    await require_project_role(result.get("project_id", "default"), principal)
    return PackageReviewResponse(**result)


@router.get("/{review_id}/workers", summary="查看三个审查智能体的领域结果")
async def review_workers(
    review_id: str,
    principal: Principal = Depends(current_principal),
) -> dict:
    result = await storage.get_package_review(review_id)
    if result is None:
        raise HTTPException(status_code=404, detail="资料包审查不存在")
    await require_project_role(result["project_id"], principal)
    workers = result.get("worker_results", {})
    return {
        "review_id": review_id,
        "orchestrator": result.get("orchestrator", "ReviewSupervisorAgent"),
        "review_plan": result.get("review_plan", {}),
        "agents_used": result.get("agents_used", []),
        "workers": workers,
        "usage": result.get("usage", {}),
    }


@router.get("/{review_id}/evidence", summary="查看审查引用的全部证据")
async def review_evidence(
    review_id: str,
    principal: Principal = Depends(current_principal),
) -> dict:
    result = await storage.get_package_review(review_id)
    if result is None:
        raise HTTPException(status_code=404, detail="资料包审查不存在")
    await require_project_role(result["project_id"], principal)
    return {"review_id": review_id, "evidence": result.get("sources", [])}


@router.get("/{review_id}/issues", summary="查看结构化工程审查问题单")
async def review_issues(
    review_id: str,
    principal: Principal = Depends(current_principal),
) -> dict:
    result = await storage.get_package_review(review_id)
    if result is None:
        raise HTTPException(status_code=404, detail="资料包审查不存在")
    await require_project_role(result["project_id"], principal)
    return {"review_id": review_id, "issues": result.get("issues", [])}


@router.patch("/{review_id}/issues/{issue_id}", summary="审核人更新工程问题单状态")
async def update_review_issue(
    review_id: str,
    issue_id: str,
    request: ReviewIssueStatusRequest,
    principal: Principal = Depends(current_principal),
) -> dict:
    review = await storage.get_package_review(review_id)
    if review is None:
        raise HTTPException(status_code=404, detail="资料包审查不存在")
    await require_project_role(review["project_id"], principal, {"reviewer"})
    try:
        updated = await ReviewDecisionRepository(storage).mutate(
            review_id,
            issue_id=issue_id,
            issue_status=request.status,
            expected_lock_version=request.expected_lock_version,
            actor=principal.user_id,
            reason=request.reason,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="审查问题单不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return updated


@router.post("/{review_id}/decision", summary="审核人按报告版本批准或退回审查")
async def decide_review(
    review_id: str,
    request: ReviewDecisionRequest,
    principal: Principal = Depends(current_principal),
) -> dict:
    review = await storage.get_package_review(review_id)
    if review is None:
        raise HTTPException(status_code=404, detail="审查报告不存在")
    await require_project_role(review["project_id"], principal, {"reviewer"})
    try:
        return await package_review_application.decide(
            review_id,
            principal,
            request.decision,
            expected_lock_version=request.expected_lock_version,
            reason=request.reason,
        )
    except ReviewApplicationError as exc:
        raise HTTPException(
            status_code={"not_found": 404, "forbidden": 403, "conflict": 409}.get(exc.code, 502), detail=str(exc)
        ) from exc


@router.get("/{review_id}/trace", summary="查看审查智能体运行轨迹")
async def review_trace(
    review_id: str,
    principal: Principal = Depends(current_principal),
) -> dict:
    result = await storage.get_package_review(review_id)
    if result is None:
        raise HTTPException(status_code=404, detail="资料包审查不存在")
    await require_project_role(result["project_id"], principal)
    runs = await storage.list_agent_runs(
        tenant_id=principal.tenant_id,
        project_id=result["project_id"],
        business_id=review_id,
    )
    return {"review_id": review_id, "runs": runs}


@router.get("/{review_id}/stream", summary="订阅审查工作流安全进度")
async def stream_package_review(
    review_id: str,
    principal: Principal = Depends(current_principal),
) -> StreamingResponse:
    review = await storage.get_package_review(review_id)
    if review is None:
        raise HTTPException(status_code=404, detail="资料包审查不存在")
    await require_project_role(review["project_id"], principal)

    async def events():
        workflow_id = f"package-review:{review_id}"
        last = ""
        while True:
            if get_settings().TEMPORAL_ENABLED:
                state = await get_workflow_state(workflow_id)
                safe = {
                    key: state.get(key)
                    for key in ("workflow_id", "status", "temporal_status", "approval", "workers", "error")
                    if key in state
                }
            else:
                current = await storage.get_package_review(review_id)
                safe = {"workflow_id": workflow_id, "status": current["status"] if current else "failed"}
            encoded = json.dumps(safe, ensure_ascii=False)
            if encoded != last:
                last = encoded
                yield f"data: {encoded}\n\n"
            if safe.get("status") in TERMINAL or safe.get("temporal_status") in TERMINAL:
                break
            await asyncio.sleep(1)

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
