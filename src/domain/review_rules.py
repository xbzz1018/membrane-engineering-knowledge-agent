"""Deterministic engineering checks that sit beside the LLM review agents."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from typing import Any

from src.domain.schemas import ReviewIssue

WORKER_LABELS = {
    "design": "设计",
    "material": "膜材",
    "price": "价格",
}

WORKER_TERMS = {
    "design": ("设计", "方案", "结构", "场景", "节点", "跨度", "版本"),
    "material": ("膜材", "材料", "型号", "规格", "厚度", "重量", "透光", "抗拉", "PTFE", "PVC", "ETFE"),
    "price": ("价格", "成本", "报价", "币种", "单价", "元/", "CNY", "日期", "区域"),
}

VERSION_PATTERN = re.compile(r"(?:版本|version|rev(?:ision)?)\s*[:：]?\s*([A-Za-z0-9._-]+)", re.I)
THICKNESS_PATTERN = re.compile(r"(?:厚度|thickness)\s*[:：]?\s*(\d+(?:\.\d+)?)\s*(mm|毫米)?", re.I)
MATERIAL_PATTERN = re.compile(r"\b(?:PTFE|PVC(?:/PVDF)?|ETFE)(?:[-_ ]?[A-Za-z0-9]+)?\b", re.I)
PRICE_UNIT_PATTERN = re.compile(
    r"(?P<currency>CNY|RMB|USD|EUR|人民币|元|美元|欧元)\s*/\s*"
    r"(?P<area>m2|㎡|平方米|square\s*meters?)",
    re.I,
)
DATE_PATTERN = re.compile(r"\b(?:19|20)\d{2}[-/.](?:0?[1-9]|1[0-2])(?:[-/.](?:0?[1-9]|[12]\d|3[01]))?\b")


def _issue_id(domain: str, issue_type: str, values: Iterable[str]) -> str:
    raw = "|".join((domain, issue_type, *values))
    return f"rule-{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]}"


def _issue(
    *,
    domain: str,
    issue_type: str,
    summary: str,
    evidence_ids: Iterable[str] = (),
    actual_value: str = "",
    expected_value: str = "",
    recommendation: str = "",
    severity: str = "warning",
    requires_human: bool = False,
) -> ReviewIssue:
    ids = list(dict.fromkeys(str(item) for item in evidence_ids if item))
    return ReviewIssue(
        issue_id=_issue_id(domain, issue_type, [summary, actual_value, expected_value, *ids]),
        domain=domain,
        issue_type=issue_type,
        summary=summary,
        severity=severity,
        actual_value=actual_value,
        expected_value=expected_value,
        evidence_ids=ids,
        recommendation=recommendation,
        status="pending_human" if requires_human else "open",
        requires_human=requires_human,
    )


def _evidence_text(item: dict[str, Any]) -> str:
    return " ".join(
        str(item.get(key, ""))
        for key in ("filename", "location", "version", "text")
    )


def _normalize_price_unit(match: re.Match[str]) -> str:
    currency = match.group("currency").lower()
    normalized_currency = {
        "rmb": "CNY",
        "人民币": "CNY",
        "元": "CNY",
        "美元": "USD",
        "欧元": "EUR",
    }.get(currency, currency.upper())
    return f"{normalized_currency}/m2"


def _domain_evidence(worker: str, evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    terms = WORKER_TERMS[worker]
    return [
        item for item in evidence
        if any(term.lower() in _evidence_text(item).lower() for term in terms)
    ]


def _version_issues(evidence: list[dict[str, Any]]) -> list[ReviewIssue]:
    values: dict[str, list[str]] = {}
    for item in evidence:
        text = _evidence_text(item)
        matches = VERSION_PATTERN.findall(text)
        for version in matches:
            values.setdefault(version, []).append(str(item["evidence_id"]))
    if len(values) <= 1:
        return []
    evidence_ids = [evidence_id for ids in values.values() for evidence_id in ids]
    versions = sorted(values)
    return [_issue(
        domain="cross_domain",
        issue_type="version_mismatch",
        summary="资料包出现多个业务版本，不能直接合并结论",
        evidence_ids=evidence_ids,
        actual_value="、".join(versions),
        expected_value="同一审查批次使用同一业务版本",
        recommendation="确认主版本后重新提交审查，或分别形成版本报告。",
        severity="conflict",
        requires_human=True,
    )]


def _thickness_issues(evidence: list[dict[str, Any]], workers: set[str]) -> list[ReviewIssue]:
    if "material" not in workers:
        return []
    values: dict[str, list[str]] = {}
    for item in evidence:
        for value, unit in THICKNESS_PATTERN.findall(_evidence_text(item)):
            normalized = f"{value}{unit or 'mm'}".lower()
            values.setdefault(normalized, []).append(str(item["evidence_id"]))
    if len(values) <= 1:
        return []
    return [_issue(
        domain="material",
        issue_type="thickness_conflict",
        summary="不同资料中的膜材厚度不一致",
        evidence_ids=[evidence_id for ids in values.values() for evidence_id in ids],
        actual_value="、".join(sorted(values)),
        expected_value="同一材料型号使用一致厚度，并注明业务版本",
        recommendation="核对膜材规格书和设计版本，确认最终厚度。",
        severity="conflict",
        requires_human=True,
    )]


def _material_alignment_issue(evidence: list[dict[str, Any]], workers: set[str]) -> list[ReviewIssue]:
    if not {"design", "material"}.issubset(workers):
        return []
    design_rows = _domain_evidence("design", evidence)
    material_rows = _domain_evidence("material", evidence)
    design_materials = {
        match.upper()
        for row in design_rows
        for match in MATERIAL_PATTERN.findall(str(row.get("text", "")))
    }
    material_materials = {
        match.upper()
        for row in material_rows
        for match in MATERIAL_PATTERN.findall(str(row.get("text", "")))
    }
    missing = sorted(design_materials - material_materials)
    if not missing:
        return []
    ids = [str(row["evidence_id"]) for row in design_rows if any(
        material.lower() in str(row.get("text", "")).lower() for material in missing
    )]
    return [_issue(
        domain="cross_domain",
        issue_type="material_reference_missing",
        summary="设计资料中的膜材型号未在膜材规格资料中找到",
        evidence_ids=ids,
        actual_value="、".join(missing),
        expected_value="设计型号应有对应规格、日期和版本的资料",
        recommendation="补充对应规格书，或确认设计资料中的型号是否正确。",
        severity="conflict",
        requires_human=True,
    )]


def _price_issues(evidence: list[dict[str, Any]], workers: set[str]) -> list[ReviewIssue]:
    if "price" not in workers:
        return []
    rows = _domain_evidence("price", evidence)
    units: dict[str, list[str]] = {}
    dates: set[str] = set()
    for row in rows:
        text = _evidence_text(row)
        ids = [str(row["evidence_id"])]
        for match in PRICE_UNIT_PATTERN.finditer(text):
            units.setdefault(_normalize_price_unit(match), []).extend(ids)
        dates.update(DATE_PATTERN.findall(text))
    issues: list[ReviewIssue] = []
    if len(units) > 1:
        issues.append(_issue(
            domain="price",
            issue_type="price_unit_mismatch",
            summary="价格资料使用了不同计价单位，不能直接比较",
            evidence_ids=[evidence_id for ids in units.values() for evidence_id in ids],
            actual_value="、".join(sorted(units)),
            expected_value="统一为同一面积单位和币种",
            recommendation="先完成单位/币种换算，再进行历史价格比较。",
            severity="conflict",
            requires_human=True,
        ))
    if len(dates) > 1:
        issues.append(_issue(
            domain="price",
            issue_type="price_date_comparability",
            summary="价格资料包含多个日期，需要确认比较口径",
            evidence_ids=[str(row["evidence_id"]) for row in rows],
            actual_value="、".join(sorted(dates)),
            expected_value="明确基准日期或标记为历史参考",
            recommendation="按日期分组展示，不将历史数据直接作为当前报价。",
            severity="warning",
        ))
    return issues


def validate_evidence(evidence: list[dict[str, Any]], workers: Iterable[str]) -> list[ReviewIssue]:
    """Run deterministic completeness and consistency checks for a review plan."""
    selected = {worker for worker in workers if worker in WORKER_LABELS}
    issues: list[ReviewIssue] = []
    for worker in sorted(selected):
        rows = _domain_evidence(worker, evidence)
        if rows:
            continue
        issues.append(_issue(
            domain=worker,
            issue_type="missing_domain_evidence",
            summary=f"未发现明确的{WORKER_LABELS[worker]}资料证据",
            expected_value=f"至少一条可用于{WORKER_LABELS[worker]}审查的证据",
            recommendation=f"补充{WORKER_LABELS[worker]}资料后重新提交审查。",
            severity="warning",
        ))
    issues.extend(_version_issues(evidence))
    issues.extend(_thickness_issues(evidence, selected))
    issues.extend(_material_alignment_issue(evidence, selected))
    issues.extend(_price_issues(evidence, selected))
    return issues
