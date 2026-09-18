from __future__ import annotations

import asyncio
import uuid
from typing import Any

import httpx
import pytest
from langchain_core.messages import AIMessage, ToolMessage

from src.agents.knowledge_agent import AgentProtocolError, KnowledgeAgent
from src.agents.model_catalog import ModelCapabilityService
from src.core.config import Settings
from src.core.security import Principal
from src.infrastructure.model_provider import (
    ModelProvider,
    ProviderConfigurationError,
    ProviderRequestError,
)
from src.main import app


def run(coro):
    return asyncio.run(coro)


def request(method: str, path: str, **kwargs) -> httpx.Response:
    async def invoke() -> httpx.Response:
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.request(method, path, **kwargs)

    return run(invoke())


def api_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "MODEL_MODE": "api",
        "MODEL_PROVIDER": "deepseek",
        "DEEPSEEK_API_KEY": "test-only-key",
        "DEEPSEEK_API_BASE": "https://deepseek.invalid/v1",
        "DEEPSEEK_MODEL": "deepseek-test",
        "GATEWAY_API_KEY": "gateway-test-key",
        "GATEWAY_API_BASE": "https://gateway.invalid/v1",
        "GATEWAY_MODEL": "gateway-test",
        "EMBEDDING_PROVIDER": "embedding",
        "EMBEDDING_API_KEY": "embedding-test-key",
        "EMBEDDING_API_BASE": "https://embedding.invalid/v1",
        "EMBEDDING_MODEL": "embedding-test",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_api_mode_requires_complete_provider_configuration() -> None:
    settings = Settings(
        _env_file=None,
        MODEL_MODE="api",
        MODEL_PROVIDER="auto",
        DEEPSEEK_API_KEY="",
        GATEWAY_API_KEY="",
        GATEWAY_API_BASE="",
        DASHSCOPE_API_KEY="",
    )
    with pytest.raises(ProviderConfigurationError, match="configured chat provider"):
        ModelProvider(settings)


def test_provider_uses_separate_chat_and_embedding_endpoints() -> None:
    provider = ModelProvider(api_settings())
    assert provider.provider == "deepseek"
    assert provider.model == "deepseek-test"
    assert provider._base_url() == "https://deepseek.invalid/v1"
    embedding = provider._embedding_config()
    assert embedding == (
        "embedding",
        "https://embedding.invalid/v1",
        "embedding-test-key",
        "embedding-test",
    )

    aliased = ModelProvider(api_settings(EMBEDDING_PROVIDER="local"))
    assert aliased._embedding_config()[0] == "embedding"
    assert aliased.embedding_model == "embedding-test"


def test_langchain_model_omits_empty_optional_kwargs() -> None:
    provider = ModelProvider(api_settings())
    model = provider.langchain_model()
    assert model.model_kwargs == {}
    assert model.extra_body is None


def test_api_request_failure_never_falls_back_to_fake(monkeypatch: pytest.MonkeyPatch) -> None:
    class FailingClient:
        def __init__(self, **_: Any):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_: Any):
            return None

        async def post(self, *_: Any, **__: Any):
            raise httpx.ConnectError("test connection failure")

    monkeypatch.setattr("src.infrastructure.model_provider.httpx.AsyncClient", FailingClient)
    provider = ModelProvider(api_settings())
    with pytest.raises(ProviderRequestError, match="chat request failed"):
        run(provider.chat("system", "question"))


def test_empty_api_response_is_retried_without_fake_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    class EmptyThenSuccessClient:
        calls = 0

        def __init__(self, **_: Any):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_: Any):
            return None

        async def post(self, url: str, **__: Any):
            type(self).calls += 1
            content = "" if self.calls == 1 else "real response"
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": content}}], "usage": {}},
                request=httpx.Request("POST", url),
            )

    monkeypatch.setattr("src.infrastructure.model_provider.httpx.AsyncClient", EmptyThenSuccessClient)
    provider = ModelProvider(api_settings(MODEL_RETRY_BACKOFF_SECONDS=0))
    answer, metadata = run(provider.chat("system", "question"))
    assert answer == "real response"
    assert metadata["provider"] == "deepseek"
    assert metadata["attempts"] == 2


