from __future__ import annotations

import asyncio

import httpx

from src.main import app


def request(method: str, path: str, **kwargs) -> httpx.Response:
    async def run() -> httpx.Response:
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.request(method, path, **kwargs)

    return asyncio.run(run())


def test_health_and_fake_chat() -> None:
    health = request("GET", "/health")
    assert health.status_code == 200
    response = request(
        "POST",
        "/api/v1/chat",
        json={"user_id": "test-user", "session_id": "test-session", "message": "ETFE 膜材规格适合采光顶吗"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["route"] == "material"
    assert payload["sources"]
    assert "provider" in payload["usage"]


def test_upload_index_and_package_review() -> None:
    response = request(
        "POST",
        "/api/v1/documents/upload",
        files={"file": ("engineering.txt", "PTFE 体育场屋盖厚度 0.8 mm".encode(), "text/plain")},
    )
    assert response.status_code == 200
    document_id = response.json()["document_id"]
    indexed = request("POST", f"/api/v1/documents/{document_id}/index")
    assert indexed.status_code == 200
    assert indexed.json()["chunks"] >= 1
    review = request(
        "POST",
        "/api/v1/package-reviews",
        json={"document_ids": [document_id], "question": "比较资料中的膜材规格"},
    )
    assert review.status_code == 200
    assert review.json()["status"] == "completed"


def test_unknown_document_is_rejected() -> None:
    response = request(
        "POST",
        "/api/v1/package-reviews",
        json={"document_ids": ["missing-document"]},
    )
    assert response.status_code == 400
