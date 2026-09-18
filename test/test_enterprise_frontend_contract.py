from __future__ import annotations

import asyncio

import httpx

from src.main import app


def request(method: str, path: str, **kwargs) -> httpx.Response:
    async def invoke() -> httpx.Response:
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.request(method, path, **kwargs)

    return asyncio.run(invoke())


def provenance() -> dict:
    return {
        "source_url": "https://example.com/membrane/source.pdf",
        "source_version": "2026-08",
        "license": "Public manufacturer technical data; verify terms at source.",
        "retrieved_at": "2026-08-30T00:00:00+00:00",
        "source_sha256": "a" * 64,
    }


def test_material_spec_crud_uses_lock_and_soft_archive() -> None:
    created = request("POST", "/api/v1/material-specs?project_id=demo-project", json={
        "manufacturer": "Test Manufacturer",
        "material": "PTFE",
        "product_reference": "TEST-502",
        "specification": "厚度0.8 mm，测试记录",
        "application": "雨棚",
        "visibility": "public",
        "synthetic": True,
        **provenance(),
    })
    assert created.status_code == 201
    item = created.json()
    assert item["status"] == "active" and item["lock_version"] == 1

    listed = request("GET", "/api/v1/material-specs?project_id=demo-project&query=TEST-502")
    assert listed.status_code == 200 and listed.json()["total"] == 1

    updated = request(
        "PATCH",
        f"/api/v1/material-specs/{item['spec_id']}?project_id=demo-project",
        json={"expected_lock_version": 1, "application": "交通雨棚"},
    )
    assert updated.status_code == 200
    assert updated.json()["application"] == "交通雨棚"
    assert updated.json()["lock_version"] == 2

    stale = request(
        "PATCH",
        f"/api/v1/material-specs/{item['spec_id']}?project_id=demo-project",
        json={"expected_lock_version": 1, "application": "过期修改"},
    )
    assert stale.status_code == 409

    archived = request(
        "POST",
        f"/api/v1/material-specs/{item['spec_id']}/archive?project_id=demo-project",
        json={"expected_lock_version": 2},
    )
    assert archived.status_code == 200 and archived.json()["status"] == "archived"
    active = request("GET", "/api/v1/material-specs?project_id=demo-project&query=TEST-502")
    assert active.json()["total"] == 0


def test_price_record_crud_and_public_real_price_rejection() -> None:
    invalid = request("POST", "/api/v1/price-records?project_id=demo-project", json={
        "material": "PTFE",
        "specification": "测试规格",
        "unit": "CNY/m2",
        "min_price": 200,
        "max_price": 300,
        "currency": "CNY",
        "region": "上海",
        "effective_date": "2026-08-30",
        "visibility": "public",
        "synthetic": False,
        **provenance(),
    })
    assert invalid.status_code == 422

    created = request("POST", "/api/v1/price-records?project_id=demo-project", json={
        "material": "ETFE",
        "specification": "synthetic测试规格",
        "unit": "CNY/m2",
        "min_price": 300,
        "max_price": 420,
        "currency": "CNY",
        "region": "苏州",
        "effective_date": "2026-08-30",
        "visibility": "public",
        "synthetic": True,
        **provenance(),
    })
    assert created.status_code == 201
    item = created.json()
    assert item["synthetic"] is True
    assert "不构成正式报价" in item["disclaimer"]

    updated = request(
        "PATCH",
        f"/api/v1/price-records/{item['price_id']}?project_id=demo-project",
        json={"expected_lock_version": 1, "max_price": 430},
    )
    assert updated.status_code == 200 and updated.json()["lock_version"] == 2

    archived = request(
        "POST",
        f"/api/v1/price-records/{item['price_id']}/archive?project_id=demo-project",
        json={"expected_lock_version": 2},
    )
    assert archived.status_code == 200 and archived.json()["status"] == "archived"


def test_dashboard_batch_list_and_budget_update_contract() -> None:
    dashboard = request("GET", "/api/v1/projects/demo-project/dashboard")
    assert dashboard.status_code == 200
    assert {"documents", "reviews", "issues", "budget", "dependencies"} <= dashboard.json().keys()

    batches = request("GET", "/api/v1/batch-imports?project_id=demo-project")
    assert batches.status_code == 200
    assert {"items", "total", "page", "page_size"} <= batches.json().keys()

    budget = request("GET", "/api/v1/projects/demo-project/budget").json()
    updated = request("PATCH", "/api/v1/projects/demo-project/budget", json={
        "daily_token_limit": max(1_000_000, budget["used_tokens"] + budget["reserved_tokens"]),
        "monthly_cost_limit_micros": max(
            100_000_000, budget["used_cost_micros"] + budget["reserved_cost_micros"],
        ),
        "max_concurrent_reviews": 4,
        "expected_lock_version": budget["lock_version"],
    })
    assert updated.status_code == 200
    assert updated.json()["max_concurrent_reviews"] == 4
    stale = request("PATCH", "/api/v1/projects/demo-project/budget", json={
        "daily_token_limit": 1_000_000,
        "monthly_cost_limit_micros": 100_000_000,
        "max_concurrent_reviews": 3,
        "expected_lock_version": budget["lock_version"],
    })
    assert stale.status_code == 409


def test_openapi_exposes_frontend_contract_routes() -> None:
    paths = app.openapi()["paths"]
    assert "/api/v1/projects/{project_id}/dashboard" in paths
    assert "/api/v1/material-specs" in paths
    assert "/api/v1/price-records" in paths
    assert "/api/v1/integrations/mcp" in paths
