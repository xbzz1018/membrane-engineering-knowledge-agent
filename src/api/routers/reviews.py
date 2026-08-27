from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src.core.config import get_settings
from src.engineering.deep_review import run_package_review
from src.engineering.schemas import PackageReviewRequest, PackageReviewResponse
from src.events.kafka_events import publisher
from src.workflows.temporal_app import submit_package_review

router = APIRouter(prefix="/api/v1/package-reviews", tags=["package-review"])


@router.post("", response_model=PackageReviewResponse)
async def package_review(request: PackageReviewRequest) -> PackageReviewResponse:
    if get_settings().TEMPORAL_ENABLED:
        review_id = __import__("uuid").uuid4().hex
        workflow = await submit_package_review(review_id, request.document_ids, request.question)
        return PackageReviewResponse(
            review_id=review_id,
            status="queued",
            engine="temporal",
            report="",
            workflow=workflow,
        )
    try:
        result = await run_package_review(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    result["workflow"] = await publisher.publish(
        "package.review.completed", result["review_id"], {"document_ids": request.document_ids}
    )
    return PackageReviewResponse(**result)