def test_uploaded_document_is_searchable_by_filename() -> None:
    filename = f"material-spec-{uuid.uuid4().hex}.txt"
    uploaded = request(
        "POST",
        "/api/v1/documents/upload",
        files={"file": (filename, f"PTFE roof evidence {filename}".encode(), "text/plain")},
    )
    assert uploaded.status_code == 200
    document_id = uploaded.json()["document_id"]
    indexed = request("POST", f"/api/v1/documents/{document_id}/index")
    assert indexed.status_code == 200

    response = request(
        "POST",
        "/api/v1/chat",
        json={"user_id": "filename-user", "session_id": uuid.uuid4().hex, "message": filename},
    )
    assert response.status_code == 200
    document_sources = [source for source in response.json()["sources"] if source["source_type"] == "document"]
    assert any(source["title"] == filename for source in document_sources)
    assert all(source["date"] and source["version"] for source in document_sources)


def test_duplicate_upload_cannot_downgrade_data_classification() -> None:
    content = b"restricted membrane design evidence"
    first = request(
        "POST",
        "/api/v1/documents/upload",
        data={"data_classification": "restricted"},
        files={"file": ("restricted.txt", content, "text/plain")},
    )
    assert first.status_code == 200
    second = request(
        "POST",
        "/api/v1/documents/upload",
        data={"data_classification": "public"},
        files={"file": ("same-content.txt", content, "text/plain")},
    )
    assert second.status_code == 200
    assert second.json()["document_id"] == first.json()["document_id"]
    assert second.json()["data_classification"] == "restricted"


class CaptureProvider:
    metadata = {"provider": "capture", "model": "test", "mode": "api"}


class MemoryStore:
    def __init__(self):
        self.messages: list[tuple[str, str]] = []

    async def append_message(self, user_id: str, session_id: str, role: str, content: str):
        self.messages.append((role, content))

    async def start_agent_run(self, **_: Any) -> str:
        return "run-1"

    async def finish_agent_run(self, *_: Any, **__: Any) -> None:
        return None

class CaptureMemory:
    async def search(self, **_: Any) -> list[str]:
        return ["项目统一使用毫米"]

    async def propose_from_message(self, **_: Any) -> None:
        return None


def test_agent_audits_messages_and_passes_confirmed_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    store = MemoryStore()
    provider = CaptureProvider()
    agent = KnowledgeAgent(store=store, provider=provider)
    agent.memory = CaptureMemory()
    suffix = uuid.uuid4().hex
    captured: dict[str, Any] = {}

    async def invoke_api(principal, project_id, session_id, query, memories):
        captured.update({
            "principal": principal,
            "project_id": project_id,
            "session_id": session_id,
            "query": query,
            "memories": memories,
        })
        return {"answer": "captured answer", "sources": [], "usage": {}}

    monkeypatch.setattr(agent, "_invoke_api", invoke_api)
    principal = Principal(f"user-{suffix}", "tester", "tenant", "design_engineer")

    run(agent.ainvoke(principal, "project", f"session-{suffix}", "资料采用什么单位"))

    assert [role for role, _ in store.messages] == ["user", "assistant"]
    assert captured["memories"] == ["项目统一使用毫米"]
    assert captured["principal"] == principal


def test_knowledge_agent_uses_one_selected_function_tool_without_prefetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Provider:
        metadata = {"provider": "capture", "model": "test", "mode": "api"}

        def langchain_model(self):
            return object()

    class Store(MemoryStore):
        async def project_has_nonpublic_documents(self, _project_id: str) -> bool:
            return False

    class Queries:
        calls: list[str] = []

        async def search_documents(self, *_args, **_kwargs):
            self.calls.append("search_project_documents")
            return {
                "tool": "search_project_documents",
                "evidence": [{"evidence_id": "doc-1", "text": "PTFE"}],
                "sources": [{"source_id": "doc-1", "title": "design.pdf"}],
                "uncertainties": [],
            }

        async def query_material_specs(self, *_args, **_kwargs):
            raise AssertionError("unselected tool was called")

        async def query_price_records(self, *_args, **_kwargs):
            raise AssertionError("unselected tool was called")

        async def get_document_evidence(self, *_args, **_kwargs):
            raise AssertionError("unselected tool was called")

    class CompiledAgent:
        def __init__(self, tools):
            self.tools = tools

        async def ainvoke(self, *_args, **_kwargs):
            assert [item.name for item in self.tools] == [
                "search_project_documents",
                "query_material_specs",
                "query_price_records",
                "get_document_evidence",
            ]
            content = await self.tools[0].ainvoke({"query": "PTFE", "limit": 8})
            return {
                "messages": [
                    ToolMessage(content=content, tool_call_id="call-1", name="search_project_documents"),
                    AIMessage(content="资料采用PTFE [doc-1]"),
                ]
            }

    monkeypatch.setattr(
        "src.agents.knowledge_agent.create_agent",
        lambda **kwargs: CompiledAgent(kwargs["tools"]),
    )
    agent = KnowledgeAgent(store=Store(), provider=Provider())
    queries = Queries()
    agent.queries = queries
    result = run(agent._invoke_api(
        Principal("user", "tester", "tenant", "design_engineer"),
        "project",
        "session",
        "PTFE资料",
        [],
    ))

    assert queries.calls == ["search_project_documents"]
    assert result["sources"][0]["source_id"] == "doc-1"


