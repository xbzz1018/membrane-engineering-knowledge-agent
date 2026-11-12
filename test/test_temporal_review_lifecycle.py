import asyncio
import uuid

import pytest

from src.infrastructure.database import storage
from src.infrastructure.review_decisions import ReviewDecisionRepository
from src.infrastructure.review_lifecycle import set_review_terminal
from src.main import app
from src.workflows.temporal_definitions import PackageReviewWorkflow


def report(review_id, status="awaiting_approval"):
    return {"review_id": review_id, "status": status, "engine": "test", "report": "synthetic",
            "sources": [{"source_id": "e1"}], "usage": {}, "issues": [{
                "issue_id": "i1", "status": "pending_human", "severity": "conflict", "requires_human": True,
            }], "human_review_required": True}


async def save(payload):
    await storage.save_package_review(payload, user_id="test-user", project_id="demo-project", question="test")


def test_publication_retry_never_overwrites_human_edits_or_sources():
    async def run():
        async with app.router.lifespan_context(app):
            rid = uuid.uuid4().hex
            payload = report(rid)
            await save(payload)
            await ReviewDecisionRepository(storage).mutate(rid, expected_lock_version=1, actor="reviewer",
                issue_id="i1", issue_status="resolved", reason="已核对")
            before = await storage.get_package_review(rid)
            payload.update(sources=[{"source_id": "wrong"}], report="retry result")
            await save(payload)
            after = await storage.get_package_review(rid)
            assert after == before
    asyncio.run(run())


def test_durable_early_decision_consumption_is_idempotent_and_blocks_competitors():
    async def run():
        async with app.router.lifespan_context(app):
            rid = uuid.uuid4().hex
            await save(report(rid))
            repo = ReviewDecisionRepository(storage)
            receipt = await repo.mutate(rid, expected_lock_version=1, actor="reviewer-a", decision="rejected",
                reason="需补充依据", defer_temporal=True)
            assert receipt["decision_pending"] and receipt["command_id"]
            with pytest.raises(ValueError):
                await repo.mutate(rid, expected_lock_version=1, actor="reviewer-b", decision="rejected",
                    reason="competing", defer_temporal=True)
            with pytest.raises(ValueError):
                await repo.mutate(rid, expected_lock_version=2, actor="reviewer-a", issue_id="i1", issue_status="resolved")
            first = await repo.consume_pending_decision(rid)
            second = await repo.consume_pending_decision(rid)
            assert first == second and first["status"] == "rejected"
            row = await storage.get_package_review(rid)
            assert len(row["usage"]["human_review_events"]) == 1
            assert row["usage"]["pending_review_decision"]["actor"] == "reviewer-a"
            assert await storage.update_package_review_status(rid, "rejected")
            assert not await storage.update_package_review_status(rid, "approved")
    asyncio.run(run())


@pytest.mark.parametrize("terminal", ["cancelled", "failed"])
def test_terminal_retry_and_late_report_cannot_resurrect_task(terminal):
    async def run():
        async with app.router.lifespan_context(app):
            rid = uuid.uuid4().hex
            await save(report(rid, "queued"))
            assert await set_review_terminal(storage, rid, terminal)
            first = await storage.get_package_review(rid)
            assert await set_review_terminal(storage, rid, terminal)
            assert not await set_review_terminal(storage, rid, "failed" if terminal == "cancelled" else "cancelled")
            await save(report(rid))
            assert await storage.get_package_review(rid) == first
    asyncio.run(run())


def test_bare_early_signals_only_wake_workflow_and_never_bypass_human_gate():
    async def run():
        workflow = PackageReviewWorkflow()
        workflow._state["status"] = "running"
        await workflow.reject("untrusted")
        await workflow.approve()
        assert workflow._decision_wake == 2 and workflow._decision is None
        workflow._state["status"] = "awaiting_approval"
        assert workflow._decision is None
    asyncio.run(run())


