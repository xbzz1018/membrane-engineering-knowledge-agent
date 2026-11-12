"""Scoped document consistency checks; findings are review leads, never approval."""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from collections.abc import Iterable
from decimal import Decimal
from typing import Any

from src.domain.schemas import ReviewIssue

WORKER_LABELS = {"design": "设计", "material": "膜材", "price": "价格"}
VERSION_PATTERN = re.compile(r"(?<!适用)(?<!基准)(?:版本|version|rev(?:ision)?)\s*[:：]?\s*([A-Za-z0-9._-]+)", re.I)
THICKNESS_PATTERN = re.compile(
    r"(?:厚度|thickness)\s*[:：]?\s*(\d+(?:\.\d+)?)\s*(mm|毫米|μm|µm|um|微米|cm|厘米|m|米)?",
    re.I,
)
MATERIAL_PATTERN = re.compile(r"(?<![A-Za-z0-9])(?:PTFE|PVC(?:/PVDF)?|ETFE)(?:[-_]?[A-Za-z0-9]+)?(?![A-Za-z0-9])", re.I)
PRICE_UNIT_PATTERN = re.compile(
    r"(?P<currency>CNY|RMB|USD|EUR|人民币|元|美元|欧元)\s*/\s*"
    r"(?P<area>m2|m²|㎡|平方米|square\s*meters?)",
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
    ids = sorted(set(str(item) for item in evidence_ids if item))
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


def _text(item: dict[str, Any]) -> str:
    # Filename/storage revision are provenance; never treat them as measured facts.
    return str(item.get("text", ""))


def _slot(text: str, label: str) -> str:
    match = re.search(rf"(?:{label})\s*[:：]?\s*([A-Za-z0-9_./-]+|[\u4e00-\u9fff]+)", text, re.I)
    return match.group(1).strip().upper() if match else ""


def _models(item: dict[str, Any]) -> set[str]:
    return {value.upper().replace("_", "-") for value in MATERIAL_PATTERN.findall(_text(item))}


def _current(item: dict[str, Any]) -> bool:
    return not re.search(r"历史参考|已作废|已替代|superseded|archived", _text(item), re.I)


def evidence_role(item: dict[str, Any]) -> str:
    """Prefer a declared role, then document title, then unambiguous body cues."""
    role = str(item.get("document_type", ""))
    if role in WORKER_LABELS:
        return role
    title = str(item.get("filename", "")).lower()
    for key, terms in (
        ("design", ("design", "设计", "图纸")),
        ("material", ("material", "spec", "规格", "材质证明")),
        ("price", ("price", "报价", "价格")),
    ):
        if any(term in title for term in terms):
            return key
    text = _text(item).lower()
    for key, terms in (
        ("design", ("设计方案", "结构方案", "设计要求", "设计资料", "design requirement")),
        ("price", ("报价", "历史价格", "价格资料", "计价", "price record")),
        ("material", ("膜材规格", "材料规格", "规格书", "材质证明", "datasheet")),
    ):
        if any(term in text for term in terms):
            return key
    return "unknown"


def _normalize_price_unit(match: re.Match[str]) -> str:
    currency = match.group("currency").lower()
    normalized = {"rmb": "CNY", "人民币": "CNY", "元": "CNY", "美元": "USD", "欧元": "EUR"}.get(
        currency, currency.upper()
    )
    return f"{normalized}/m2"


def _version_issues(evidence: list[dict[str, Any]]) -> list[ReviewIssue]:
    groups: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for item in evidence:
        if not _current(item):
            continue
        text = _text(item)
        number = _slot(text, "文件编号|资料编号|图号|document no\\.?")
        # A design revision and a supplier's datasheet revision are independent.
        if number:
            for version in VERSION_PATTERN.findall(text):
                groups[number][version.upper()].append(str(item["evidence_id"]))
    return [
        _issue(
            domain="cross_domain",
            issue_type="version_mismatch",
            summary=f"文件 {number} 同时存在多个未标记作废的版本",
            evidence_ids=[i for ids in versions.values() for i in ids],
            actual_value="、".join(sorted(versions)),
            expected_value="选定当前适用版本，旧版仅作历史参考",
            recommendation="审核人确认版本生效关系后重审。",
            severity="conflict",
            requires_human=True,
        )
        for number, versions in sorted(groups.items())
        if len(versions) > 1
    ]


def _thickness_issues(evidence: list[dict[str, Any]], workers: set[str]) -> list[ReviewIssue]:
    if "material" not in workers:
        return []
    groups: dict[tuple[str, str, str], dict[Decimal, list[str]]] = defaultdict(lambda: defaultdict(list))
    issues = []
    factors = {
        "mm": "1",
        "毫米": "1",
        "μm": ".001",
        "µm": ".001",
        "um": ".001",
        "微米": ".001",
        "m": "1000",
        "米": "1000",
        "cm": "10",
        "厘米": "10",
    }
    for item in evidence:
        if not _current(item) or evidence_role(item) == "price":
            continue
        matches = THICKNESS_PATTERN.findall(_text(item))
        if not matches:
            continue
        models = _models(item)
        if len(models) != 1 or len(matches) != 1 or not matches[0][1]:
            issues.append(
                _issue(
                    domain="material",
                    issue_type="thickness_scope_unclear",
                    summary="厚度缺少唯一材料型号、明确单位或单一取值，无法自动比较",
                    evidence_ids=[item["evidence_id"]],
                    recommendation="人工拆分材料行并补齐型号、单位和适用版本。",
                    requires_human=True,
                )
            )
            continue
        value, unit = matches[0]
        normalized = Decimal(value) * Decimal(factors[unit.lower()])
        applicable = _slot(_text(item), "适用版本|基准版本|applicable revision")
        match = THICKNESS_PATTERN.search(_text(item))
        prefix = _text(item)[max(0, match.start() - 20):match.start()]
        if re.search(r"涂层|保护区|coating|protective", prefix, re.I):
            measurement = "coating"
        else:
            measurement = "nominal_total"
        groups[(next(iter(models)), applicable, measurement)][normalized].append(str(item["evidence_id"]))
    for (model, applicable, measurement), values in sorted(groups.items()):
        if len(values) <= 1:
            continue
        issues.append(
            _issue(
                domain="material",
                issue_type="thickness_conflict" if applicable else "thickness_applicability_unclear",
                summary=f"材料 {model} 在适用版本 {applicable or '未注明'} 下的{measurement}厚度不一致",
                evidence_ids=[i for ids in values.values() for i in ids],
                actual_value="、".join(f"{format(v.normalize(), 'f')} mm" for v in sorted(values)),
                expected_value="同型号、同适用版本的名义厚度一致",
                recommendation="确认厚度定义、容差与生效资料，规则发现仅作为复核线索。",
                severity="conflict" if applicable else "warning",
                requires_human=True,
            )
        )
    return issues


def _material_alignment_issue(evidence: list[dict[str, Any]], workers: set[str]) -> list[ReviewIssue]:
    if not {"design", "material"}.issubset(workers):
        return []
    specs = [row for row in evidence if evidence_role(row) == "material" and _current(row)]
    missing: dict[str, list[str]] = defaultdict(list)
    for row in evidence:
        if evidence_role(row) != "design" or not _current(row):
            continue
        applicable = _slot(_text(row), "适用版本|基准版本|applicable revision")
        for model in _models(row):
            if not any(
                model in _models(spec)
                and (not applicable or applicable == _slot(_text(spec), "适用版本|基准版本|applicable revision"))
                for spec in specs
            ):
                missing[model].append(str(row["evidence_id"]))
    return [
        _issue(
            domain="cross_domain",
            issue_type="material_reference_missing",
            summary=f"设计引用的材料 {model} 未找到适用规格资料",
            evidence_ids=ids,
            actual_value=model,
            expected_value="独立的同型号、适用版本规格证据",
            recommendation="补充规格书或确认设计型号及生效版本。",
            requires_human=True,
        )
        for model, ids in sorted(missing.items())
    ]


def _price_issues(evidence: list[dict[str, Any]], workers: set[str]) -> list[ReviewIssue]:
    if "price" not in workers:
        return []
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    issues = []
    for row in evidence:
        if evidence_role(row) != "price":
            continue
        models = _models(row)
        region = _slot(_text(row), "地区|区域|region")
        tax = _slot(_text(row), "税口径|tax basis") or (
            "未税" if "未税" in _text(row) else "含税" if "含税" in _text(row) else ""
        )
        if len(models) != 1 or not region or not tax or not PRICE_UNIT_PATTERN.search(_text(row)):
            issues.append(
                _issue(
                    domain="price",
                    issue_type="price_scope_unclear",
                    summary="价格缺少型号、地区、税口径或币种面积单位，无法直接比较",
                    evidence_ids=[row["evidence_id"]],
                    recommendation="补齐可比口径，保留历史参考标识。",
                    requires_human=True,
                )
            )
            continue
        groups[(next(iter(models)), region, tax)].append(row)
    for key, rows in sorted(groups.items()):
        units: dict[str, list[str]] = defaultdict(list)
        dates: set[str] = set()
        for row in rows:
            for match in PRICE_UNIT_PATTERN.finditer(_text(row)):
                units[_normalize_price_unit(match)].append(str(row["evidence_id"]))
            dates.update(DATE_PATTERN.findall(_text(row)))
        if len(units) > 1:
            issues.append(
                _issue(
                    domain="price",
                    issue_type="price_unit_mismatch",
                    summary=f"材料 {key[0]} 同地区同税口径价格的币种不一致",
                    evidence_ids=[i for ids in units.values() for i in ids],
                    actual_value="、".join(sorted(units)),
                    recommendation="明确汇率与基准日期后再比较。",
                    requires_human=True,
                )
            )
        if len(dates) > 1:
            issues.append(
                _issue(
                    domain="price",
                    issue_type="price_date_comparability",
                    summary=f"材料 {key[0]} 价格包含多个日期，仅作历史比较",
                    evidence_ids=[row["evidence_id"] for row in rows],
                    actual_value="、".join(sorted(dates)),
                    recommendation="按日期分组展示，不能据此判定报价异常。",
                )
            )
    return issues


def validate_evidence(evidence: list[dict[str, Any]], workers: Iterable[str]) -> list[ReviewIssue]:
    selected = {worker for worker in workers if worker in WORKER_LABELS}
    issues = []
    for worker in sorted(selected):
        if any(evidence_role(row) == worker and _current(row) for row in evidence) or (
            worker == "price" and any(evidence_role(row) == worker for row in evidence)
        ):
            continue
        issues.append(
            _issue(
                domain=worker,
                issue_type="missing_domain_evidence",
                summary=f"未发现独立的{WORKER_LABELS[worker]}资料证据",
                expected_value=f"至少一条明确类型的{WORKER_LABELS[worker]}证据",
                recommendation="补充资料或改为专项审查。",
                requires_human=True,
            )
        )
    issues.extend(_version_issues(evidence))
    issues.extend(_thickness_issues(evidence, selected))
    issues.extend(_material_alignment_issue(evidence, selected))
    issues.extend(_price_issues(evidence, selected))
    return issues
