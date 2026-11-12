from __future__ import annotations

import asyncio
import hashlib
import os
from collections import Counter
from pathlib import Path

import httpx
import pytest
from fastapi import HTTPException
from langchain_core.messages import AIMessage

from scripts.build_document_fixtures import build as build_documents
from scripts.build_synthetic_cases import build as build_cases
from scripts.build_synthetic_prices import build as build_prices
from scripts.validate_data import read_jsonl, validate
from src.agents.knowledge_agent import AgentProtocolError, KnowledgeAgent
from src.agents.review_agents import PackageReviewService
from src.api.dependencies import require_project_role
from src.core.config import Settings
from src.core.security import Principal, create_access_token, decode_access_token, hash_password, verify_password
from src.infrastructure.database import prices, specs, storage
from src.main import app
from src.workflows import temporal_app
from src.workflows.temporal_definitions import _retry_policy


def request(method: str, path: str, **kwargs) -> httpx.Response:
    async def invoke() -> httpx.Response:
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.request(method, path, **kwargs)

    return asyncio.run(invoke())


def test_data_validator_enforces_release_counts() -> None:
    assert validate() == 0


def test_public_case_dataset_contract() -> None:
    rows = read_jsonl(Path("data/processed/public_cases.jsonl"))
    assert len(rows) >= 100
    assert all(row["synthetic"] is False for row in rows)
    assert all(len(row["source_sha256"]) == 64 for row in rows)


def test_synthetic_case_dataset_is_detailed() -> None:
    rows = read_jsonl(Path("data/processed/synthetic_cases.jsonl"))
    required = {"area_m2", "design_goal", "material_selection_reason", "license", "source_sha256"}
    assert len(rows) >= 100
    assert sum(required <= row.keys() for row in rows) >= 100


def test_business_case_count_excludes_hand_authored_fixtures() -> None:
    public = read_jsonl(Path("data/processed/public_cases.jsonl"))
    synthetic = read_jsonl(Path("data/processed/synthetic_cases.jsonl"))
    fixtures = read_jsonl(Path("data/fixtures/cases.jsonl"))
    assert len(public) + len(synthetic) == 200
    assert len(fixtures) == 5
    assert not ({row["case_id"] for row in public + synthetic} & {row["case_id"] for row in fixtures})


def test_catalog_records_have_enterprise_scope() -> None:
    specs = read_jsonl(Path("data/processed/material_specs.jsonl"))
    prices = read_jsonl(Path("data/processed/price_records.jsonl"))
    assert all(row["tenant_id"] == "membrane-company" and row["visibility"] == "public" for row in specs)
    assert all(row["tenant_id"] == "membrane-company" and row["visibility"] == "public" for row in prices)
    assert all("project_id" in row for row in prices)


def test_catalog_search_is_tenant_and_project_scoped() -> None:
    async def verify() -> None:
        async with app.router.lifespan_context(app):
            suffix = hashlib.sha256(os.urandom(16)).hexdigest()[:12]
            await storage.seed_payloads(specs, [{
                "spec_id": f"foreign-spec-{suffix}",
                "material": "FOREIGN-MATERIAL",
                "tenant_id": "other-tenant",
                "visibility": "public",
            }], "spec_id")
            await storage.seed_payloads(prices, [{
                "price_id": f"foreign-price-{suffix}",
                "material": "FOREIGN-PRICE",
                "tenant_id": "membrane-company",
                "project_id": "other-project",
                "visibility": "internal",
                "synthetic": True,
            }], "price_id")

            spec_rows = await storage.search_specs(
                "FOREIGN-MATERIAL",
                tenant_id="membrane-company",
                visibility={"public"},
            )
            price_rows = await storage.search_prices(
                "FOREIGN-PRICE",
                tenant_id="membrane-company",
                project_id="demo-project",
                visibility={"public"},
            )
            assert all(row.get("spec_id") != f"foreign-spec-{suffix}" for row in spec_rows)
            assert all(row.get("price_id") != f"foreign-price-{suffix}" for row in price_rows)

    asyncio.run(verify())


def test_public_material_specs_are_traceable() -> None:
    rows = read_jsonl(Path("data/processed/material_specs.jsonl"))
    public = [row for row in rows if row["synthetic"] is False]
    assert len(public) >= 40
    assert all(row["source_url"].startswith("https://") for row in public)
    assert all(len(row["source_sha256"]) == 64 for row in public)


def test_synthetic_prices_are_not_quotations() -> None:
    rows = read_jsonl(Path("data/processed/price_records.jsonl"))
    assert len(rows) >= 60
    assert all(row["synthetic"] is True for row in rows)
    assert all("not a market price" in row["disclaimer"] for row in rows)


