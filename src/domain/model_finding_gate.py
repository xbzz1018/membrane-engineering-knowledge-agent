"""Only supported deterministic comparisons may become definite model conflicts.

Unsupported comparisons remain human leads. Quotes establish traceability, not
semantic truth; no general semantic entailment score is manufactured here.
"""

import re

from src.domain.review_rules import validate_evidence
from src.domain.schemas import ReviewIssue

CHECK_TYPES = {
    "version": {"version_mismatch"},
    "thickness": {"thickness_conflict", "thickness_scope_unclear", "thickness_applicability_unclear"},
    "material_reference": {"material_reference_missing"},
    "price_basis": {"price_unit_mismatch", "price_scope_unclear", "price_date_comparability"},
}


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", value)


def convert_model_findings(model_review, evidence: list[dict]) -> tuple[list[ReviewIssue], list[str]]:
    by_id = {str(row["evidence_id"]): row for row in evidence}
    findings, limitations = [], []
    for proposal in model_review.findings:
        ids = set(proposal.evidence_ids)
        if not ids <= set(model_review.processed_evidence_ids):
            raise ValueError("模型发现引用未声明处理的证据")
        if not ids <= by_id.keys() or ids != {q.evidence_id for q in proposal.quotes}:
            raise ValueError("模型发现须对每条可见引用提供原文，不得附加无关证据")
        for quote in proposal.quotes:
            if not _compact(quote.quote) or _compact(quote.quote) not in _compact(by_id[quote.evidence_id]["text"]):
                raise ValueError("模型引文不在对应证据正文中")
        if proposal.check == "material_reference":
            # Missing references require the entire package. A routed worker or
            # quoted subset cannot establish absence; compose runs this check.
            limitations.append("材料引用完整性由全包规则校验，领域子集不作缺证结论。")
            continue
        if proposal.check in CHECK_TYPES:
            candidates = validate_evidence([by_id[i] for i in sorted(ids)], ["design", "material", "price"])
            supported = [item for item in candidates if item.issue_type in CHECK_TYPES[proposal.check]]
            if supported:
                findings.extend(supported)
            else:
                limitations.append(f"未采纳缺少可验证比较前提的{proposal.check}模型提议：{proposal.summary}")
            continue
        findings.append(ReviewIssue(
            domain=model_review.worker, issue_type="model_review_lead", summary=proposal.summary,
            severity="warning", actual_value=proposal.actual_value, expected_value=proposal.expected_value,
            evidence_ids=sorted(ids), recommendation=proposal.recommendation,
            requires_human=True, status="pending_human",
        ))
    return findings, limitations