def test_knowledge_agent_rejects_invalid_evidence_citation(monkeypatch: pytest.MonkeyPatch) -> None:
    class Provider:
        metadata = {"provider": "capture", "model": "test", "mode": "api"}

        def langchain_model(self):
            return object()

    class Store(MemoryStore):
        async def project_has_nonpublic_documents(self, _project_id: str) -> bool:
            return False

    class Queries:
        async def search_documents(self, *_args, **_kwargs):
            return {
                "tool": "search_project_documents",
                "evidence": [{"evidence_id": "allowed", "text": "PTFE"}],
                "sources": [],
                "uncertainties": [],
            }

    class CompiledAgent:
        def __init__(self, tools):
            self.tool = tools[0]

        async def ainvoke(self, *_args, **_kwargs):
            content = await self.tool.ainvoke({"query": "PTFE", "limit": 8})
            return {
                "messages": [
                    ToolMessage(content=content, tool_call_id="call-1", name=self.tool.name),
                    AIMessage(content="无效引用 [invented]"),
                ]
            }

    monkeypatch.setattr(
        "src.agents.knowledge_agent.create_agent",
        lambda **kwargs: CompiledAgent(kwargs["tools"]),
    )
    agent = KnowledgeAgent(store=Store(), provider=Provider())
    agent.queries = Queries()
    with pytest.raises(AgentProtocolError, match="invalid evidence citations"):
        run(agent._invoke_api(
            Principal("user", "tester", "tenant", "design_engineer"),
            "project",
            "session",
            "PTFE资料",
            [],
        ))


def test_dependency_health_reports_real_checks() -> None:
    response = request("GET", "/health/deps")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["checks"]["database"]["healthy"] is True
    assert payload["checks"]["model"]["healthy"] is True
    assert payload["checks"]["upload_storage"]["healthy"] is True
    assert payload["checks"]["redis"]["enabled"] is False


def test_vector_rerank_catalog_contains_17_models() -> None:
    settings = Settings(_env_file=None, MODEL_MODE="fake")
    service = ModelCapabilityService(provider=ModelProvider(settings), settings=settings)
    overview = service.overview()
    assert overview["catalog_count"] == 17
    assert {item["model_code"] for item in overview["vector_rerank_catalog"]} >= {
        "qwen3-rerank",
        "qwen3-vl-rerank",
        "text-embedding-v4",
    }


def test_qwen3_reranker_response_is_mapped_without_document_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RerankClient:
        def __init__(self, **_: Any):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_: Any):
            return None

        async def post(self, url: str, **kwargs: Any):
            assert url.endswith("/compatible-api/v1/reranks")
            assert kwargs["json"]["model"] == "qwen3-rerank"
            assert "instruct" in kwargs["json"]
            return httpx.Response(
                200,
                json={"results": [{"index": 1, "relevance_score": 0.91}]},
                request=httpx.Request("POST", url),
            )

    settings = api_settings(
        RERANKER_ENABLED=True,
        RERANKER_PROVIDER="dashscope",
        RERANKER_API_BASE="https://workspace.invalid/compatible-api/v1/reranks",
        RERANKER_API_KEY="reranker-test-key",
        RERANKER_MODEL="qwen3-rerank",
    )
    monkeypatch.setattr("src.infrastructure.model_provider.httpx.AsyncClient", RerankClient)
    ranked = run(ModelProvider(settings).rerank(
        "膜材规格",
        [{"text": "价格", "id": "price"}, {"text": "PTFE厚度", "id": "material"}],
        top_n=1,
    ))
    assert ranked[0]["id"] == "material"
    assert ranked[0]["rerank"]["provider"] == "dashscope"