def test_document_manifest_hashes_and_formats() -> None:
    rows = read_jsonl(Path("data/manifests/document_fixtures.jsonl"))
    counts = Counter(row["format"] for row in rows)
    assert counts == {"pdf": 10, "docx": 10, "xlsx": 10}
    for row in rows:
        path = Path("data/fixtures/documents") / row["filename"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == row["sha256"]


def test_document_fixture_builder_is_reproducible(tmp_path: Path) -> None:
    first = build_documents(tmp_path / "documents")
    second = build_documents(tmp_path / "documents")
    assert [row["sha256"] for row in first] == [row["sha256"] for row in second]


def test_synthetic_generators_are_deterministic() -> None:
    assert build_cases(5) == build_cases(5)
    assert build_prices() == build_prices()


def test_password_hash_and_jwt_round_trip() -> None:
    encoded = hash_password("test-password")
    assert verify_password("test-password", encoded)
    assert not verify_password("wrong-password", encoded)
    principal = Principal("user-1", "tester", "tenant-1", "reviewer")
    settings = Settings(_env_file=None, JWT_SECRET="test-secret-with-enough-entropy-32-bytes")
    assert decode_access_token(create_access_token(principal, settings), settings) == principal


def test_temporal_retry_policy_contract() -> None:
    policy = _retry_policy()
    assert policy.maximum_attempts == 3
    assert policy.backoff_coefficient == 2.0
    assert "ValueError" in policy.non_retryable_error_types


def test_disabled_temporal_submission_is_explicit(monkeypatch) -> None:
    settings = Settings(_env_file=None, TEMPORAL_ENABLED=False)
    monkeypatch.setattr(temporal_app, "get_settings", lambda: settings)
    document = asyncio.run(temporal_app.submit_document_ingest("doc-1"))
    package = asyncio.run(
        temporal_app.submit_package_review("review-1", ["doc-1"], "question", "user", "project", "tenant")
    )
    assert document["enabled"] is False and document["status"] == "local"
    assert package["enabled"] is False and package["status"] == "local"


def test_upload_rejects_unsupported_extension() -> None:
    response = request(
        "POST",
        "/api/v1/documents/upload",
        files={"file": ("unsafe.exe", b"not executable", "application/octet-stream")},
    )
    assert response.status_code == 415


def test_chat_rejects_empty_message() -> None:
    response = request(
        "POST",
        "/api/v1/chat",
        json={"user_id": "contract", "session_id": "empty", "message": ""},
    )
    assert response.status_code == 422


def test_batch_import_rejects_missing_documents() -> None:
    response = request("POST", "/api/v1/batch-imports", json={"document_ids": ["missing-document"]})
    assert response.status_code == 409


def test_unknown_workflow_business_object_is_not_disclosed() -> None:
    response = request("GET", "/api/v1/workflows/example-workflow")
    assert response.status_code == 404


def test_budget_reservation_is_idempotent_and_settled() -> None:
    async def verify() -> None:
        async with app.router.lifespan_context(app):
            workflow_id = "budget-test-" + hashlib.sha256(os.urandom(16)).hexdigest()
            first = await storage.reserve_budget("demo-project", workflow_id, 100)
            second = await storage.reserve_budget("demo-project", workflow_id, 100)
            assert first["id"] == second["id"]
            assert await storage.settle_budget(workflow_id, 42)
            assert not await storage.settle_budget(workflow_id, 42)

    asyncio.run(verify())


def test_local_budget_concurrency_respects_project_review_limit() -> None:
    async def verify() -> None:
        async with app.router.lifespan_context(app):
            async def reserve(index: int) -> str:
                workflow_id = f"concurrency-test-{index}-{hashlib.sha256(os.urandom(16)).hexdigest()}"
                try:
                    await storage.reserve_budget("demo-project", workflow_id, 100)
                    return f"reserved:{workflow_id}"
                except ValueError as exc:
                    assert "concurrent review quota" in str(exc)
                    return "rejected"

            outcomes = await asyncio.gather(*(reserve(index) for index in range(6)))
            reserved = [item for item in outcomes if item.startswith("reserved:")]
            assert len(reserved) == 3
            assert outcomes.count("rejected") == 3
            for item in reserved:
                await storage.settle_budget(item.split(":", 1)[1], 0, status="cancelled")

    asyncio.run(verify())


def test_review_approval_allows_only_the_first_concurrent_decision() -> None:
    async def verify() -> None:
        async with app.router.lifespan_context(app):
            review_id = "approval-test-" + hashlib.sha256(os.urandom(16)).hexdigest()
            await storage.save_package_review(
                {
                    "review_id": review_id,
                    "status": "awaiting_approval",
                    "engine": "deterministic-fake",
                    "report": "待审核",
                    "sources": [],
                    "conflicts": ["版本冲突"],
                    "worker_results": {},
                    "issues": [],
                    "usage": {},
                    "human_review_required": True,
                },
                user_id="approval-user",
                project_id="demo-project",
                question="并发审批测试",
            )
            from src.infrastructure.review_decisions import ReviewDecisionRepository

            repo = ReviewDecisionRepository(storage)
            outcomes = await asyncio.gather(
                repo.mutate(review_id, expected_lock_version=1, actor="reviewer-a", decision="approved"),
                repo.mutate(review_id, expected_lock_version=1, actor="reviewer-b", decision="rejected", reason="补证"),
                return_exceptions=True,
            )
            assert sum(isinstance(outcome, dict) for outcome in outcomes) == 1
            stored = await storage.get_package_review(review_id)
            assert stored and stored["status"] in {"approved", "rejected"}
            assert await storage.update_package_review_status(review_id, stored["status"])
            assert not await storage.update_package_review_status(
                review_id, "rejected" if stored["status"] == "approved" else "approved",
            )

    asyncio.run(verify())


def test_project_membership_prevents_cross_project_access() -> None:
    async def verify() -> None:
        async with app.router.lifespan_context(app):
            user = await storage.create_user(
                "member-" + hashlib.sha256(os.urandom(16)).hexdigest()[:16],
                hash_password("test-password"),
                "design_engineer",
            )
            allowed = await storage.create_project("授权项目", "membrane-company")
            denied = await storage.create_project("未授权项目", "membrane-company")
            await storage.add_project_member(allowed["id"], user["id"], "design_engineer")
            principal = Principal(user["id"], user["username"], "membrane-company", "design_engineer")
            assert await require_project_role(allowed["id"], principal) == "design_engineer"
            with pytest.raises(HTTPException) as captured:
                await require_project_role(denied["id"], principal)
            assert captured.value.status_code == 404

    asyncio.run(verify())


def test_long_evidence_batching_never_drops_units() -> None:
    evidence = [
        {"evidence_id": f"evidence-{index}", "token_count": 700, "text": f"text-{index}"}
        for index in range(25)
    ]
    batches = PackageReviewService._batches(evidence, token_budget=2000)
    flattened = [item["evidence_id"] for batch in batches for item in batch]
    assert flattened == [item["evidence_id"] for item in evidence]
    assert all(sum(item["token_count"] for item in batch) <= 2000 for batch in batches)


def test_truncated_agent_output_is_rejected() -> None:
    message = AIMessage(
        content="partial answer",
        response_metadata={"finish_reason": "length"},
    )
    with pytest.raises(AgentProtocolError, match="truncated"):
        KnowledgeAgent._answer([message])


def test_nonpublic_project_is_rejected_before_cloud_model_call() -> None:
    class RestrictedStore:
        async def project_has_nonpublic_documents(self, project_id: str) -> bool:
            return True

    class ApiProvider:
        metadata = {"provider": "test", "model": "test", "mode": "api"}

        def langchain_model(self):
            raise AssertionError("cloud model must not be constructed")

    agent = KnowledgeAgent(store=RestrictedStore(), provider=ApiProvider())
    principal = Principal("user", "tester", "tenant", "design_engineer")
    with pytest.raises(AgentProtocolError, match="非公开资料"):
        asyncio.run(agent._invoke_api(principal, "project", "session", "question", []))


def test_agent_run_is_linked_to_business_and_steps() -> None:
    async def verify() -> None:
        async with app.router.lifespan_context(app):
            admin = await storage.get_user_by_username("admin")
            run_id = await storage.start_agent_run(
                tenant_id="membrane-company",
                project_id="demo-project",
                user_id=admin["id"],
                business_id="review-test",
                run_type="package_review_design",
                provider="fake",
                model="deterministic",
            )
            assert run_id
            await storage.add_agent_step(run_id, "design_review", "invoke_agent", "completed", input_tokens=10)
            await storage.finish_agent_run(run_id, status="completed", input_tokens=10, output_tokens=2)
            rows = await storage.list_agent_runs(
                tenant_id="membrane-company",
                project_id="demo-project",
                business_id="review-test",
            )
            assert [item["id"] for item in rows] == [run_id]
            detail = await storage.get_agent_run(run_id, "membrane-company")
            assert detail["business_id"] == "review-test"
            assert detail["steps"][0]["step_name"] == "design_review"

    asyncio.run(verify())
