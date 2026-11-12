from __future__ import annotations

import asyncio
import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from langchain_core.messages import AIMessage
from pydantic import ValidationError

from src.agents.conversation_supervisor import ConversationSupervisor, SupervisorRouter, scoped_session
from src.agents.knowledge_agent import AgentProtocolError, KnowledgeAgent
from src.core.config import Settings
from src.core.security import Principal
from src.domain.chat_routing import ChatRoutingDecision, ChatRoutingInfo, enforce_route, rule_decision
from src.infrastructure.database import storage
from src.infrastructure.model_provider import ModelProvider
from src.main import app


@pytest.mark.parametrize(("query", "intent", "mode"), [
    ("什么是膜结构？", "direct_chat", "direct"),
    ("你好", "direct_chat", "direct"),
    ("查找2025年停车棚项目资料", "knowledge_search", "single"),
    ("PVDF-502规格和厚度是多少", "material_query", "single"),
    ("历史停车棚案例以及PVDF材料规格", "combined_query", "parallel"),
    ("查历史项目采用的膜材规格", "combined_query", "sequential"),
    ("如何生成项目书？", "direct_chat", "direct"),
    ("给我生成800平方米停车棚初步方案", "generate_project", "action"),
    ("请审查这个资料包", "review_package", "action"),
    ("它的规格是什么", "clarify", "clarify"),
    ("不要生成项目书，只介绍原理", "direct_chat", "direct"),
    ("不要审查资料，查询PVDF-502规格", "material_query", "single"),
])
def test_rule_routes(query, intent, mode):
    decision = rule_decision(query)
    assert decision.intent == intent
    assert decision.execution_mode == mode


def test_routing_schema_and_server_guard():
    with pytest.raises(ValidationError):
        ChatRoutingDecision(intent="direct_chat", agents=["shell"])
    with pytest.raises(ValidationError):
        ChatRoutingDecision(intent="direct_chat", material_depends_on_retrieval=True)
    with pytest.raises(ValidationError):
        ChatRoutingDecision(intent="combined_query", material_depends_on_retrieval="true")
    decision, guarded = enforce_route(ChatRoutingDecision(intent="direct_chat"), "查公司PTFE-502规格")
    assert guarded and decision.intent == "combined_query"
    decision, guarded = enforce_route(ChatRoutingDecision(intent="generate_project"), "如何生成项目书？")
    assert guarded and decision.intent == "direct_chat"
    assert decision.roles == []


def test_followup_uses_previous_user_but_does_not_cross_scope():
    history = [{"role": "user", "content": "查询PVDF-502规格"}, {"role": "assistant", "content": "回答"}]
    decision = rule_decision("它的厚度是多少", history)
    assert "PVDF-502" in decision.material_query
    principal = Principal("u", "name", "t", "admin")
    assert scoped_session(principal, "p1", "same") != scoped_session(principal, "p2", "same")
    assert len(scoped_session(principal, "p1", "same")) < 128


def fake_supervisor():
    provider = ModelProvider(Settings(_env_file=None, MODEL_MODE="fake", ROLE_MODEL_ROUTING_ENABLED=False))
    return ConversationSupervisor(KnowledgeAgent(store=storage, provider=provider))


def routing_info(decision):
    return ChatRoutingInfo(intent=decision.intent, execution_mode=decision.execution_mode, decision_source="rules")


def output(role="retrieval", text="型号PTFE-502", outcome="ok"):
    return {
        "answer": text + " [e1]", "sources": [{"source_id": "e1", "title": "规格书"}],
        "_tool_evidence": [{"evidence_id": "e1", "text": text}], "uncertainties": [],
        "outcome": outcome, "usage": {"model_usage": {"input_tokens": 0, "output_tokens": 0}},
    }


