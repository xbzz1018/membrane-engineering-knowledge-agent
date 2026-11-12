from __future__ import annotations

import asyncio
import hashlib
import io
import uuid
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio
from docx import Document
from sqlalchemy import select, update

from src.agents.knowledge_agent import AgentProtocolError
from src.agents.project_plan_agents import ProjectPlanWriter
from src.application.authorization import ProjectAccessError
from src.application.project_plans import ProjectPlanService
from src.core.config import get_settings
from src.core.security import Principal
from src.domain.project_plan import (
    CreatePlanRequest,
    PlanContent,
    PlanDecisionRequest,
    PlanExportRequest,
    PlanRequirements,
    RevisionRequest,
    digest,
    material_matches,
)
from src.infrastructure.database import documents, project_plan_artifacts, storage
from src.infrastructure.project_plan_repository import PlanConflict, PlanOwnershipLost
from src.main import app


@pytest_asyncio.fixture
async def setup_plan():
    await storage.init()
    admin = await storage.get_user_by_username(get_settings().BOOTSTRAP_ADMIN_USERNAME)
    principal = Principal(admin["id"], admin["username"], admin["tenant_id"], admin["role"])
    project = await storage.create_project("SYNTHETIC proposal " + uuid.uuid4().hex[:8], principal.tenant_id)
    document = await storage.add_document(
        "synthetic-plan-source.txt", "text/plain",
        b"synthetic-source-" + uuid.uuid4().bytes, "basic", tenant_id=principal.tenant_id, project_id=project["id"],
    )
    text = "SYNTHETIC 停车棚 历史项目案例。膜材型号 PVDF-PLAN-TEST，适用版次 R1，名义厚度 0.8 mm。仅用于合成测试。"
    await storage.save_chunks(document["id"], [{"chunk_index": 0, "text": text, "location": "合成资料第1段"}], "basic")
    service = ProjectPlanService(storage)
    request = CreatePlanRequest(request_id=uuid.uuid4().hex, requirements=PlanRequirements(
        project_name="合成停车棚初步方案", building_area_m2=800, location="合成测试场地",
        preferred_membrane="PVDF-PLAN-TEST", applicable_revision="R1",
    ))
    yield service, principal, project["id"], document["id"], request
    await storage.close()


def decision_for(record, **changes):
    return PlanDecisionRequest(**{
        "command_id": uuid.uuid4().hex, "expected_lock_version": record["lock_version"],
        "review_id": record["review"]["id"], "content_hash": record["content_hash"],
        "manifest_hash": record["manifest_hash"], "decision": "approved", "reason": "确认合成初步方案的需求及来源",
        **changes,
    })


