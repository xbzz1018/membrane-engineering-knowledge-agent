import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage
from pydantic import ValidationError

from src.agents.review_agents import PackageReviewService, ReviewAgentError, ReviewPlan, WorkerReview
from src.agents.subagent_tools import DomainAgentTools, ScriptedSupervisorModel, run_subagents_as_tools


def service():
    return PackageReviewService(provider=type("Provider", (), {"metadata": {"mode": "fake"}})())


def test_supervisor_parallel_lookup_then_review_with_real_tools(monkeypatch):
    current = service()
    started = set()
    ready = asyncio.Event()

    async def worker(name, question, evidence, memories):
        if name == "review":
            assert {"retrieval", "material"} <= started
            assert "上游结果" in question
        started.add(name)
        if {"retrieval", "material"} <= started:
            ready.set()
        await asyncio.wait_for(ready.wait(), timeout=2)
        return WorkerReview(worker=name, processed_evidence_ids=["e1"]), {"calls": 1}

    monkeypatch.setattr(current, "run_worker", worker)
    outputs, trace = asyncio.run(run_subagents_as_tools(
        current, ReviewPlan(workers=["retrieval", "material", "review"]), "审查资料", [{"evidence_id": "e1"}], [],
    ))
    assert [review.worker for review, _ in outputs] == ["retrieval", "material", "review"]
    assert trace["tool_calls"] == 3
    assert trace["mode"] == "scripted-tool-calling"
    assert len([event for event in trace["events"] if event["status"] == "completed"]) == 3


def test_tools_reject_identity_injection_and_cache_duplicate_calls(monkeypatch):
    current = service()
    calls = []

    async def worker(name, question, evidence, memories):
        calls.append(name)
        return WorkerReview(worker=name), {"calls": 1}

    monkeypatch.setattr(current, "run_worker", worker)

    async def run():
        boundary = DomainAgentTools(current, ["material"], "任务", [], [])
        tool = boundary.tools[0]
        with pytest.raises(ValidationError):
            await tool.ainvoke({"project_id": "other-project"})
        await asyncio.gather(tool.ainvoke({}), tool.ainvoke({}))
        assert calls == ["material"]
        assert boundary.events[-1]["status"] == "reused"

    asyncio.run(run())


def test_focused_review_exposes_only_selected_tool():
    async def run():
        current = service()
        boundary = DomainAgentTools(current, ["review"], "价格", [], [])
        assert [item.name for item in boundary.tools] == ["review_review"]
        with pytest.raises(ReviewAgentError):
            DomainAgentTools(current, ["shell"], "", [], [])

    asyncio.run(run())


def test_supervisor_cannot_claim_completion_without_tools():
    provider = type("Provider", (), {
        "metadata": {"mode": "api"},
        "langchain_model": lambda self, **kwargs: ScriptedSupervisorModel(responses=[AIMessage(content="全部通过")]),
    })()
    current = PackageReviewService(provider=provider)
    with pytest.raises(ReviewAgentError, match="未完成必要领域工具"):
        asyncio.run(run_subagents_as_tools(current, ReviewPlan(workers=["material"]), "审查", [], []))


def test_tool_rejects_worker_citing_unavailable_evidence(monkeypatch):
    current = service()

    async def worker(*args):
        return WorkerReview(worker="material", processed_evidence_ids=["other-project:e1"]), {}

    monkeypatch.setattr(current, "run_worker", worker)

    async def run():
        boundary = DomainAgentTools(current, ["material"], "审查", [{"evidence_id": "e1"}], [])
        with pytest.raises(ReviewAgentError, match="越界"):
            await boundary.tools[0].ainvoke({})

    asyncio.run(run())


def test_temporal_activity_uses_the_same_domain_tool_boundary(monkeypatch):
    from temporalio.testing import ActivityEnvironment

    from src.workflows import activities

    current = service()
    current.collect_evidence = AsyncMock(return_value=([], [{"evidence_id": "e1"}], []))
    current.memory = SimpleNamespace(search=AsyncMock(return_value=[]))
    current.run_worker = AsyncMock(return_value=(
        WorkerReview(worker="material", processed_evidence_ids=["e1"]), {"calls": 1},
    ))
    store = SimpleNamespace(
        start_agent_run=AsyncMock(return_value="run-1"),
        add_agent_step=AsyncMock(), finish_agent_run=AsyncMock(),
    )
    monkeypatch.setattr(activities, "storage", store)
    monkeypatch.setattr(activities, "get_package_review_service", lambda: current)
    result = asyncio.run(ActivityEnvironment().run(activities.review_worker_activity, {
        "worker": "material", "tenant_id": "test-tenant", "project_id": "demo-project",
        "user_id": "test-user", "review_id": "review-1", "document_ids": ["d1"], "question": "膜材审查",
    }))
    assert result["usage"]["tool"] == "review_material"
    assert result["review"]["processed_evidence_ids"] == ["e1"]
    current.run_worker.assert_awaited_once()
