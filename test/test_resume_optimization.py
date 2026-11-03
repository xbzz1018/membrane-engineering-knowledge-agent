import asyncio
import uuid
from datetime import date

import httpx
import pytest
from pydantic import ValidationError

from src.agents.review_agents import PackageReviewService
from src.agents.review_model_output import ModelWorkerReview
from src.domain.document_search import DocumentSearchFilters
from src.domain.model_finding_gate import convert_model_findings
from src.infrastructure.document_filters import vector_filter_sql
from src.main import app


def proposal(check, evidence):
    return ModelWorkerReview(worker="material", processed_evidence_ids=[r["evidence_id"] for r in evidence], findings=[{
        "check": check, "summary": "需核对的差异", "severity": "conflict",
        "evidence_ids": [r["evidence_id"] for r in evidence],
        "quotes": [{"evidence_id": r["evidence_id"], "quote": r["text"]} for r in evidence],
    }])


@pytest.mark.parametrize("left,right", [
    ("膜材规格 PTFE-502 厚度0.8 mm 适用版本R1", "膜材规格 PTFE-502 厚度0.7 mm 适用版本R2"),
    ("膜材规格 PTFE-502 厚度0.8 mm 适用版本R1", "膜材规格 PTFE-503 厚度0.7 mm 适用版本R1"),
    ("膜材规格 PTFE-502 厚度0.8 mm 适用版本R1", "膜材规格 PTFE-502 厚度800 um 适用版本R1"),
    ("膜材规格 PTFE-502 名义厚度0.8 mm 适用版本R1", "膜材规格 PTFE-502 涂层厚度0.16 mm 适用版本R1"),
])
def test_model_cannot_override_comparison_premises(left, right):
    evidence = [{"evidence_id": "e1", "text": left}, {"evidence_id": "e2", "text": right}]
    issues, limitations = convert_model_findings(proposal("thickness", evidence), evidence)
    assert not issues and limitations


def test_model_supported_difference_and_unknown_applicability():
    evidence = [
        {"evidence_id": "e1", "text": "膜材规格 PTFE-502 厚度0.8 mm 适用版本R1"},
        {"evidence_id": "e2", "text": "膜材规格 PTFE-502 厚度0.7 mm 适用版本R1"},
    ]
    issues, _ = convert_model_findings(proposal("thickness", evidence), evidence)
    assert issues[0].issue_type == "thickness_conflict"
    for row in evidence:
        row["text"] = row["text"].replace(" 适用版本R1", "")
    issues, _ = convert_model_findings(proposal("thickness", evidence), evidence)
    assert issues[0].issue_type == "thickness_applicability_unclear"
    assert issues[0].severity != "conflict" and issues[0].requires_human


def test_worker_cannot_infer_package_missing_spec_from_quoted_design_subset():
    evidence = [{"evidence_id": "e1", "text": "设计要求 PTFE-502"}]
    issues, limitations = convert_model_findings(proposal("material_reference", evidence), evidence)
    assert not issues and limitations


def test_tax_scopes_and_fabricated_quotes_are_not_conflicts():
    evidence = [
        {"evidence_id": "e1", "text": "历史价格 PTFE-502 地区 上海 含税 300 CNY/m2"},
        {"evidence_id": "e2", "text": "历史价格 PTFE-502 地区 上海 未税 30 USD/m2"},
    ]
    issues, _ = convert_model_findings(proposal("price_basis", evidence), evidence)
    assert issues == []
    model = proposal("price_basis", evidence)
    model.findings[0].quotes[0].quote = "不存在的原文"
    with pytest.raises(ValueError, match="引文"):
        convert_model_findings(model, evidence)
    fields = ModelWorkerReview.model_json_schema()["$defs"]["ModelFinding"]["properties"]
    assert not {"evidence_refs", "issue_id", "version", "status", "domain"} & fields.keys()


def test_api_supervisor_plans_full_review_but_cannot_drop_required_roles():
    from langchain_core.messages import AIMessage

    from src.agents.subagent_tools import ScriptedSupervisorModel

    class Provider:
        metadata = {"mode": "api"}

        def langchain_model(self, **_kwargs):
            return ScriptedSupervisorModel(responses=[AIMessage(content='{"workers":["material"],"rationale":"核验型号"}')])

    plan, usage = asyncio.run(PackageReviewService(provider=Provider()).plan_review("全包", [], "full"))
    assert plan.workers == ["retrieval", "material", "review"]
    assert usage["calls"] == 1 and usage["mode"] == "llm"


