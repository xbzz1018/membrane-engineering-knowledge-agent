"""Transactional human review mutations using the report's existing metadata JSON."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, select

from src.infrastructure.database import EngineeringStorage, package_reviews

EDITABLE = {"awaiting_approval", "completed"}


class ReviewDecisionRepository:
    def __init__(self, store: EngineeringStorage):
        self.store = store

    async def mutate(
        self,
        review_id: str,
        *,
        expected_lock_version: int,
        actor: str,
        decision: str = "",
        issue_id: str = "",
        issue_status: str = "",
        reason: str = "",
        defer_temporal: bool = False,
    ) -> dict[str, Any]:
        if decision not in {"", "approved", "rejected"} or issue_status not in {
            "",
            "resolved",
            "dismissed",
            "pending_human",
        }:
            raise ValueError("unsupported review mutation")
        if bool(decision) == bool(issue_id) or (issue_id and not issue_status):
            raise ValueError("exactly one decision or issue mutation required")
        if issue_status == "dismissed" and not reason.strip():
            raise ValueError("忽略问题必须填写原因")
        if decision == "rejected" and not reason.strip():
            raise ValueError("退回必须填写原因")
        async with self.store.session_factory() as session:
            row = (
                (
                    await session.execute(
                        select(package_reviews).where(package_reviews.c.id == review_id).with_for_update()
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                raise LookupError("review not found")
            if row["lock_version"] != expected_lock_version or row["status"] not in EDITABLE:
                raise ValueError("报告版本或状态已变化，请刷新后操作")
            issues = json.loads(row["issues"] or "[]")
            issue = None
            if issue_id:
                issue = next((item for item in issues if item.get("issue_id") == issue_id), None)
                if issue is None:
                    raise LookupError("issue not found")
                issue["status"] = issue_status
                if issue_status == "pending_human":
                    issue["requires_human"] = True
            unresolved = [
                item
                for item in issues
                if (item.get("requires_human") or item.get("severity") == "conflict")
                and item.get("status") not in {"resolved", "dismissed"}
            ]
            if decision == "approved" and unresolved:
                raise ValueError("仍有需要人工处理的问题，先逐条解决或忽略后再批准")
            usage = json.loads(row["usage"] or "{}")
            events = list(usage.get("human_review_events", []))
            now = datetime.now(UTC)
            command_id = ""
            decision_pending = bool(defer_temporal and decision and row["status"] == "awaiting_approval")
            if decision_pending:
                command_id = str(uuid.uuid4())
            events.append(
                {
                    "actor": actor,
                    "action": decision or issue_status,
                    "issue_id": issue_id,
                    "reason": reason[:1000],
                    "at": now.isoformat(),
                    "prior_lock_version": expected_lock_version,
                    **({"command_id": command_id} if command_id else {}),
                }
            )
            usage["human_review_events"] = events
            if decision_pending:
                usage["pending_review_decision"] = {
                    "command_id": command_id,
                    "review_id": review_id,
                    "actor": actor,
                    "decision": decision,
                    "reason": reason[:1000],
                    "expected_lock_version": expected_lock_version,
                    "created_at": now.isoformat(),
                }
                next_status = "decision_pending"
            else:
                next_status = decision or ("awaiting_approval" if unresolved else row["status"])
            updated = await session.execute(
                package_reviews.update()
                .where(
                    and_(
                        package_reviews.c.id == review_id,
                        package_reviews.c.lock_version == expected_lock_version,
                        package_reviews.c.status.in_(EDITABLE),
                    )
                )
                .values(
                    status=next_status,
                    issues=json.dumps(issues, ensure_ascii=False),
                    usage=json.dumps(usage, ensure_ascii=False),
                    human_review_required=int(bool(unresolved)),
                    lock_version=expected_lock_version + 1,
                    updated_at=now,
                )
            )
            if not updated.rowcount:
                raise ValueError("报告已被其他审核人修改")
            await session.commit()
        return {
            "review_id": review_id,
            "status": next_status,
            "issue": issue,
            "lock_version": expected_lock_version + 1,
            "human_review_required": bool(unresolved),
            "command_id": command_id,
            "decision_pending": decision_pending,
        }

    async def consume_pending_decision(self, review_id: str) -> dict[str, Any] | None:
        """Apply one durable Temporal decision, returning the same receipt on replay."""

        async with self.store.session_factory() as session:
            row = (
                (
                    await session.execute(
                        select(package_reviews).where(package_reviews.c.id == review_id).with_for_update()
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                raise LookupError("review not found")
            usage = json.loads(row["usage"] or "{}")
            command = usage.get("pending_review_decision")
            if not isinstance(command, dict):
                await session.rollback()
                return None
            command_id = str(command.get("command_id", ""))
            consumed_status = str(command.get("consumed_status", ""))
            if consumed_status:
                await session.rollback()
                return {
                    "review_id": review_id,
                    "status": consumed_status,
                    "command_id": command_id,
                    "decision_pending": False,
                    "lock_version": int(command.get("consumed_lock_version", row["lock_version"])),
                }
            if row["status"] != "decision_pending" or command.get("decision") not in {"approved", "rejected"}:
                await session.rollback()
                return None
            now = datetime.now(UTC)
            final_status = str(command["decision"])
            command["consumed_status"] = final_status
            command["consumed_at"] = now.isoformat()
            command["consumed_lock_version"] = int(row["lock_version"]) + 1
            usage["pending_review_decision"] = command
            updated = await session.execute(
                package_reviews.update()
                .where(
                    and_(
                        package_reviews.c.id == review_id,
                        package_reviews.c.lock_version == row["lock_version"],
                        package_reviews.c.status == "decision_pending",
                    )
                )
                .values(
                    status=final_status,
                    usage=json.dumps(usage, ensure_ascii=False),
                    lock_version=package_reviews.c.lock_version + 1,
                    updated_at=now,
                )
            )
            if not updated.rowcount:
                await session.rollback()
                return None
            await session.commit()
            return {
                "review_id": review_id,
                "status": final_status,
                "command_id": command_id,
                "decision_pending": False,
                "lock_version": int(row["lock_version"]) + 1,
            }
