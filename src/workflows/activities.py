from __future__ import annotations

from src.engineering.deep_review import run_package_review
from src.engineering.parsing import parse_document
from src.engineering.schemas import PackageReviewRequest
from src.engineering.storage import storage


async def parse_and_index_activity(document_id: str) -> dict:
    document = await storage.get_document(document_id)
    if not document:
        raise ValueError(f"document not found: {document_id}")
    chunks, parser = await parse_document(document["stored_path"])
    count = await storage.save_chunks(document_id, chunks, parser)
    return {"document_id": document_id, "chunks": count, "parser": parser, "status": "indexed"}


async def package_review_activity(payload: dict) -> dict:
    request = PackageReviewRequest(
        user_id="temporal-worker",
        project_id="default",
        document_ids=payload["document_ids"],
        question=payload.get("question", "比较资料中的设计方案和膜材规格"),
    )
    return await run_package_review(request)
