from __future__ import annotations

import asyncio
import uuid
from typing import Any

import httpx
import pytest

from src.core.config import Settings
from src.engineering.agents import EngineeringSupervisor
from src.engineering.provider import (
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

    monkeypatch.setattr("src.engineering.provider.httpx.AsyncClient", FailingClient)
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

    monkeypatch.setattr("src.engineering.provider.httpx.AsyncClient", EmptyThenSuccessClient)
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
        files={"file": (filename, b"PTFE roof evidence", "text/plain")},
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


class CaptureProvider:
    metadata = {"provider": "capture", "model": "test", "mode": "fake"}

    def __init__(self):
        self.prompts: list[str] = []

    async def chat(self, system: str, user: str, json_mode: bool = False):
        self.prompts.append(user)
        return "captured answer", self.metadata


class MemoryStore:
    def __init__(self):
        self.messages: list[tuple[str, str]] = []

    async def search_cases(self, query: str, limit: int = 6):
        return [{"case_id": "case-1", "title": "Test case", "source_url": "https://example.invalid"}]

    async def search_chunks(self, query: str, limit: int = 8):
        return []

    async def search_specs(self, query: str, limit: int = 8):
        return []

    async def search_prices(self, query: str, limit: int = 8):
        return []

    async def append_message(self, user_id: str, session_id: str, role: str, content: str):
        self.messages.append((role, content))

    async def save_memory(self, user_id: str, content: str, kind: str = "project_context"):
        return None

    async def search_memory(self, user_id: str, query: str, limit: int = 5):
        return []


def test_short_term_memory_saves_user_and_enters_next_prompt() -> None:
    store = MemoryStore()
    provider = CaptureProvider()
    supervisor = EngineeringSupervisor(store=store, provider=provider)
    suffix = uuid.uuid4().hex

    run(supervisor.ainvoke(f"user-{suffix}", f"session-{suffix}", "第一轮问题"))
    run(supervisor.ainvoke(f"user-{suffix}", f"session-{suffix}", "第二轮问题"))

    assert [role for role, _ in store.messages] == ["user", "assistant", "user", "assistant"]
    assert "第一轮问题" in provider.prompts[1]
    assert "captured answer" in provider.prompts[1]
    assert "第二轮问题" in provider.prompts[1]


def test_dependency_health_reports_real_checks() -> None:
    response = request("GET", "/health/deps")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["checks"]["database"]["healthy"] is True
    assert payload["checks"]["model"]["healthy"] is True
    assert payload["checks"]["upload_storage"]["healthy"] is True
    assert payload["checks"]["redis"]["enabled"] is False
