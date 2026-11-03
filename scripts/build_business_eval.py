"""Build hand-authored synthetic business regression cases, not a held-out benchmark."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "data/eval/business_review_v1.jsonl"


def cases() -> list[dict]:
    design = "设计方案采用 PTFE-502，厚度 0.8 mm，适用版本 R1。版本 D3。"
    material = "膜材规格 PTFE-502，厚度 0.8 mm，适用版本 R1。版本 S7。"
    price = "历史价格 PTFE-502，235 CNY/m2，地区 上海，含税，日期 2026-03。"
    rows = []

    def add(key, category, expected, texts, issue_types=(), evidence_docs=()):
        rows.append(
            {
                "eval_id": key,
                "category": category,
                "synthetic": True,
                "split": "regression",
                "question": "核验设计、材料和历史价格资料的一致性与可比口径。",
                "documents": [{"filename": f"{role}.txt", "text": text} for role, text in texts],
                "expected_human_review": expected,
                "expected_issue_types": list(issue_types),
                "expected_evidence_documents": list(evidence_docs),
            }
        )

    def docs(d=design, m=material, p=price):
        return [("design", d), ("material", m), ("price", p)]

    add("ok-mm", "coherent", False, docs())
    add("ok-micrometre", "unit_equivalence", False, docs(m=material.replace("0.8 mm", "800 μm")))
    add("ok-metre", "unit_equivalence", False, docs(m=material.replace("0.8 mm", "0.0008 m")))
    add("ok-decimal", "unit_equivalence", False, docs(m=material.replace("0.8 mm", "0.80 mm")))
    add(
        "ok-independent-revisions",
        "version_scope",
        False,
        docs(d=design + " 文件编号 D-01。", m=material + " 文件编号 S-01。"),
    )
    add(
        "ok-other-material",
        "entity_scope",
        False,
        docs() + [("material-other", "膜材规格 ETFE-250，厚度 0.25 mm，适用版本 R1。")],
    )
    add(
        "ok-other-applicability",
        "version_scope",
        False,
        docs() + [("material-r0", "膜材规格 PTFE-502，厚度 0.7 mm，适用版本 R0。")],
    )
    add(
        "ok-superseded",
        "version_scope",
        False,
        docs() + [("material-old", "历史参考 已作废 膜材规格 PTFE-502，厚度 0.7 mm，适用版本 R1。")],
    )
    add(
        "ok-price-region",
        "price_scope",
        False,
        docs() + [("price-other", price.replace("上海", "北京").replace("CNY", "USD"))],
    )
    add(
        "ok-price-tax",
        "price_scope",
        False,
        docs() + [("price-tax", price.replace("含税", "未税").replace("CNY", "USD"))],
    )
    add(
        "ok-price-history",
        "price_scope",
        False,
        docs() + [("price-older", price.replace("2026-03", "2025-03").replace("235", "220"))],
    )
    add("ok-alias-currency", "price_scope", False, docs() + [("price-alias", price.replace("CNY/m2", "元/平方米"))])
    add("bad-thickness", "thickness", True, docs(m=material.replace("0.8", "0.7")), ["thickness_conflict"], [0, 1])
    add(
        "bad-unit-converted",
        "thickness",
        True,
        docs(m=material.replace("0.8 mm", "700 um")),
        ["thickness_conflict"],
        [0, 1],
    )
    add(
        "unclear-unit",
        "insufficient_scope",
        True,
        docs(m=material.replace("0.8 mm", "0.8")),
        ["thickness_scope_unclear"],
        [1],
    )
    add(
        "unclear-multiple-models",
        "insufficient_scope",
        True,
        docs(m=material + " 同行还记录 ETFE-250。"),
        ["thickness_scope_unclear"],
        [1],
    )
    add(
        "bad-active-revisions",
        "version_scope",
        True,
        docs()
        + [
            ("design-copy-a", "设计资料 文件编号 D-01，版本 V1。"),
            ("design-copy-b", "设计资料 文件编号 D-01，版本 V2。"),
        ],
        ["version_mismatch"],
        [3, 4],
    )
    add(
        "missing-spec",
        "missing_evidence",
        True,
        [("design", design), ("price", price)],
        ["missing_domain_evidence", "material_reference_missing"],
        [0],
    )
    add(
        "missing-price",
        "missing_evidence",
        True,
        [("design", design), ("material", material)],
        ["missing_domain_evidence"],
    )
    add(
        "bad-model-reference",
        "entity_scope",
        True,
        docs(m=material.replace("PTFE-502", "PTFE-702")),
        ["material_reference_missing"],
        [0],
    )
    add(
        "bad-applicable-reference",
        "version_scope",
        True,
        docs(m=material.replace("R1", "R0")),
        ["material_reference_missing"],
        [0],
    )
    add(
        "unclear-currency",
        "price_scope",
        True,
        docs() + [("price-usd", price.replace("CNY", "USD"))],
        ["price_unit_mismatch"],
        [2, 3],
    )
    add("unclear-tax", "price_scope", True, docs(p=price.replace("含税，", "")), ["price_scope_unclear"], [2])
    add(
        "unclear-applicability",
        "insufficient_scope",
        True,
        docs(d=design.replace("适用版本 R1。", ""), m=material.replace("适用版本 R1。", "").replace("0.8", "0.7")),
        ["thickness_applicability_unclear"],
        [0, 1],
    )
    return rows


def main():
    rows = cases()
    DATASET.parent.mkdir(parents=True, exist_ok=True)
    encoded = ("\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows) + "\n").encode("utf-8")
    DATASET.write_bytes(encoded)
    digest = hashlib.sha256(encoded).hexdigest()
    DATASET.with_suffix(".sha256").write_text(f"{digest}  {DATASET.name}\n", encoding="ascii")
    print(
        json.dumps({"rows": len(rows), "positive": sum(row["expected_human_review"] for row in rows), "sha256": digest})
    )


if __name__ == "__main__":
    main()
