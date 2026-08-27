from __future__ import annotations

import asyncio
import hashlib
from collections import Counter
from pathlib import Path

import httpx

from scripts.build_document_fixtures import build as build_documents
from scripts.build_synthetic_cases import build as build_cases
from scripts.build_synthetic_prices import build as build_prices
from scripts.validate_data import read_jsonl, validate
from src.core.config import Settings
from src.engineering.agents import EngineeringSupervisor
from src.events.kafka_events import EventEnvelope
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


def test_event_envelope_round_trip_and_unique_ids() -> None:
    first = EventEnvelope.create(
        event_type="document.ingest.requested",
        aggregate_type="document",
        aggregate_id="doc-1",
        payload={"document_id": "doc-1"},
    )
    second = EventEnvelope.create(
        event_type="document.ingest.requested",
        aggregate_type="document",
        aggregate_id="doc-1",
        payload={"document_id": "doc-1"},
    )
    assert EventEnvelope.model_validate_json(first.model_dump_json()) == first
    assert first.event_id != second.event_id
    assert first.schema_version == "1.0"


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
        temporal_app.submit_package_review("review-1", ["doc-1"], "question", "user", "project")
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
    assert response.status_code == 400


def test_replay_rejects_when_kafka_disabled() -> None:
    response = request("POST", "/api/v1/events/missing-event/replay")
    assert response.status_code == 409


def test_workflow_status_reports_disabled_temporal() -> None:
    response = request("GET", "/api/v1/workflows/example-workflow")
    assert response.status_code == 200
    assert response.json()["status"] == "disabled"


def test_precontraint_technical_parameters_route_to_material() -> None:
    assert EngineeringSupervisor.route("Precontraint 502 技术参数来源和版本是什么") == "material"


def test_comparison_with_material_and_cost_routes_to_multi() -> None:
    assert EngineeringSupervisor.route("对比入口雨棚案例、材料参数与成本资料") == "multi"
