from __future__ import annotations

import pytest

from scripts.run_business_eval import load_frozen
from src.agents.review_agents import PackageReviewService, ReviewAgentError, WorkerReview
from src.domain.review_rules import validate_evidence
from src.evaluation.metrics import binary_metrics, latency_summary, retrieval_metrics, unique_documents


def test_balanced_business_regression_rules():
    from pathlib import Path

    rows, _ = load_frozen(Path("data/eval/business_review_v1.jsonl"))
    assert sum(row["expected_human_review"] for row in rows) == 12
    for row in rows:
        evidence = [
            {"evidence_id": f"e{i}", "filename": doc["filename"], "text": doc["text"]}
            for i, doc in enumerate(row["documents"])
        ]
        issues = validate_evidence(evidence, ["design", "material", "price"])
        assert any(issue.requires_human for issue in issues) == row["expected_human_review"], row["eval_id"]
        assert set(row["expected_issue_types"]) <= {issue.issue_type for issue in issues}, row["eval_id"]
        target_citations = {
            eid for issue in issues if issue.issue_type in row["expected_issue_types"] for eid in issue.evidence_ids
        }
        assert {f"e{i}" for i in row["expected_evidence_documents"]} <= target_citations, row["eval_id"]


def test_unreported_evidence_stays_unprocessed():
    review = WorkerReview(worker="material", processed_evidence_ids=["e1"])
    PackageReviewService._validate_worker_review("material", review, {"e1": {}, "e2": {}})
    assert review.processed_evidence_ids == ["e1"]
    assert review.skipped_evidence_ids == ["e2"]
    assert review.skipped_reasons["e2"] == "模型未报告处理状态"


@pytest.mark.parametrize(
    "finding",
    [
        {"domain": "material", "summary": "没引用"},
        {"domain": "material", "summary": "虚构引用", "evidence_ids": ["other"]},
    ],
)
def test_invalid_worker_findings_rejected(finding):
    review = WorkerReview(worker="material", findings=[finding], processed_evidence_ids=["e1"])
    with pytest.raises(ReviewAgentError):
        PackageReviewService._validate_worker_review("material", review, {"e1": {}})


def test_worker_cannot_self_resolve_and_coverage_states_must_agree():
    review = WorkerReview(
        worker="material",
        findings=[
            {
                "domain": "material",
                "summary": "厚度差异",
                "evidence_ids": ["e1"],
                "severity": "conflict",
                "status": "resolved",
            }
        ],
        processed_evidence_ids=["e1"],
    )
    PackageReviewService._validate_worker_review("material", review, {"e1": {}})
    assert review.findings[0].status == "pending_human"
    review.skipped_evidence_ids = ["e1"]
    with pytest.raises(ReviewAgentError):
        PackageReviewService._validate_worker_review("material", review, {"e1": {}})


def test_retrieval_is_unique_document_macro_recall_and_truncated_rr():
    ids = unique_documents([{"document_id": "a"}, {"source_id": "a:2"}, {"document_id": "b"}])
    assert ids == ["a", "b"]
    metric = retrieval_metrics(ids, {"a", "c"}, 10)
    assert metric["recall_at_10"] == 0.5
    assert metric["rr_at_10"] == 1
    assert retrieval_metrics(["x", "a"], {"a"}, 1)["rr_at_1"] == 0
    with pytest.raises(ValueError):
        retrieval_metrics([], set())


def test_nearest_rank_p95_and_undefined_metrics():
    assert latency_summary([10, 20, 30])["p95"] == 30
    assert latency_summary([10, 20, 30])["small_sample"]
    metrics = binary_metrics([(True, True), (False, True), (True, False), (False, False)])
    assert metrics["f1"] == 0.5 and metrics["tp"] == metrics["fp"] == metrics["tn"] == metrics["fn"] == 1
    assert binary_metrics([(False, False)])["precision"] is None