@pytest.mark.asyncio
async def test_complete_plan_approval_export_and_idempotency(setup_plan):
    service, principal, project_id, _document_id, request = setup_plan
    record = await service.create(principal, project_id, request)
    assert record["status"] == "awaiting_approval"
    assert record["workflow"]["status"] == "local_inline"
    assert record["review"]["result"]["review_agent"]["worker"] == "review"
    assert record["content"]["requirements"]["building_area_m2"] == 800
    repeated = await service.create(principal, project_id, request)
    assert repeated["plan_id"] == record["plan_id"] and repeated["version"] == 1
    with pytest.raises(PlanConflict):
        await service.export(principal, record["plan_id"], 1, PlanExportRequest())
    command = decision_for(record)
    approved = await service.decide(principal, record["plan_id"], 1, command)
    assert approved["status"] == "approved"
    assert (await service.decide(principal, record["plan_id"], 1, command))["lock_version"] == approved["lock_version"]
    first = await service.export(principal, record["plan_id"], 1, PlanExportRequest())
    second = await service.export(principal, record["plan_id"], 1, PlanExportRequest())
    assert first == second
    rendered = {}
    for item in first["artifacts"]:
        data, actual = await service.download(principal, item["id"])
        assert actual["content_hash"] == approved["content_hash"]
        assert actual["manifest_hash"] == approved["manifest_hash"]
        assert hashlib.sha256(data).hexdigest() == item["sha256"]
        rendered[item["format"]] = data
    document = Document(io.BytesIO(rendered["docx"]))
    docx_text = "\n".join([paragraph.text for paragraph in document.paragraphs] + [
        cell.text for table in document.tables for row in table.rows for cell in row.cells
    ])
    markdown = rendered["md"].decode()
    for value in ("合成停车棚初步方案", "800 m²", "PVDF-PLAN-TEST", approved["content_hash"], approved["manifest_hash"]):
        assert value in docx_text and value in markdown
    async with storage.session_factory() as session:
        rows = (await session.execute(select(project_plan_artifacts).where(
            project_plan_artifacts.c.plan_id == record["plan_id"],
        ))).mappings().all()
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_revision_invalidates_old_approval_and_download(setup_plan):
    service, principal, project_id, _, request = setup_plan
    first = await service.create(principal, project_id, request)
    approved = await service.decide(principal, first["plan_id"], 1, decision_for(first))
    output = await service.export(principal, first["plan_id"], 1, PlanExportRequest(formats=["docx"]))
    approved = await service.repo.get(first["plan_id"])
    content = PlanContent.model_validate(approved["content"])
    content.requirements.building_area_m2 = 900
    revision = RevisionRequest(request_id=uuid.uuid4().hex, base_version=1,
                               expected_lock_version=approved["lock_version"], content=content, reason="修改声明面积")
    second = await service.revise(principal, first["plan_id"], revision)
    assert second["version"] == 2 and second["status"] == "awaiting_approval"
    assert second["decision"] is None and second["content_hash"] != approved["content_hash"]
    with pytest.raises(PlanConflict):
        await service.export(principal, first["plan_id"], 2, PlanExportRequest())
    with pytest.raises(PlanConflict):
        await service.download(principal, output["artifacts"][0]["id"])
    with pytest.raises(PlanConflict):
        await service.decide(principal, first["plan_id"], 2, decision_for(second, review_id=first["review"]["id"]))
    history = await service.repo.get(first["plan_id"], 1)
    assert history["status"] == "approved" and history["content"]["requirements"]["building_area_m2"] == 800


@pytest.mark.asyncio
async def test_missing_requirements_or_sources_block_approval(setup_plan):
    service, principal, project_id, _, request = setup_plan
    request.requirements.location = ""
    record = await service.create(principal, project_id, request)
    assert record["status"] == "needs_revision"
    assert any(issue["target_path"] == "requirements.location" for issue in record["review"]["result"]["issues"])
    with pytest.raises(PlanConflict):
        await service.decide(principal, record["plan_id"], 1, decision_for(record))
    rejected = await service.decide(principal, record["plan_id"], 1, decision_for(record, decision="rejected", reason="补充场地"))
    assert rejected["status"] == "rejected"


@pytest.mark.asyncio
async def test_no_sources_remains_a_draft_and_query_failures_are_errors(setup_plan, monkeypatch):
    service, principal, _, _, request = setup_plan
    project = await storage.create_project("SYNTHETIC empty", principal.tenant_id)
    record = await service.create(principal, project["id"], request)
    assert record["status"] == "needs_revision"
    assert record["review"]["result"]["review_agent"] is None
    assert record["source_manifest"]["query_outcomes"]["retrieval"] == "no_results"
    service._agents()
    monkeypatch.setattr(service.supervisor, "_query_role", AsyncMock(side_effect=TimeoutError("test")))
    request.request_id = uuid.uuid4().hex
    with pytest.raises(TimeoutError):
        await service.create(principal, project["id"], request)
    latest = (await service.repo.list(principal.tenant_id, project["id"]))[0]
    failed = await service.repo.get(latest["id"])
    assert failed["status"] == "failed" and failed["content"] is None