def test_snapshot_stays_fixed_after_reindex_and_is_scope_checked():
    from src.domain.schemas import PackageReviewRequest
    from src.infrastructure.review_manifest import freeze_review_manifest, read_review_manifest
    from src.workflows.activities import _collect_review_evidence

    async def run():
        async with app.router.lifespan_context(app):
            doc = await storage.add_document("design.txt", "text/plain", uuid.uuid4().hex.encode(), "basic")
            await storage.save_chunks(doc["id"], [{"chunk_index": 0, "text": "原始冻结证据"}], "basic")
            rid = uuid.uuid4().hex
            frozen = [{"evidence_id": doc["id"] + ":0", "text": "原始冻结证据"}]
            await freeze_review_manifest(storage, rid, doc["tenant_id"], doc["project_id"], [doc], frozen, [])
            await storage.save_chunks(doc["id"], [{"chunk_index": 0, "text": "重新索引改变的证据"}], "basic")
            service = type("Service", (), {"provider": type("Provider", (), {"metadata": {"mode": "fake"}})()})()
            _, evidence, _ = await _collect_review_evidence(service,
                PackageReviewRequest(document_ids=[doc["id"]], project_id=doc["project_id"]), {
                    "review_id": rid, "project_id": doc["project_id"], "tenant_id": doc["tenant_id"], "manifest_required": True,
                })
            assert evidence == frozen
            with pytest.raises(ValueError, match="快照"):
                await read_review_manifest(storage, rid, "other-tenant", doc["project_id"])
            with pytest.raises(ValueError, match="不同证据快照"):
                await freeze_review_manifest(storage, rid, doc["tenant_id"], doc["project_id"], [doc], [], [])
    asyncio.run(run())


def test_compose_failure_after_commit_does_not_erase_intervening_human_review(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from temporalio.testing import ActivityEnvironment

    from src.workflows import activities

    async def run():
        async with app.router.lifespan_context(app):
            rid = uuid.uuid4().hex
            payload = report(rid)
            service = SimpleNamespace(collect_evidence=AsyncMock(return_value=([], [], [])),
                compose_and_organize=AsyncMock(return_value=payload))
            monkeypatch.setattr(activities, "get_package_review_service", lambda: service)
            monkeypatch.setattr(storage, "settle_budget", AsyncMock(side_effect=[RuntimeError("after commit"), True]))
            args = {"review_id": rid, "tenant_id": "membrane-company", "project_id": "demo-project",
                    "user_id": "test-user", "document_ids": ["doc1"], "question": "test", "worker_outputs": [],
                    "review_plan": {"workers": ["material"]}}
            env = ActivityEnvironment()
            with pytest.raises(RuntimeError, match="after commit"):
                await env.run(activities.compose_package_review_activity, args)
            await ReviewDecisionRepository(storage).mutate(rid, expected_lock_version=1,
                actor="reviewer", issue_id="i1", issue_status="resolved", reason="已复核")
            before = await storage.get_package_review(rid)
            await env.run(activities.compose_package_review_activity, args)
            assert await storage.get_package_review(rid) == before
    asyncio.run(run())


def test_finalize_activity_replays_only_committed_commands_and_terminal_activity_syncs(monkeypatch):
    from unittest.mock import AsyncMock

    from temporalio.testing import ActivityEnvironment

    from src.workflows import activities

    async def run():
        async with app.router.lifespan_context(app):
            env = ActivityEnvironment()
            rid = uuid.uuid4().hex
            await save(report(rid))
            assert await env.run(activities.finalize_package_review_activity,
                                 {"review_id": rid, "status": "approved"}) is None
            await ReviewDecisionRepository(storage).mutate(rid, expected_lock_version=1,
                actor="reviewer", decision="rejected", reason="依据不足", defer_temporal=True)
            first = await env.run(activities.finalize_package_review_activity, {"review_id": rid})
            assert first == await env.run(activities.finalize_package_review_activity, {"review_id": rid})
            assert first["status"] == "rejected"
            queued = uuid.uuid4().hex
            await save(report(queued, "queued"))
            monkeypatch.setattr(storage, "settle_budget", AsyncMock(return_value=True))
            result = await env.run(activities.settle_review_budget_activity,
                                   {"review_id": queued, "status": "cancelled"})
            assert result["terminal_synced"]
            assert (await storage.get_package_review(queued))["status"] == "cancelled"
    asyncio.run(run())