def test_independent_queries_really_overlap_and_no_review(monkeypatch):
    async def run():
        supervisor = fake_supervisor()
        started, done = set(), asyncio.Event()

        async def worker(role, *_args):
            started.add(role)
            if len(started) == 2:
                done.set()
            await asyncio.wait_for(done.wait(), 1)
            return output(role)

        monkeypatch.setattr(supervisor, "_query_role", worker)
        decision = rule_decision("历史停车棚案例以及PTFE材料规格")
        result = await supervisor._queries(Principal("u", "n", "t", "admin"), "p", decision, [], routing_info(decision))
        assert started == {"retrieval", "material"}
        assert "ReviewAgent" not in result["usage"]["agents_used"]
        boundary = supervisor._query_tools(Principal("u", "n", "t", "admin"), "p", decision, [])
        with pytest.raises(ValidationError):
            await boundary["retrieval"].ainvoke({"project_id": "other"})

    asyncio.run(run())


def test_dependent_query_waits_for_cited_material_identity(monkeypatch):
    async def run():
        supervisor = fake_supervisor()
        calls = []

        async def worker(role, _principal, _project, query, _memories):
            calls.append(role)
            if role == "material":
                assert calls == ["retrieval", "material"]
                assert "PTFE-502" in query
            return output(role)

        monkeypatch.setattr(supervisor, "_query_role", worker)
        decision = rule_decision("查历史项目采用的膜材规格")
        routing = routing_info(decision)
        await supervisor._queries(Principal("u", "n", "t", "admin"), "p", decision, [], routing)
        assert routing.outcomes == {"retrieval": "ok", "material": "ok"}

    asyncio.run(run())


def test_ambiguous_dependency_does_not_guess_or_call_material(monkeypatch):
    async def run():
        supervisor = fake_supervisor()
        worker = AsyncMock(return_value=output(text="PTFE-502与PVDF-503均有历史记录"))
        monkeypatch.setattr(supervisor, "_query_role", worker)
        decision = rule_decision("查历史项目采用的膜材规格")
        routing = routing_info(decision)
        result = await supervisor._queries(Principal("u", "n", "t", "admin"), "p", decision, [], routing)
        assert worker.await_count == 1
        assert routing.outcomes["material"] == "blocked"
        assert "请明确" in result["answer"]

    asyncio.run(run())


def test_one_query_failure_stays_failure_and_all_failures_raise(monkeypatch):
    async def run():
        supervisor = fake_supervisor()

        async def worker(role, *_args):
            if role == "material":
                raise RuntimeError("network error")
            return output(role)

        monkeypatch.setattr(supervisor, "_query_role", worker)
        decision = rule_decision("历史案例以及PTFE规格")
        routing = routing_info(decision)
        result = await supervisor._queries(Principal("u", "n", "t", "admin"), "p", decision, [], routing)
        assert routing.outcomes == {"retrieval": "ok", "material": "failed"}
        assert "不能视为没有相关资料" in result["answer"]
        monkeypatch.setattr(supervisor, "_query_role", AsyncMock(side_effect=RuntimeError("down")))
        with pytest.raises(AgentProtocolError, match="All selected"):
            await supervisor._queries(Principal("u", "n", "t", "admin"), "p", decision, [], routing_info(decision))

    asyncio.run(run())


def test_query_timeout_is_explicit(monkeypatch):
    async def run():
        supervisor = fake_supervisor()
        supervisor.query_timeout = 1

        async def worker(role, *_args):
            if role == "material":
                await asyncio.Event().wait()
            return output(role)

        monkeypatch.setattr(supervisor, "_query_role", worker)
        decision = rule_decision("历史案例以及PTFE规格")
        routing = routing_info(decision)
        await supervisor._queries(Principal("u", "n", "t", "admin"), "p", decision, [], routing)
        assert routing.outcomes["material"] == "timeout"

    asyncio.run(run())


def test_router_retries_json_but_never_falls_back_to_fake(monkeypatch):
    async def run():
        response = AsyncMock(side_effect=[
            {"messages": [AIMessage(content="invalid JSON")]},
            {"messages": [AIMessage(content='{"intent":"direct_chat"}')]},
        ])
        monkeypatch.setattr("src.agents.conversation_supervisor.create_agent", lambda **_kwargs: SimpleNamespace(ainvoke=response))
        provider = SimpleNamespace(metadata={"mode": "api"}, langchain_model=lambda **_kwargs: object())
        decision, source, _usage = await SupervisorRouter(provider).route("查询PTFE-502厚度", [])
        assert response.await_count == 2
        assert decision.intent == "material_query" and source == "server_guard"
        response.side_effect = [{"messages": [AIMessage(content="bad")]}] * 2
        with pytest.raises(AgentProtocolError, match="invalid routing JSON"):
            await SupervisorRouter(provider).route("什么是膜结构", [])

    asyncio.run(run())