@pytest.mark.asyncio
async def test_cross_project_scope_and_reviewer_permissions(setup_plan):
    service, principal, project_id, _, request = setup_plan
    record = await service.create(principal, project_id, request)
    designer = await storage.create_user("plan-designer-" + uuid.uuid4().hex, "test", "design_engineer")
    actor = Principal(designer["id"], designer["username"], designer["tenant_id"], designer["role"])
    with pytest.raises(ProjectAccessError):
        await service.authorize_plan(actor, record["plan_id"])
    await storage.add_project_member(project_id, actor.user_id, "design_engineer")
    with pytest.raises(ProjectAccessError):
        await service.decide(actor, record["plan_id"], 1, decision_for(record))
    other = Principal(principal.user_id, principal.username, "other-tenant", "admin")
    with pytest.raises(LookupError):
        await service.authorize_plan(other, record["plan_id"])


@pytest.mark.asyncio
async def test_source_reclassification_blocks_export_and_download(setup_plan):
    service, principal, project_id, document_id, request = setup_plan
    record = await service.create(principal, project_id, request)
    await service.decide(principal, record["plan_id"], 1, decision_for(record))
    exported = await service.export(principal, record["plan_id"], 1, PlanExportRequest())
    async with storage.session_factory() as session:
        await session.execute(update(documents).where(documents.c.id == document_id).values(data_classification="restricted"))
        await session.commit()
    with pytest.raises(PlanConflict):
        await service.download(principal, exported["artifacts"][0]["id"])
    with pytest.raises(PlanConflict):
        await service.export(principal, record["plan_id"], 1, PlanExportRequest())


@pytest.mark.asyncio
async def test_parallel_revision_cas_and_request_identity(setup_plan):
    service, principal, project_id, _, request = setup_plan
    record = await service.create(principal, project_id, request)
    content = PlanContent.model_validate(record["content"])
    content.requirements.location = "另一合成场地"
    requests = [RevisionRequest(request_id=uuid.uuid4().hex, base_version=1, expected_lock_version=record["lock_version"],
                                content=content, reason="并发修订") for _ in range(2)]
    results = await asyncio.gather(*(service.repo.revise(record["plan_id"], principal, item) for item in requests), return_exceptions=True)
    assert sum(result == 2 for result in results) == 1
    assert sum(isinstance(result, PlanConflict) for result in results) == 1
    request.requirements.location = "请求ID相同但需求变化"
    with pytest.raises(PlanConflict):
        await service.create(principal, project_id, request)


@pytest.mark.asyncio
async def test_stale_attempt_and_cancel_cannot_publish(setup_plan):
    service, principal, project_id, _, request = setup_plan
    plan_id = await service.repo.create(principal, project_id, request)
    await service.repo.acquire(plan_id, 1, "generating", ("activity", 1))
    await service.repo.acquire(plan_id, 1, "generating", ("activity", 2))
    with pytest.raises(PlanOwnershipLost):
        await service.repo.freeze(plan_id, 1, {"evidence": []}, ("activity", 1))
    record = await service.repo.get(plan_id)
    await service.cancel(principal, plan_id, 1, record["lock_version"])
    with pytest.raises(PlanOwnershipLost):
        await service.repo.freeze(plan_id, 1, {"evidence": []}, ("activity", 2))


