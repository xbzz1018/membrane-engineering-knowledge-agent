from __future__ import annotations

import asyncio
import uuid

import httpx

from src.core.config import Settings
from src.infrastructure.database import _fuse_ranked
from src.infrastructure.full_backends import FullBackends
from src.infrastructure.model_provider import ModelProvider
from src.main import app


def request(method: str, path: str, **kwargs) -> httpx.Response:
    async def invoke() -> httpx.Response:
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.request(method, path, **kwargs)

    return asyncio.run(invoke())


def test_weighted_rrf_merges_backend_explanations() -> None:
    postgres = [
        {"id": "shared", "text": "lexical", "retrieval": [{"backend": "postgresql", "rank": 1, "score": 3}]},
        {"id": "sql-only", "text": "sql"},
    ]
    pgvector = [
        {"id": "shared", "text": "vector", "retrieval": [{"backend": "pgvector", "rank": 1, "score": 0.92}]},
        {"id": "vector-only", "text": "vector"},
    ]

    rows = _fuse_ranked(
        [("postgresql", 1.0, postgres), ("pgvector", 1.3, pgvector)],
        "id",
        10,
    )

    assert rows[0]["id"] == "shared"
    assert rows[0]["fusion_method"] == "weighted_rrf(k=60)"
    assert {item["backend"] for item in rows[0]["retrieval"]} == {"postgresql", "pgvector"}
    assert rows[0]["fusion_score"] > rows[1]["fusion_score"]


def test_fake_embedding_matches_configured_vector_dimension() -> None:
    provider = ModelProvider(Settings(
        _env_file=None,
        MODEL_MODE="fake",
        EMBEDDING_DIMENSIONS=48,
    ))
    first = asyncio.run(provider.embed("same text"))
    second = asyncio.run(provider.embed("same text"))
    assert len(first) == 48
    assert first == second


def test_pgvector_search_filters_tenant_project_classification_and_model() -> None:
    captured: dict = {}

    class Provider:
        embedding_model = "embedding-v1"

        async def embed(self, _text: str) -> list[float]:
            return [0.1, 0.2]

    class Result:
        def mappings(self):
            return self

        def all(self):
            return []

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def execute(self, statement, params):
            captured["statement"] = str(statement)
            captured["params"] = params
            return Result()

    backend = FullBackends(
        settings=Settings(_env_file=None, EMBEDDING_DIMENSIONS=2),
        provider=Provider(),
        session_factory=Session,
    )
    rows = asyncio.run(backend.search_documents(
        "PTFE",
        project_id="project-a",
        tenant_id="tenant-a",
        classifications={"public"},
    ))

    assert rows == []
    assert "embedding_model = :embedding_model" in captured["statement"]
    assert "project_id = :project_id" in captured["statement"]
    assert "tenant_id = :tenant_id" in captured["statement"]
    assert "classification IN (:classification_0)" in captured["statement"]
    assert captured["params"]["embedding_model"] == "embedding-v1"
    assert captured["params"]["project_id"] == "project-a"
    assert captured["params"]["tenant_id"] == "tenant-a"
    assert captured["params"]["classification_0"] == "public"


def test_long_term_memory_requires_confirmation_before_use() -> None:
    suffix = uuid.uuid4().hex
    user_id = f"memory-user-{suffix}"
    session_id = f"memory-session-{suffix}"
    chat = request(
        "POST",
        "/api/v1/chat",
        json={
            "user_id": user_id,
            "session_id": session_id,
            "message": "请记住我们的项目是 synthetic PTFE canopy",
        },
    )
    assert chat.status_code == 200

    listed = request("GET", "/api/v1/memories?status=pending")
    assert listed.status_code == 200
    memories = listed.json()
    matching = [item for item in memories if "synthetic PTFE canopy" in item["content"]]
    assert len(matching) == 1
    assert matching[0]["status"] == "pending"
    memory_id = matching[0]["memory_id"]

    confirmed = request("POST", f"/api/v1/memories/{memory_id}/confirm")
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "confirmed"

    updated = request("PATCH", f"/api/v1/memories/{memory_id}", json={
        "content": "请记住我们的项目是 synthetic ETFE canopy",
    })
    assert updated.status_code == 200
    assert updated.json()["status"] == "pending"
    assert "ETFE" in updated.json()["content"]
    assert request("POST", f"/api/v1/memories/{memory_id}/confirm").json()["status"] == "confirmed"

    deleted = request("DELETE", f"/api/v1/memories/{memory_id}")
    assert deleted.status_code == 204
    assert all(item["memory_id"] != memory_id for item in request("GET", "/api/v1/memories").json())


def test_deleting_unknown_memory_returns_404() -> None:
    response = request("DELETE", "/api/v1/memories/unknown-user/unknown-memory")
    assert response.status_code == 404
