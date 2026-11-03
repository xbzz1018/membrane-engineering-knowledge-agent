import asyncio

from src.agents.review_agents import PackageReviewService, ReviewAgentError, WorkerReview
from src.domain.review_rules import validate_evidence
from src.domain.schemas import PackageReviewRequest


def _item(evidence_id: str, filename: str, text: str, version: int = 1) -> dict:
    return {
        "evidence_id": evidence_id,
        "filename": filename,
        "location": "第1页",
        "version": version,
        "text": text,
    }


def test_rules_create_version_thickness_alignment_and_price_issues() -> None:
    evidence = [
        _item("design-1", "design-v1.pdf", "结构方案采用 PTFE-502，文件编号 D01，版本 v1"),
        _item("material-1", "material-v2.pdf", "膜材规格 PTFE-502，厚度 0.7 mm，适用版本 R1，文件编号 D01，版本 v2"),
        _item("material-2", "material-v2.pdf", "膜材规格 PTFE-502，厚度 0.8 mm，适用版本 R1，版本 v2"),
        _item("price-1", "price.xlsx", "历史价格 PTFE-502，300 CNY/m2，地区 上海，含税，日期 2025-01"),
        _item("price-2", "price.xlsx", "历史价格 PTFE-502，320 USD/m2，地区 上海，含税，日期 2026-01"),
    ]
    issues = validate_evidence(evidence, ("design", "material", "price"))
    types = {issue.issue_type for issue in issues}
    assert {"version_mismatch", "thickness_conflict", "price_unit_mismatch"} <= types
    assert all(
        issue.issue_id and issue.evidence_ids for issue in issues if issue.issue_type != "missing_domain_evidence"
    )
    assert all(issue.status == "pending_human" for issue in issues if issue.requires_human)


def test_rules_do_not_raise_for_coherent_evidence() -> None:
    evidence = [
        _item("design-1", "design-v1.pdf", "结构方案采用 PTFE-502，文件编号 D01，版本 v1"),
        _item("material-1", "material-v1.pdf", "膜材规格 PTFE-502，厚度 0.8 mm，版本 v1"),
        _item("price-1", "price.xlsx", "历史价格 300 元/平方米，日期 2025-01"),
    ]
    issues = validate_evidence(evidence, ("design", "material", "price"))
    assert not {issue.issue_type for issue in issues} & {
        "version_mismatch",
        "thickness_conflict",
        "price_unit_mismatch",
        "material_reference_missing",
    }


def test_issue_refs_are_hydrated_from_evidence() -> None:
    service = PackageReviewService(provider=type("Provider", (), {"metadata": {"mode": "fake"}})())
    review = WorkerReview(
        worker="material",
        findings=[
            {
                "summary": "规格需要人工确认",
                "issue_id": "issue-1",
                "domain": "material",
                "evidence_ids": ["e1"],
            }
        ],
        processed_evidence_ids=["e1"],
    )
    result = service.compose(
        [(review, {"calls": 0})],
        [],
        evidence=[_item("e1", "material.pdf", "PTFE 规格", version=2)],
    )
    ref = result["issues"][0]["evidence_refs"][0]
    assert ref == {
        "evidence_id": "e1",
        "filename": "material.pdf",
        "location": "第1页",
        "version": "2",
    }


def test_cloud_review_rejects_restricted_documents() -> None:
    class Store:
        async def list_documents(self, *_args, **_kwargs):
            return [
                {
                    "id": "restricted-1",
                    "filename": "internal.pdf",
                    "data_classification": "restricted",
                }
            ]

        async def list_document_chunks(self, *_args, **_kwargs):
            return []

    provider = type("Provider", (), {"metadata": {"mode": "api"}})()
    service = PackageReviewService(store=Store(), provider=provider)
    request = PackageReviewRequest(document_ids=["restricted-1"])
    try:
        asyncio.run(service.collect_evidence(request, "tenant"))
    except ReviewAgentError as exc:
        assert "非公开资料" in str(exc)
    else:
        raise AssertionError("restricted cloud review was not rejected")


def test_full_review_always_covers_three_domains_and_focused_can_narrow() -> None:
    service = PackageReviewService(provider=type("Provider", (), {"metadata": {"mode": "fake"}})())
    full, _ = asyncio.run(service.plan_review("只看价格", [], "full"))
    focused, _ = asyncio.run(service.plan_review("只审查价格和币种", [], "focused"))

    assert set(full.workers) == {"design", "material", "price"}
    assert full.review_mode == "full"
    assert focused.workers == ["price"]
    assert focused.review_mode == "focused"


def test_evidence_routing_is_multi_label_and_shares_unclassified_units() -> None:
    service = PackageReviewService(provider=type("Provider", (), {"metadata": {"mode": "fake"}})())
    evidence = [
        _item("cross-1", "combined.pdf", "设计方案指定 PTFE 膜材厚度 0.8 mm"),
        _item("shared-1", "notes.pdf", "会议纪要已归档，等待后续确认"),
        _item("price-1", "price.xlsx", "历史价格 300 CNY/m2"),
    ]

    routes = service.route_evidence(("design", "material", "price"), evidence)

    assert "cross-1" in {item["evidence_id"] for item in routes["design"]}
    assert "cross-1" in {item["evidence_id"] for item in routes["material"]}
    assert all("shared-1" in {item["evidence_id"] for item in rows} for rows in routes.values())
    assert "price-1" in {item["evidence_id"] for item in routes["price"]}


def test_uncovered_evidence_is_rerouted_once_to_selected_workers(monkeypatch) -> None:
    service = PackageReviewService(provider=type("Provider", (), {"metadata": {"mode": "fake"}})())
    evidence = [
        _item("design-1", "design.pdf", "结构设计方案"),
        _item("shared-1", "notes.pdf", "会议纪要已归档，等待后续确认"),
    ]
    initial_outputs = [
        (
            WorkerReview(
                worker=worker,
                processed_evidence_ids=["design-1"] if worker == "design" else [],
                skipped_evidence_ids=["shared-1"],
            ),
            {"calls": 1, "input_tokens": 10, "output_tokens": 2, "finish_reasons": ["stop"]},
        )
        for worker in ("design", "material", "price")
    ]

    async def repair_worker(worker, _question, repair_evidence, _memories):
        ids = [item["evidence_id"] for item in repair_evidence]
        return (
            WorkerReview(worker=worker, processed_evidence_ids=ids),
            {"calls": 1, "input_tokens": 3, "output_tokens": 1, "finish_reasons": ["stop"]},
        )

    monkeypatch.setattr(service, "run_worker", repair_worker)
    repaired, coverage = asyncio.run(
        service.repair_evidence_coverage(
            ("design", "material", "price"),
            "完整审查",
            evidence,
            [],
            initial_outputs,
        )
    )

    assert coverage["attempted"] is True
    assert coverage["passes"] == 1
    assert coverage["initial_uncovered_ids"] == ["shared-1"]
    assert coverage["remaining_uncovered_ids"] == []
    assert coverage["rerouted_workers"] == ["design", "material", "price"]
    assert all("shared-1" in review.processed_evidence_ids for review, _ in repaired)