@pytest.mark.asyncio
async def test_export_failure_retry_and_revision_during_render(setup_plan, monkeypatch):
    from src.documents.project_export import ProjectDocumentService

    service, principal, project_id, _, request = setup_plan
    record = await service.create(principal, project_id, request)
    await service.decide(principal, record["plan_id"], 1, decision_for(record))
    item = await service.repo.reserve_artifact(record["plan_id"], 1, "docx")
    original = ProjectDocumentService.store

    async def fail_after_store(self, artifact, data):
        await original(self, artifact, data)
        raise RuntimeError("synthetic crash after object storage")

    monkeypatch.setattr(ProjectDocumentService, "store", fail_after_store)
    with pytest.raises(RuntimeError):
        await service.render(item["id"], ("export", 1))
    assert (await service.repo.get_artifact(item["id"]))["status"] == "failed"
    monkeypatch.setattr(ProjectDocumentService, "store", original)
    await service.render(item["id"], ("export", 2))
    assert (await service.repo.get_artifact(item["id"]))["status"] == "published"

    markdown = await service.repo.reserve_artifact(record["plan_id"], 1, "md")

    async def revise_during_store(self, artifact, data):
        result = await original(self, artifact, data)
        current = await service.repo.get(record["plan_id"])
        await service.repo.revise(record["plan_id"], principal, RevisionRequest(
            request_id=uuid.uuid4().hex, base_version=1, expected_lock_version=current["lock_version"],
            content=PlanContent.model_validate(current["content"]), reason="模拟渲染过程中改版",
        ))
        return result

    monkeypatch.setattr(ProjectDocumentService, "store", revise_during_store)
    with pytest.raises(PlanConflict):
        await service.render(markdown["id"], ("markdown", 1))
    assert (await service.repo.get_artifact(markdown["id"]))["status"] == "failed"


@pytest.mark.asyncio
async def test_json_writer_protocol_failure_never_falls_back(setup_plan, monkeypatch):
    from types import SimpleNamespace

    from langchain_core.messages import AIMessage

    service, principal, project_id, _, request = setup_plan
    service._agents()
    model = SimpleNamespace(ainvoke=AsyncMock(return_value={"messages": [AIMessage(content="not json")]}))
    monkeypatch.setattr("src.agents.project_plan_agents.create_agent", lambda **kwargs: model)
    provider = SimpleNamespace(metadata={"mode": "api", "provider": "test", "model": "stub"},
                               langchain_model=lambda **kwargs: object())
    service.writer = ProjectPlanWriter(provider)
    with pytest.raises(AgentProtocolError):
        await service.create(principal, project_id, request)
    assert model.ainvoke.await_count == 2
    latest = (await service.repo.list(principal.tenant_id, project_id))[0]
    record = await service.repo.get(latest["id"])
    assert record["status"] == "failed" and record["content"] is None


@pytest.mark.asyncio
async def test_http_create_approve_download_and_chat(setup_plan):
    service, principal, project_id, _, request = setup_plan
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(f"/api/v1/projects/{project_id}/plans", json=request.model_dump(mode="json"))
        assert response.status_code == 202, response.text
        record = response.json()
        response = await client.post(f"/api/v1/plans/{record['plan_id']}/versions/1/decision",
                                     json=decision_for(record).model_dump())
        assert response.status_code == 200, response.text
        response = await client.post(f"/api/v1/plans/{record['plan_id']}/versions/1/exports", json={"formats": ["docx"]})
        assert response.status_code == 202, response.text
        item = response.json()["artifacts"][0]
        downloaded = await client.get(item["download_url"])
        assert downloaded.status_code == 200 and downloaded.content[:2] == b"PK"
        assert downloaded.headers["cache-control"] == "no-store"
        assert downloaded.headers["x-plan-version"] == "1"
        response = await client.post("/api/v1/chat", json={
            "project_id": project_id, "session_id": uuid.uuid4().hex, "request_id": uuid.uuid4().hex,
            "message": "生成800平方米PVDF停车棚初步方案，地点：合成场地",
        })
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["routing"]["action_status"] == "accepted"
        assert result["project_plan"]["plan_id"] and result["project_plan"]["version"] == 1