def test_empty_query_result_is_distinct_from_failure_and_drops_model_guess(monkeypatch):
    async def run():
        supervisor = fake_supervisor()
        supervisor.knowledge.provider = SimpleNamespace(metadata={"mode": "api"})
        monkeypatch.setattr(supervisor, "_provider", lambda _role: supervisor.knowledge.provider)
        monkeypatch.setattr(supervisor.knowledge, "_invoke_api", AsyncMock(return_value={
            "answer": "未经证据支持的猜测", "_tool_evidence": [], "sources": [], "usage": {},
        }))
        result = await supervisor._query_role("material", Principal("u", "n", "t", "admin"), "p", "PTFE-502", [])
        assert result["outcome"] == "no_results"
        assert "猜测" not in result["answer"]
        assert "未找到" in result["answer"]

    asyncio.run(run())


def test_document_read_tool_cannot_leave_bound_project():
    from src.application.authorization import ProjectAuthorizationService
    from src.application.knowledge import KnowledgeQueryError, KnowledgeQueryService

    async def run():
        store = SimpleNamespace(get_document=AsyncMock(return_value={
            "id": "other-doc", "project_id": "other-project", "tenant_id": "t",
        }))
        service = KnowledgeQueryService(store=store, authorization=ProjectAuthorizationService(store),
                                        retrieval=SimpleNamespace())
        with pytest.raises(KnowledgeQueryError, match="无访问权限"):
            await service.get_document_evidence(Principal("u", "n", "t", "admin"), "other-doc", project_id="p")

    asyncio.run(run())


def test_authorization_failure_precedes_model_or_history_access(monkeypatch):
    async def run():
        supervisor = fake_supervisor()
        supervisor.authorization = SimpleNamespace(authorize=AsyncMock(side_effect=RuntimeError("denied")))
        router = AsyncMock(side_effect=AssertionError("must not call router"))
        monkeypatch.setattr(supervisor.router, "route", router)
        with pytest.raises(RuntimeError, match="denied"):
            await supervisor.ainvoke(Principal("u", "n", "t", "admin"), "p", "s", "什么是膜结构")
        assert router.await_count == 0

    asyncio.run(run())


def test_http_direct_chat_and_sse_metadata_and_action_guidance(monkeypatch):
    async def run():
        async with app.router.lifespan_context(app):
            supervisor = fake_supervisor()
            monkeypatch.setattr("src.api.routers.chat.get_conversation_supervisor", lambda: supervisor)
            tools = AsyncMock(side_effect=AssertionError("direct chat must not call tools"))
            monkeypatch.setattr(supervisor, "_query_role", tools)
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                session = uuid.uuid4().hex
                response = await client.post("/api/v1/chat", json={"message": "什么是膜结构？", "session_id": session})
                assert response.status_code == 200
                result = response.json()
                assert result["route"] == "direct_chat"
                assert result["answer_origin"] == "general_knowledge" and result["sources"] == []
                assert result["routing"]["needs_review"] is False
                assert tools.await_count == 0
                response = await client.post("/api/v1/chat/stream", json={"message": "你好", "session_id": uuid.uuid4().hex})
                events = [json.loads(line.removeprefix("data: ")) for line in response.text.splitlines() if line.startswith("data: ")]
                assert events[-1]["route"] == "direct_chat"
                assert events[-1]["routing"]["execution_mode"] == "direct"
                result = (await client.post("/api/v1/chat", json={
                    "message": "审查这个资料包", "session_id": uuid.uuid4().hex,
                })).json()
                assert result["routing"]["action_status"] == "existing_api_required"
                assert result["routing"]["needs_review"] is True
                assert "没有创建审查任务" in result["answer"]

    asyncio.run(run())
