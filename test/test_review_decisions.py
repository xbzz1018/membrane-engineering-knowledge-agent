from __future__ import annotations

import asyncio
import uuid

import httpx

from src.infrastructure.database import storage
from src.main import app


def test_human_review_closure_has_lock_audit_and_terminal_guard():
    async def run():
        async with app.router.lifespan_context(app):
            review_id = "closure-" + uuid.uuid4().hex
            await storage.save_package_review(
                {
                    "review_id": review_id,
                    "status": "awaiting_approval",
                    "engine": "deterministic-fake",
                    "report": "synthetic",
                    "issues": [
                        {
                            "issue_id": "i1",
                            "domain": "material",
                            "issue_type": "thickness_conflict",
                            "summary": "测试差异",
                            "severity": "conflict",
                            "requires_human": True,
                            "status": "pending_human",
                            "evidence_ids": ["e1"],
                        }
                    ],
                    "human_review_required": True,
                },
                user_id="test-user",
                project_id="demo-project",
                question="synthetic",
            )
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
                path = f"/api/v1/package-reviews/{review_id}"
                assert (
                    await client.post(path + "/decision", json={"decision": "approved", "expected_lock_version": 1})
                ).status_code == 409
                assert (
                    await client.patch(path + "/issues/i1", json={"status": "dismissed", "expected_lock_version": 1})
                ).status_code == 409
                resolved = await client.patch(
                    path + "/issues/i1",
                    json={"status": "resolved", "expected_lock_version": 1, "reason": "已核对测试规格"},
                )
                assert resolved.status_code == 200
                assert (
                    await client.post(path + "/decision", json={"decision": "approved", "expected_lock_version": 1})
                ).status_code == 409
                approved = await client.post(
                    path + "/decision", json={"decision": "approved", "expected_lock_version": 2}
                )
                assert approved.status_code == 200
                assert approved.json()["status"] == "approved"
                assert (
                    await client.patch(
                        path + "/issues/i1", json={"status": "pending_human", "expected_lock_version": 3}
                    )
                ).status_code == 409
            review = await storage.get_package_review(review_id)
            events = review["usage"]["human_review_events"]
            assert len(events) == 2 and events[0]["reason"] == "已核对测试规格"
            assert events[1]["action"] == "approved" and events[1]["actor"]

    asyncio.run(run())


def test_rejection_requires_reason_and_only_one_competing_decision_wins():
    from src.infrastructure.review_decisions import ReviewDecisionRepository

    async def run():
        async with app.router.lifespan_context(app):
            repo = ReviewDecisionRepository(storage)
            review_id = "decision-race-" + uuid.uuid4().hex
            await storage.save_package_review(
                {
                    "review_id": review_id,
                    "status": "awaiting_approval",
                    "engine": "deterministic-fake",
                    "report": "synthetic",
                    "issues": [],
                },
                user_id="u",
                project_id="demo-project",
                question="synthetic",
            )
            results = await asyncio.gather(
                repo.mutate(review_id, expected_lock_version=1, actor="r1", decision="approved"),
                repo.mutate(review_id, expected_lock_version=1, actor="r2", decision="rejected", reason="补充资料"),
                return_exceptions=True,
            )
            assert sum(isinstance(item, dict) for item in results) == 1
            assert sum(isinstance(item, ValueError) for item in results) == 1

    asyncio.run(run())


def test_legacy_approval_endpoint_cannot_bypass_issue_gate():
    async def run():
        async with app.router.lifespan_context(app):
            review_id = "legacy-" + uuid.uuid4().hex
            await storage.save_package_review(
                {
                    "review_id": review_id,
                    "status": "awaiting_approval",
                    "engine": "deterministic-fake",
                    "report": "synthetic",
                    "issues": [{"issue_id": "i1", "requires_human": True, "status": "pending_human"}],
                },
                user_id="u",
                project_id="demo-project",
                question="synthetic",
            )
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
                path = f"/api/v1/workflows/package-review:{review_id}/approve"
                assert (await client.post(path)).status_code == 422
                assert (await client.post(path, json={"expected_lock_version": 1})).status_code == 409

    asyncio.run(run())
