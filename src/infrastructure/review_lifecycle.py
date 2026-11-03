"""Idempotent persistence guards for Temporal package review lifecycles."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, delete, insert, select, update
from sqlalchemy.exc import IntegrityError

from src.core.config import get_settings
from src.infrastructure.database import EngineeringStorage, package_review_evidence, package_reviews

PUBLISH_PLACEHOLDER_STATUSES = {"queued", "created", "running"}
TERMINAL_STATUSES = {"cancelled", "failed"}
TERMINAL_SOURCE_STATUSES = {
    "queued",
    "created",
    "running",
    "awaiting_approval",
    "completed",
    "decision_pending",
}


def _json(value: Any, default: Any) -> str:
    return json.dumps(value if value is not None else default, ensure_ascii=False)


def _evidence_rows(review_id: str, sources: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [
        {
            "id": f"{review_id}:{index}",
            "review_id": review_id,
            "source_id": str(source.get("source_id", index)),
            "payload": _json(source, {}),
        }
        for index, source in enumerate(sources)
    ]


async def publish_review_once(
    store: EngineeringStorage,
    result: dict[str, Any],
    *,
    user_id: str,
    project_id: str,
    question: str,
    review_mode: str = "full",
    tenant_id: str | None = None,
) -> None:
    """Publish a composed report without overwriting a later lifecycle state.

    A queued/created/running row is an intentionally replaceable placeholder. Once
    composition has published a report, every later retry becomes a no-op. The
    evidence replacement and report update share one transaction.
    """

    review_id = str(result["review_id"])
    now = datetime.now(UTC)
    values = {
        "tenant_id": tenant_id or get_settings().DEFAULT_TENANT_ID,
        "user_id": user_id,
        "project_id": project_id,
        "question": question,
        "review_mode": review_mode,
        "status": str(result.get("status", "completed")),
        "engine": str(result.get("engine", "")),
        "report": str(result.get("report", "")),
        "conflicts": _json(result.get("conflicts", []), []),
        "worker_results": _json(result.get("worker_results", {}), {}),
        "issues": _json(result.get("issues", []), []),
        "usage": _json(result.get("usage", {}), {}),
        "human_review_required": int(bool(result.get("human_review_required"))),
        "updated_at": now,
    }
    evidence = _evidence_rows(review_id, list(result.get("sources", [])))

    async with store.session_factory() as session:
        row = (
            (await session.execute(
                select(package_reviews).where(package_reviews.c.id == review_id).with_for_update()
            ))
            .mappings()
            .first()
        )
        if row is None:
            try:
                await session.execute(
                    insert(package_reviews).values(
                        id=review_id,
                        **values,
                        lock_version=1,
                        created_at=now,
                    )
                )
            except IntegrityError:
                await session.rollback()
                raise RuntimeError("concurrent report publication; retry after reading the winning row") from None
            if evidence:
                await session.execute(insert(package_review_evidence), evidence)
            await session.commit()
            return

        if row["tenant_id"] != values["tenant_id"] or row["project_id"] != project_id or row["user_id"] != user_id:
            raise ValueError("review identity cannot be rebound")

        if row["status"] not in PUBLISH_PLACEHOLDER_STATUSES:
            await session.rollback()
            return

        updated = await session.execute(
            update(package_reviews)
            .where(
                and_(
                    package_reviews.c.id == review_id,
                    package_reviews.c.lock_version == row["lock_version"],
                    package_reviews.c.status.in_(PUBLISH_PLACEHOLDER_STATUSES),
                )
            )
            .values(**values, lock_version=package_reviews.c.lock_version + 1)
        )
        if not updated.rowcount:
            await session.rollback()
            raise RuntimeError("review changed during publication; retry")
        await session.execute(
            delete(package_review_evidence).where(package_review_evidence.c.review_id == review_id)
        )
        if evidence:
            await session.execute(insert(package_review_evidence), evidence)
        await session.commit()


async def set_review_terminal(store: EngineeringStorage, review_id: str, status: str) -> bool:
    """Persist a cancellation/failure terminal state with an optimistic CAS."""

    if status not in TERMINAL_STATUSES:
        return False
    now = datetime.now(UTC)
    async with store.session_factory() as session:
        row = (
            (await session.execute(
                select(package_reviews).where(package_reviews.c.id == review_id).with_for_update()
            ))
            .mappings()
            .first()
        )
        if row is None:
            await session.rollback()
            return False
        current_status = str(row["status"])
        if current_status == status:
            await session.rollback()
            return True
        if current_status not in TERMINAL_SOURCE_STATUSES:
            await session.rollback()
            return False
        if current_status == "decision_pending":
            try:
                usage = json.loads(row["usage"] or "{}")
            except (TypeError, ValueError):
                usage = {}
            pending = usage.get("pending_review_decision")
            if isinstance(pending, dict) and not pending.get("consumed_status"):
                await session.rollback()
                return False
        updated = await session.execute(
            update(package_reviews)
            .where(
                and_(
                    package_reviews.c.id == review_id,
                    package_reviews.c.lock_version == row["lock_version"],
                    package_reviews.c.status == current_status,
                )
            )
            .values(status=status, updated_at=now, lock_version=package_reviews.c.lock_version + 1)
        )
        if not updated.rowcount:
            await session.rollback()
            raise RuntimeError("review changed during terminal synchronization; retry")
        await session.commit()
        return True
