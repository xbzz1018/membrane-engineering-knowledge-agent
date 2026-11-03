from __future__ import annotations

import asyncio
import io

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
    assert payload["route"] == "knowledge"
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
    assert review.json()["status"] == "awaiting_approval"
    assert review.json()["human_review_required"]
    assert any(item["issue_type"] == "missing_domain_evidence" for item in review.json()["issues"])
    assert "ReviewSupervisorAgent" in review.json()["agents_used"]
    assert set(review.json()["review_plan"]["workers"]) == {"retrieval", "material", "review"}
    persisted = request("GET", f"/api/v1/package-reviews/{review.json()['review_id']}")
    assert persisted.status_code == 200
    assert persisted.json()["report"] == review.json()["report"]
    assert persisted.json()["sources"]
    assert request("GET", "/api/v1/documents?project_id=demo-project").status_code == 200
    detail = request("GET", f"/api/v1/documents/{document_id}")
    assert detail.status_code == 200 and "stored_path" not in detail.json()
    evidence = request("GET", f"/api/v1/documents/{document_id}/evidence")
    assert evidence.status_code == 200 and evidence.json()
    reviews = request("GET", "/api/v1/package-reviews?project_id=demo-project")
    assert any(item["review_id"] == review.json()["review_id"] for item in reviews.json())
    workers = request("GET", f"/api/v1/package-reviews/{review.json()['review_id']}/workers")
    assert set(workers.json()["workers"]) == {"retrieval", "material", "review"}
    assert workers.json()["review_plan"]["workers"]
    review_evidence = request("GET", f"/api/v1/package-reviews/{review.json()['review_id']}/evidence")
    assert review_evidence.status_code == 200 and review_evidence.json()["evidence"]
    issues = request("GET", f"/api/v1/package-reviews/{review.json()['review_id']}/issues")
    assert issues.status_code == 200 and issues.json()["issues"]
    assert all("issue_id" in item and "domain" in item for item in issues.json()["issues"])
    assert all("evidence_refs" in item for item in issues.json()["issues"])
    issue = issues.json()["issues"][0]
    updated_issue = request(
        "PATCH",
        f"/api/v1/package-reviews/{review.json()['review_id']}/issues/{issue['issue_id']}",
        json={"status": "resolved", "expected_lock_version": review.json()["lock_version"]},
    )
    assert updated_issue.status_code == 200
    stale_issue = request(
        "PATCH",
        f"/api/v1/package-reviews/{review.json()['review_id']}/issues/{issue['issue_id']}",
        json={"status": "dismissed", "expected_lock_version": review.json()["lock_version"]},
    )
    assert stale_issue.status_code == 409
    trace = request("GET", f"/api/v1/package-reviews/{review.json()['review_id']}/trace")
    assert trace.status_code == 200


def test_unknown_document_is_rejected() -> None:
    response = request(
        "POST",
        "/api/v1/package-reviews",
        json={"document_ids": ["missing-document"]},
    )
    assert response.status_code == 400


def test_corrupt_and_empty_pdfs_are_not_marked_indexed() -> None:
    import pymupdf

    empty = pymupdf.open()
    empty.new_page()
    buffer = io.BytesIO()
    empty.save(buffer)
    empty.close()
    for filename, content in (
        ("broken.pdf", b"not a valid PDF"),
        ("empty.pdf", buffer.getvalue()),
    ):
        uploaded = request(
            "POST",
            "/api/v1/documents/upload",
            files={"file": (filename, content, "application/pdf")},
        )
        assert uploaded.status_code == 200
        document_id = uploaded.json()["document_id"]
        indexed = request("POST", f"/api/v1/documents/{document_id}/index")
        assert indexed.status_code == 422
        detail = request("GET", f"/api/v1/documents/{document_id}")
        assert detail.json()["status"] == "failed"


def test_unknown_package_review_returns_404() -> None:
    response = request("GET", "/api/v1/package-reviews/missing-review")
    assert response.status_code == 404


def test_model_capabilities_are_visible() -> None:
    response = request("GET", "/api/v1/model-capabilities")
    assert response.status_code == 200
    payload = response.json()
    assert payload["catalog_count"] == 17
    assert {item["model_code"] for item in payload["vector_rerank_catalog"]} >= {
        "qwen3-rerank",
        "text-embedding-v3",
    }


def test_enterprise_and_multi_agent_apis_are_visible() -> None:
    agents = request("GET", "/api/v1/agents")
    assert agents.status_code == 200
    assert len(agents.json()["review_agents"]) == 3
    assert request("GET", "/api/v1/auth/users").status_code == 200
    assert request("GET", "/api/v1/projects/demo-project/members").status_code == 200
    budget = request("GET", "/api/v1/projects/demo-project/budget")
    assert budget.status_code == 200 and budget.json()["daily_token_limit"] > 0


def test_openapi_is_chinese_and_contains_enterprise_routes() -> None:
    schema = app.openapi()
    assert schema["info"]["title"] == "膜结构企业资料审查平台"
    assert len(schema["paths"]) >= 30
    assert "/api/v1/agents" in schema["paths"]
    assert "/api/v1/package-reviews/{review_id}/workers" in schema["paths"]
    assert schema["paths"]["/api/v1/chat"]["post"]["summary"] == "基于项目证据进行知识问答"
