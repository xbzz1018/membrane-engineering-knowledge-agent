from __future__ import annotations

import asyncio
import uuid

import httpx

from src.core.config import Settings
from src.engineering.provider import ModelProvider
from src.engineering.storage import _fuse_ranked
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
    milvus = [
        {"id": "shared", "text": "vector", "retrieval": [{"backend": "milvus", "rank": 1, "score": 0.92}]},
        {"id": "vector-only", "text": "vector"},
    ]

    rows = _fuse_ranked(
        [("postgresql", 1.0, postgres), ("milvus", 1.3, milvus)],
        "id",
        10,
    )

    assert rows[0]["id"] == "shared"
    assert rows[0]["fusion_method"] == "weighted_rrf(k=60)"
    assert {item["backend"] for item in rows[0]["retrieval"]} == {"postgresql", "milvus"}
    assert rows[0]["fusion_score"] > rows[1]["fusion_score"]


def test_fake_embedding_matches_configured_milvus_dimension() -> None:
    provider = ModelProvider(Settings(
        _env_file=None,
        MODEL_MODE="fake",
        EMBEDDING_DIMENSIONS=48,
    ))
    first = asyncio.run(provider.embed("same text"))
    second = asyncio.run(provider.embed("same text"))
    assert len(first) == 48
    assert first == second


def test_long_term_memory_can_be_viewed_and_deleted() -> None:
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

    listed = request("GET", f"/api/v1/memories/{user_id}")
    assert listed.status_code == 200
    memories = listed.json()
    assert len(memories) == 1
    assert "synthetic PTFE canopy" in memories[0]["content"]

    deleted = request("DELETE", f"/api/v1/memories/{user_id}/{memories[0]['memory_id']}")
    assert deleted.status_code == 204
    assert request("GET", f"/api/v1/memories/{user_id}").json() == []


def test_deleting_unknown_memory_returns_404() -> None:
    response = request("DELETE", "/api/v1/memories/unknown-user/unknown-memory")
    assert response.status_code == 404
