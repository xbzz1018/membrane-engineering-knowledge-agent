"""Run a real restricted three-subagent package review and verify persistence."""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from pathlib import Path

import httpx
from sqlalchemy import func, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core.config import get_settings
from src.engineering.storage import SessionFactory, package_review_evidence, package_reviews
from src.main import app


async def main() -> None:
    settings = get_settings()
    if settings.RUNTIME_MODE.lower() != "full" or not settings.DEEPAGENTS_ENABLED:
        raise RuntimeError("validate_deepagents.py requires Full mode and DEEPAGENTS_ENABLED=true")
    suffix = uuid.uuid4().hex[:12]
    documents = [
        (
            f"design-{suffix}.txt",
            "Design package version 1 dated 2025-01-15. PTFE tensile canopy. "
            "The concept record states membrane thickness 0.7 mm. This is not a safety calculation.",
        ),
        (
            f"material-price-{suffix}.txt",
            "Material schedule version 2 dated 2025-02-20. PTFE membrane thickness 0.8 mm. "
            "Synthetic price scenario: CNY 300-360/m2 dated 2025-02, not a formal quotation.",
        ),
    ]

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=600) as client:
            document_ids = []
            for filename, content in documents:
                uploaded = await client.post(
                    "/api/v1/documents/upload",
                    files={"file": (filename, content.encode("utf-8"), "text/plain")},
                )
                uploaded.raise_for_status()
                document_id = uploaded.json()["document_id"]
                indexed = await client.post(f"/api/v1/documents/{document_id}/index")
                indexed.raise_for_status()
                document_ids.append(document_id)

            review = await client.post(
                "/api/v1/package-reviews",
                json={
                    "user_id": f"reviewer-{suffix}",
                    "project_id": f"project-{suffix}",
                    "document_ids": document_ids,
                    "question": "分别审查设计、膜材和价格资料，指出厚度冲突并保留页码证据。",
                },
            )
            review.raise_for_status()
            payload = review.json()
            if payload["engine"] != "deepagents" or payload["status"] != "completed":
                raise AssertionError(f"Unexpected DeepAgents result metadata: {payload['engine']}/{payload['status']}")
            if len(payload["report"]) < 100:
                raise AssertionError("DeepAgents report is unexpectedly short")
            if len(payload["sources"]) < 4:
                raise AssertionError("DeepAgents review did not retain document evidence")
            persisted = await client.get(f"/api/v1/package-reviews/{payload['review_id']}")
            persisted.raise_for_status()
            stored = persisted.json()
            if stored["report"] != payload["report"] or stored["sources"] != payload["sources"]:
                raise AssertionError("Persisted DeepAgents report or evidence differs from response")

        async with SessionFactory() as session:
            review_count = await session.scalar(
                select(func.count()).select_from(package_reviews).where(package_reviews.c.id == payload["review_id"])
            )
            evidence_count = await session.scalar(
                select(func.count())
                .select_from(package_review_evidence)
                .where(package_review_evidence.c.review_id == payload["review_id"])
            )
        summary = {
            "engine": payload["engine"],
            "report_chars": len(payload["report"]),
            "sources": len(payload["sources"]),
            "conflicts": len(payload["conflicts"]),
            "persisted_reviews": review_count,
            "persisted_evidence": evidence_count,
        }
        if review_count != 1 or evidence_count != len(payload["sources"]):
            raise AssertionError(f"DeepAgents persistence validation failed: {summary}")
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
