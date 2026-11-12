import asyncio
import hashlib
import json
import uuid

import httpx
import pytest
from langchain_core.messages import AIMessage
from pydantic import ValidationError

from src.agents.evidence_tools import frozen_evidence_tool
from src.agents.review_agents import PackageReviewService, ReviewAgentError
from src.agents.subagent_tools import DomainAgentTools, ScriptedSupervisorModel
from src.core.config import Settings
from src.documents.representations import contextual_text, document_index_model, document_markdown
from src.domain.review_roles import validate_review_evidence
from src.infrastructure.model_provider import ProviderConfigurationError, get_role_model_provider
from src.main import app


def test_strong_and_light_routes_are_explicit_and_incomplete_route_fails():
    settings = Settings(_env_file=None, MODEL_MODE="api", ROLE_MODEL_ROUTING_ENABLED=True,
        STRONG_MODEL_API_BASE="https://strong.invalid/v1", STRONG_MODEL_API_KEY="test-strong",
        STRONG_MODEL="strong-test", LIGHT_MODEL_API_BASE="https://light.invalid/v1",
        LIGHT_MODEL_API_KEY="test-light", LIGHT_MODEL="light-test")
    providers = {role: get_role_model_provider(role, settings) for role in ("supervisor", "review", "retrieval", "material")}
    assert providers["supervisor"].metadata == providers["review"].metadata
    assert providers["material"].model == providers["retrieval"].model == "light-test"
    assert providers["supervisor"].model == "strong-test"
    assert all("key" not in json.dumps(provider.metadata).lower() for provider in providers.values())
    with pytest.raises(ProviderConfigurationError, match="Incomplete LIGHT"):
        get_role_model_provider("material", settings.model_copy(update={"LIGHT_MODEL": ""}))
    fake = get_role_model_provider("material", settings.model_copy(update={"MODEL_MODE": "fake"}))
    assert fake.metadata["mode"] == "fake"


def test_reviewer_cannot_run_before_prerequisites():
    service = PackageReviewService(provider=type("Provider", (), {"metadata": {"mode": "fake"}})())
    boundary = DomainAgentTools(service, ["review"], "审查", [], [])
    with pytest.raises(ReviewAgentError, match="须等待"):
        asyncio.run(boundary.tools[0].ainvoke({}))


def test_lookup_keeps_units_and_cannot_accept_project_override():
    evidence = [{"evidence_id": "e1", "filename": "material.txt", "text": "膜材规格 PTFE-502 单位面积质量650 g/㎡"}]
    tool = frozen_evidence_tool(evidence, material_only=True)
    result = json.loads(asyncio.run(tool.ainvoke({"query": "PTFE-502"})))
    assert result["evidence"][0]["text"] == evidence[0]["text"]
    with pytest.raises(ValidationError):
        asyncio.run(tool.ainvoke({"query": "PTFE", "project_id": "foreign"}))
    assert json.loads(asyncio.run(tool.ainvoke({"query": "ETFE-999"})))["evidence"] == []


def test_real_langchain_retrieval_role_must_call_tool_and_preserve_selection():
    payload = {"worker": "retrieval", "processed_evidence_ids": ["e1"], "selected_evidence_ids": ["e1"]}

    class Provider:
        metadata = {"mode": "api", "model": "scripted-test", "provider": "test"}

        def langchain_model(self, **kwargs):
            return ScriptedSupervisorModel(responses=[
                AIMessage(content="", tool_calls=[{"name": "search_frozen_evidence",
                    "args": {"query": "PTFE-502"}, "id": "lookup-1"}]),
                AIMessage(content=json.dumps(payload)),
            ])

    evidence = [{"evidence_id": "e1", "text": "PTFE-502 厚度0.8 mm", "filename": "spec.txt", "token_count": 20}]
    review, usage = asyncio.run(PackageReviewService(provider=Provider()).run_worker("retrieval", "查资料", evidence, []))
    assert review.selected_evidence_ids == ["e1"] and usage["calls"] == 2
    assert usage["model_tier"] == "light" and usage["model"] == "scripted-test"


