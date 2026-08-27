from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException

from src.core.config import get_settings
from src.engineering.deep_review import run_package_review
from src.engineering.schemas import PackageReviewRequest, PackageReviewResponse
from src.engineering.storage import storage
from src.events.kafka_events import publisher
from src.workflows.temporal_app import submit_package_review

router = APIRouter(prefix="/api/v1/package-reviews", tags=["package-review"])


@router.post("", response_model=PackageReviewResponse)
async def package_review(request: PackageReviewRequest) -> PackageReviewResponse:
    if get_settings().TEMPORAL_ENABLED:
        review_id = uuid.uuid4().hex
        queued = {
            "review_id": review_id,
            "status": "queued",
            "engine": "temporal",
            "report": "",
            "sources": [],
            "conflicts": [],
        }
        await storage.save_package_review(
            queued,
            user_id=request.user_id,
            project_id=request.project_id,
            question=request.question,
        )
        workflow = await submit_package_review(
            review_id,
            request.document_ids,
            request.question,
            request.user_id,
            request.project_id,
        )
        queued["workflow"] = workflow
        return PackageReviewResponse(**queued)
    try:
        result = await run_package_review(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    result["workflow"] = await publisher.publish(
        "package.review.completed", result["review_id"], {"document_ids": request.document_ids}
    )
    await storage.save_package_review(
        result,
        user_id=request.user_id,
        project_id=request.project_id,
        question=request.question,
    )
    return PackageReviewResponse(**result)


@router.get("/{review_id}", response_model=PackageReviewResponse)
async def get_package_review(review_id: str) -> PackageReviewResponse:
    result = await storage.get_package_review(review_id)
    if result is None:
        raise HTTPException(status_code=404, detail="资料包审查不存在")
    return PackageReviewResponse(**result)