@pytest.mark.asyncio
async def test_deferred_decision_is_not_approval_until_consumed(setup_plan, monkeypatch):
    service, principal, project_id, _, request = setup_plan
    record = await service.create(principal, project_id, request)
    monkeypatch.setattr(get_settings(), "TEMPORAL_ENABLED", True)
    pending = await service.decide(principal, record["plan_id"], 1, decision_for(record))
    assert pending["status"] == "decision_pending"
    with pytest.raises(PlanConflict):
        await service.repo.reserve_artifact(record["plan_id"], 1, "docx")
    receipt = await service.repo.consume_decision(record["plan_id"], 1)
    assert receipt["status"] == "approved"
    assert receipt == await service.repo.consume_decision(record["plan_id"], 1)


def test_plan_hash_stable_and_exact_material_identity():
    assert digest({"a": 1, "b": 2}) == digest({"b": 2, "a": 1})
    assert material_matches("PVDF-502", "膜材PVDF-502规格")
    assert not material_matches("PVDF-502", "膜材PVDF-5020规格")
    assert material_matches("PVDF", "膜材PVDF-5020规格")


@pytest.mark.asyncio
async def test_partial_catalog_match_does_not_hide_specific_uploaded_material(setup_plan):
    from src.infrastructure.bootstrap import seed_local_data

    service, principal, project_id, _, request = setup_plan
    await seed_local_data(storage)
    record = await service.create(principal, project_id, request)
    assert record["status"] == "awaiting_approval"
    material_quotes = [quote for quote in record["content"]["source_quotes"] if quote["purpose"] == "material"]
    assert material_quotes and all("PVDF-PLAN-TEST" in quote["quote"] for quote in material_quotes)


@pytest.mark.parametrize("mutation", ["invented_quote", "numeric_claim", "wrong_preference"])
@pytest.mark.asyncio
async def test_revised_unsupported_claims_cannot_be_approved(setup_plan, mutation):
    service, principal, project_id, _, request = setup_plan
    record = await service.create(principal, project_id, request)
    content = PlanContent.model_validate(record["content"])
    if mutation == "invented_quote":
        content.source_quotes[0].quote = "原文并没有出现的保证性材料结论"
    elif mutation == "numeric_claim":
        content.sections[1].content = "拟采用厚度9.9 mm，保证结构安全。"
    else:
        content.requirements.preferred_membrane = "PTFE-NO-SOURCE"
    revised = await service.revise(principal, record["plan_id"], RevisionRequest(
        request_id=uuid.uuid4().hex, base_version=1, expected_lock_version=record["lock_version"],
        content=content, reason="合成测试验证未支持断言被阻断",
    ))
    assert revised["status"] == "needs_revision"
    with pytest.raises(PlanConflict):
        await service.decide(principal, record["plan_id"], 2, decision_for(revised))


@pytest.mark.asyncio
async def test_generation_waits_for_both_query_tools_and_export_does_not_write_prose(setup_plan, monkeypatch):
    service, principal, project_id, _, request = setup_plan
    service._agents()
    original_query = service.supervisor._query_role
    original_write = service.writer.generate
    arrived = set()
    completed = set()
    barrier = asyncio.Event()

    async def query(role, *args, **kwargs):
        arrived.add(role)
        if len(arrived) == 2:
            barrier.set()
        await asyncio.wait_for(barrier.wait(), 3)
        result = await original_query(role, *args, **kwargs)
        completed.add(role)
        return result

    async def write(*args, **kwargs):
        assert completed == {"retrieval", "material"}
        return await original_write(*args, **kwargs)

    monkeypatch.setattr(service.supervisor, "_query_role", query)
    monkeypatch.setattr(service.writer, "generate", write)
    record = await service.create(principal, project_id, request)
    await service.decide(principal, record["plan_id"], 1, decision_for(record))
    monkeypatch.setattr(service.writer, "generate", AsyncMock(side_effect=AssertionError("approved export cannot generate prose")))
    exported = await service.export(principal, record["plan_id"], 1, PlanExportRequest())
    assert all(item["status"] == "published" for item in exported["artifacts"])
