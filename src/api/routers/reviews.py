from __future__ import annotations

import asyncio
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from src.api.dependencies import current_principal, rate_limited_principal, require_project_role
from src.core.config import get_settings
from src.core.security import Principal
from src.engineering.review_agents import run_package_review
from src.engineering.schemas import PackageReviewRequest, PackageReviewResponse
from src.engineering.storage import storage
from src.workflows.temporal_app import get_workflow_state, submit_package_review

router = APIRouter(prefix="/api/v1/package-reviews", tags=["package-review"])
TERMINAL = {"completed", "approved", "rejected", "failed", "cancelled", "canceled"}


def _estimated_review_tokens(document_count: int) -> int:
    settings = get_settings()
    return min(settings.DEFAULT_DAILY_TOKEN_LIMIT, 20_000 + (document_count * 15_000))


def _actual_tokens(usage: dict) -> int:
    return sum(
        int(item.get("input_tokens", 0) or 0) + int(item.get("output_tokens", 0) or 0)
        for item in usage.values()
        if isinstance(item, dict)
    )


def _estimated_cost(tokens: int) -> int:
    rate = get_settings().MODEL_ESTIMATED_COST_MICROS_PER_1K_TOKENS
    return ((max(0, tokens) + 999) // 1000) * rate


@router.post("", response_model=PackageReviewResponse)
async def package_review(
    request: PackageReviewRequest,
    principal: Principal = Depends(rate_limited_principal),
) -> PackageReviewResponse:
    await require_project_role(
        request.project_id,
        principal,
        {"admin", "design_engineer", "material_procurement", "reviewer"},
    )
    review_id = uuid.uuid4().hex
    workflow_id = f"package-review:{review_id}"
    try:
        reserved_tokens = _estimated_review_tokens(len(request.document_ids))
        await storage.reserve_budget(
            request.project_id,
            workflow_id,
            reserved_tokens,
            _estimated_cost(reserved_tokens),
        )
    except ValueError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    if get_settings().TEMPORAL_ENABLED:
        queued = {
            "review_id": review_id,
            "status": "queued",
            "engine": "temporal",
            "report": "",
            "sources": [],
            "conflicts": [],
        }
        try:
            await storage.save_package_review(
                queued,
                user_id=principal.user_id,
                project_id=request.project_id,
                question=request.question,
                tenant_id=principal.tenant_id,
            )
            workflow = await submit_package_review(
                review_id,
                request.document_ids,
                request.question,
                principal.user_id,
                request.project_id,
                principal.tenant_id,
            )
        except Exception:
            await storage.settle_budget(workflow_id, 0, status="failed")
            raise
        queued["workflow"] = workflow
        return PackageReviewResponse(**queued)
    try:
        result = await run_package_review(
            request,
            tenant_id=principal.tenant_id,
            user_id=principal.user_id,
        )
    except ValueError as exc:
        await storage.settle_budget(workflow_id, 0, status="failed")
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        await storage.settle_budget(workflow_id, 0, status="failed")
        raise
    result["review_id"] = review_id
    result["workflow"] = None
    await storage.save_package_review(
        result,
        user_id=principal.user_id,
        project_id=request.project_id,
        question=request.question,
        tenant_id=principal.tenant_id,
    )
    actual_tokens = _actual_tokens(result.get("usage", {}))
    await storage.settle_budget(workflow_id, actual_tokens, _estimated_cost(actual_tokens))
    return PackageReviewResponse(**result)


@router.get("/{review_id}", response_model=PackageReviewResponse)
async def get_package_review(
    review_id: str,
    principal: Principal = Depends(current_principal),
) -> PackageReviewResponse:
    result = await storage.get_package_review(review_id)
    if result is None:
        raise HTTPException(status_code=404, detail="资料包审查不存在")
    await require_project_role(result.get("project_id", "default"), principal)
    return PackageReviewResponse(**result)


@router.get("/{review_id}/stream")
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