def test_context_prefix_never_changes_original_and_namespaces_vectors():
    row = {"id": "d:0", "text": "它的质量为650 g/㎡。", "heading_path": "PTFE-502 / 物理性能", "location": "第3页"}
    document = {"id": "d", "filename": "spec.md", "version": 2, "sha256": "a" * 64}
    original = dict(row)
    enhanced = contextual_text(document, row)
    assert "PTFE-502" in enhanced and enhanced.endswith(row["text"]) and row == original
    provider = type("Provider", (), {"embedding_model": "embed-test"})()
    off = Settings(_env_file=None, CONTEXTUAL_RETRIEVAL_ENABLED=False)
    on = off.model_copy(update={"CONTEXTUAL_RETRIEVAL_ENABLED": True})
    assert document_index_model(provider, off) == "embed-test"
    assert document_index_model(provider, on) == "embed-test:ctx-metadata-v1"
    exported = document_markdown(document, [row])
    assert row["text"] in exported and hashlib.sha256(row["text"].encode()).hexdigest() in exported
    assert "检索上下文（非原文）" not in exported


def test_contextual_heading_retrieval_has_same_raw_evidence(monkeypatch):
    from src.core.config import get_settings
    from src.infrastructure.database import storage

    async def run():
        async with app.router.lifespan_context(app):
            doc = await storage.add_document("context-" + uuid.uuid4().hex + ".md", "text/markdown",
                uuid.uuid4().hex.encode(), "basic", project_id="demo-project")
            await storage.acquire_document_ingest(doc["id"])
            await storage.save_chunks(doc["id"], [{"chunk_index": 0, "text": "它采用复合涂层。",
                "heading_path": "耐候耐久试验章节", "page_number": 1}], "basic")
            monkeypatch.setattr(get_settings(), "CONTEXTUAL_RETRIEVAL_ENABLED", False)
            off = await storage.search_chunks("耐候耐久试验章节", project_id="demo-project")
            monkeypatch.setattr(get_settings(), "CONTEXTUAL_RETRIEVAL_ENABLED", True)
            on = await storage.search_chunks("耐候耐久试验章节", project_id="demo-project")
            assert not any(row["document_id"] == doc["id"] for row in off)
            hit = next(row for row in on if row["document_id"] == doc["id"])
            assert hit["text"] == "它采用复合涂层。"
    asyncio.run(run())


@pytest.mark.parametrize("right,expected", [("650 g/㎡", None), ("700 g/㎡", "mass_per_area_conflict"),
                                         ("650", "mass_unit_missing")])
def test_mass_keeps_entity_revision_and_units(right, expected):
    rows = [{"evidence_id": "d:0", "filename": "design.txt",
             "text": "设计要求 PTFE-502 适用版本 R1 单位面积质量0.65 kg/㎡"},
            {"evidence_id": "s:0", "filename": "material.txt",
             "text": f"膜材规格 PTFE-502 适用版本 R1 单位面积质量{right}"}]
    types = {item.issue_type for item in validate_review_evidence(rows, ["retrieval", "material", "review"])}
    assert not types if expected is None else expected in types
    if expected == "mass_per_area_conflict":
        rows[1]["text"] = rows[1]["text"].replace("R1", "R2")
        assert "mass_per_area_conflict" not in {
            item.issue_type for item in validate_review_evidence(rows, ["material"])
        }


def test_markdown_http_exports_roundtrip_evidence_and_human_state():
    async def run():
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
                project = (await client.post("/api/v1/projects", json={"name": uuid.uuid4().hex})).json()["id"]
                ids = []
                for name, body in [("design.txt", "设计要求 PTFE-502 厚度0.8 mm 适用版本R1"),
                                   ("material.txt", "膜材规格 PTFE-502 厚度0.8 mm 适用版本R1")]:
                    uploaded = await client.post("/api/v1/documents/upload", data={"project_id": project},
                        files={"file": (name, body.encode(), "text/plain")})
                    did = uploaded.json()["document_id"]
                    assert (await client.get(f"/api/v1/documents/{did}/markdown")).status_code == 409
                    assert (await client.post(f"/api/v1/documents/{did}/index")).status_code == 200
                    response = await client.get(f"/api/v1/documents/{did}/markdown")
                    assert response.status_code == 200 and body in response.text
                    assert f"{did}:0" in response.text and response.headers["cache-control"] == "no-store"
                    ids.append(did)
                review = (await client.post("/api/v1/package-reviews", json={"project_id": project, "document_ids": ids})).json()
                assert review["status"] == "completed" and set(review["worker_results"]) == {"retrieval", "material", "review"}
                assert not any(item["domain"] == "price" for item in review["issues"])
                rid = review["review_id"]
                decided = await client.post(f"/api/v1/package-reviews/{rid}/decision", json={
                    "decision": "rejected", "expected_lock_version": review["lock_version"], "reason": "验收退回",
                })
                assert decided.status_code == 200
                response = await client.get(f"/api/v1/package-reviews/{rid}/markdown")
                assert response.status_code == 200 and "rejected" in response.text and ids[0] in response.text
    asyncio.run(run())
