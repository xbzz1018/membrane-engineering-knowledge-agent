"""Limited areal-mass checks: preserve units and compare only explicit scope."""

import re
from collections import defaultdict
from decimal import Decimal

from src.domain.review_rules import _current, _issue, _models, _slot, _text, evidence_role

MASS = re.compile(
    r"(?:单位面积质量|面密度|克重|mass per unit area)\s*[:：]?\s*(\d+(?:\.\d+)?)\s*"
    r"(?:(kg|g|千克|克)\s*/\s*(?:m2|m²|㎡|平方米))?", re.I,
)


def mass_issues(evidence: list[dict], workers: set[str]):
    if "material" not in workers:
        return []
    groups = defaultdict(lambda: defaultdict(list))
    issues = []
    for row in evidence:
        if not _current(row) or evidence_role(row) == "price":
            continue
        text = _text(row)
        matches = list(MASS.finditer(text))
        models = _models(row)
        if len(matches) != 1 or len(models) != 1:
            continue
        match = matches[0]
        number, unit = match.groups()
        ids = [row["evidence_id"]]
        if not unit:
            issues.append(_issue(domain="material", issue_type="mass_unit_missing",
                summary="单位面积质量缺少明确单位", evidence_ids=ids,
                expected_value="明确 g/m² 或 kg/m²，保留原文依据", requires_human=True))
            continue
        revision = _slot(text, "适用版本|基准版本|applicable revision")
        if not revision:
            # An isolated measured value is legitimate; absence of an applicable
            # revision alone is not a conflict. Do not infer cross-file pairing.
            continue
        value = Decimal(number) * (Decimal(1000) if unit.lower() in {"kg", "千克"} else Decimal(1))
        groups[(next(iter(models)), revision)][value].extend(ids)
    for (model, revision), values in groups.items():
        if len(values) > 1:
            issues.append(_issue(domain="material", issue_type="mass_per_area_conflict",
                summary=f"{model} 在适用版本 {revision} 的单位面积质量不同，需核对名义值、容差及定义",
                evidence_ids=[eid for ids in values.values() for eid in ids],
                actual_value=", ".join(f"{value} g/m²" for value in sorted(values)),
                expected_value="同对象、版本与测量口径一致；差异由审核人确认", requires_human=True))
    return issues