def test_judge_cannot_choose_denominator_or_omit_claims():
    from pydantic import ValidationError

    from src.evaluation.groundedness import validate_judge

    valid = '{"verdicts":[{"claim_id":"c1","supported":true,"reason":"证据给出明确值"}]}'
    assert validate_judge(valid, ["c1"])["score"] == 1
    assert validate_judge('{"verdicts":[]}', [])["score"] is None
    for answer in (
        '{"total":0,"supported":0}',
        '{"verdicts":[]}',
        '{"verdicts":[{"claim_id":"c1","supported":"true","reason":"x"}]}',
    ):
        with pytest.raises((ValidationError, ValueError)):
            validate_judge(answer, ["c1"])


def test_one_domain_cannot_mask_another_domain_coverage_gap(monkeypatch):
    import asyncio

    service = PackageReviewService(provider=type("P", (), {"metadata": {"mode": "fake"}})())
    evidence = [{"evidence_id": "cross", "text": "设计方案指定膜材厚度", "filename": "design.txt"}]
    initial = [
        (WorkerReview(worker="retrieval", processed_evidence_ids=["cross"]), {}),
        (WorkerReview(worker="material", skipped_evidence_ids=["cross"]), {}),
    ]

    async def worker(name, *args):
        return WorkerReview(
            worker=name,
            processed_evidence_ids=["cross"] if name == "retrieval" else [],
            skipped_evidence_ids=["cross"] if name == "material" else [],
        ), {}

    monkeypatch.setattr(service, "run_worker", worker)
    outputs, coverage = asyncio.run(
        service.repair_evidence_coverage(["retrieval", "material"], "审查", evidence, [], initial)
    )
    assert coverage["initial_uncovered_by_worker"]["material"] == ["cross"]
    assert coverage["remaining_uncovered_by_worker"]["material"] == ["cross"]
    result = service.compose(outputs, [], evidence=evidence, coverage=coverage)
    assert any(item["issue_type"] == "evidence_coverage_gap" for item in result["issues"])
    assert result["human_review_required"]


def test_evidence_metadata_is_not_a_business_measurement():
    evidence = [
        {"evidence_id": "e", "filename": "design-厚度0.7mm-v2.txt", "version": 99, "text": "设计方案采用 PTFE-502。"},
        {"evidence_id": "s", "filename": "material.txt", "text": "膜材规格 PTFE-502，厚度 0.8 mm。"},
    ]
    issues = validate_evidence(evidence, ["design", "material"])
    assert not any(
        item.issue_type in {"version_mismatch", "thickness_conflict", "thickness_applicability_unclear"}
        for item in issues
    )


def test_worker_tool_assigns_finding_domain():
    review = WorkerReview(
        worker="material",
        findings=[{"domain": "design", "summary": "规格差异", "evidence_ids": ["e1"]}],
        processed_evidence_ids=["e1"],
    )
    PackageReviewService._validate_worker_review("material", review, {"e1": {}})
    assert review.findings[0].domain == "material"


def test_lexical_search_hides_failed_index_even_if_chunks_exist():
    import asyncio

    from sqlalchemy import update

    from src.infrastructure.database import documents, storage
    from src.main import app

    async def run():
        async with app.router.lifespan_context(app):
            doc = await storage.add_document("index-failed-gate.txt", "text/plain", b"status gate synthetic", "pending")
            await storage.save_chunks(
                doc["id"], [{"chunk_index": 0, "text": "STATUS_GATE_UNIQUE", "page_number": 1}], "test"
            )
            assert any(
                row["document_id"] == doc["id"]
                for row in await storage.search_chunks("STATUS_GATE_UNIQUE", project_id="demo-project")
            )
            async with storage.session_factory() as session:
                await session.execute(
                    update(documents).where(documents.c.id == doc["id"]).values(status="index_failed")
                )
                await session.commit()
            assert all(
                row["document_id"] != doc["id"]
                for row in await storage.search_chunks("STATUS_GATE_UNIQUE", project_id="demo-project")
            )

    asyncio.run(run())