def test_exact_filters_are_applied_in_http_and_do_not_fuzz_models():
    async def run():
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
                project = (await client.post("/api/v1/projects", json={"name": uuid.uuid4().hex})).json()["id"]
                ids = []
                for model, revision, start, end in [
                    ("PTFE-502", "R1", "2026-01-01", "2026-06-30"),
                    ("PTFE-5020", "R1", "2026-01-01", None),
                    ("PTFE-502", "R10", "2026-01-01", None),
                    ("PTFE-502", "R1", "2027-01-01", None),
                ]:
                    uploaded = await client.post("/api/v1/documents/upload", data={"project_id": project},
                        files={"file": (model + ".txt", f"spec {model} {revision} {start}".encode(), "text/plain")})
                    assert uploaded.status_code == 200
                    did = uploaded.json()["document_id"]
                    ids.append(did)
                    assert (await client.post(f"/api/v1/documents/{did}/index")).status_code == 200
                    doc = (await client.get(f"/api/v1/documents/{did}")).json()
                    response = await client.put(f"/api/v1/documents/{did}/business-metadata", json={
                        "engineering_model": model.lower(), "applicable_revision": revision, "document_type": "material",
                        "effective_from": start, "effective_to": end, "source_note": "合成规格书第1页，人工声明",
                        "expected_lock_version": doc["lock_version"],
                    })
                    assert response.status_code == 200, response.text
                    assert response.json()["provenance"] == "user_declared"
                query = {"project_id": project, "query": "spec", "filters": {
                    "engineering_model": "ptfe-502", "applicable_revision": "R1", "effective_on": "2026-05-01",
                }}
                response = await client.post("/api/v1/documents/search", json=query)
                assert response.status_code == 200, response.text
                assert {r["evidence_id"].split(":")[0] for r in response.json()["evidence"]} == {ids[0]}
                query["filters"]["effective_on"] = "2026-07-01"
                assert (await client.post("/api/v1/documents/search", json=query)).json()["evidence"] == []
                query["filters"]["effective_on"] = "2026-05-01"
                query["query"] = ""
                assert len((await client.post("/api/v1/documents/search", json=query)).json()["evidence"]) == 1
                query["project_id"] = "demo-project"
                assert (await client.post("/api/v1/documents/search", json=query)).json()["evidence"] == []
                query["project_id"] = "nonexistent-" + uuid.uuid4().hex
                assert (await client.post("/api/v1/documents/search", json=query)).status_code == 404
    asyncio.run(run())


def test_vector_predicate_uses_same_explicit_business_dates():
    clauses, params = vector_filter_sql(DocumentSearchFilters(
        engineering_model="ptfe-502", applicable_revision="r1", upload_version=2, effective_on=date(2026, 5, 1),
    ))
    sql = " ".join(clauses)
    assert "m.engineering_model = :filter_engineering_model" in sql
    assert "m.effective_from <= :filter_effective_on" in sql and "m.effective_to >=" in sql
    assert "d.version = :filter_upload_version" in sql and "created_at" not in sql
    assert params["filter_engineering_model"] == "PTFE-502"
    with pytest.raises(ValidationError):
        DocumentSearchFilters.model_validate({"project_id": "other-project"})


def test_issue_evaluation_counts_extra_findings_duplicates_and_missed_evidence():
    from src.evaluation.business_checks import match_issues

    gold = [{"issue_type": "thickness_conflict", "evidence_documents": [0, 1]}]
    issue = {"issue_id": "i1", "issue_type": "thickness_conflict", "requires_human": True,
             "evidence_ids": ["a:0", "b:0"]}
    assert match_issues([issue], gold, ["a", "b"])["strict_issue_pass"]
    duplicate = match_issues([issue, issue], gold, ["a", "b"])
    assert (duplicate["tp"], duplicate["fp"], duplicate["fn"]) == (1, 1, 0)
    wrong = match_issues([{**issue, "evidence_ids": ["a:0"]}], gold, ["a", "b"])
    assert (wrong["tp"], wrong["fp"], wrong["fn"]) == (0, 1, 1)
