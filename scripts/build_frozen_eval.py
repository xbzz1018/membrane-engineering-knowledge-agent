"""Build the deterministic v1 frozen evaluation set and its attested SHA-256."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

OUTPUT = Path("data/eval/frozen_v1.jsonl")
ATTESTATION = Path("data/eval/frozen_v1.sha256")


def build() -> list[dict]:
    rows = []
    materials = ["PTFE", "PVC/PVDF", "ETFE", "Precontraint 502", "PTFE mesh"]
    material_questions = [
        "的厚度和重量规格是什么",
        "的透光性能和适用场景是什么",
        "膜材规格应核对哪些单位",
        "技术参数来源和版本是什么",
    ]
    for material in materials:
        for question in material_questions:
            rows.append({
                "eval_id": f"material-{len(rows) + 1:03d}",
                "category": "material",
                "query": f"{material}{question}",
                "expected_route": "material",
                "required_source_types": ["material_spec"],
            })

    price_materials = ["PTFE", "PVC/PVDF", "ETFE", "PTFE mesh", "PVC mesh"]
    regions = ["华东 synthetic", "华南 synthetic", "华北 synthetic", "西南 synthetic"]
    for material in price_materials:
        for region in regions:
            rows.append({
                "eval_id": f"price-{len(rows) + 1:03d}",
                "category": "price",
                "query": f"查询 {region} 的 {material} 历史价格和资料日期，仅作成本参考",
                "expected_route": "price",
                "required_source_types": ["price"],
            })

    locations = ["上海", "苏州", "杭州", "南京", "宁波"]
    applications = ["体育场", "入口雨棚", "交通连廊", "停车棚"]
    for location in locations:
        for application in applications:
            rows.append({
                "eval_id": f"design-{len(rows) + 1:03d}",
                "category": "design",
                "query": f"查找 {location} {application} 的相似设计方案和案例",
                "expected_route": "design",
                "required_source_types": ["case"],
            })

    multi_materials = ["PTFE", "PVC/PVDF", "ETFE", "Precontraint 502", "PTFE mesh"]
    multi_questions = [
        "比较体育场方案、膜材规格和历史价格",
        "对比入口雨棚案例、材料参数与成本资料",
        "比较交通连廊设计、膜材版本和价格日期",
        "对比停车棚方案与材料价格，不生成正式报价",
    ]
    for material in multi_materials:
        for question in multi_questions:
            rows.append({
                "eval_id": f"multi-{len(rows) + 1:03d}",
                "category": "multi",
                "query": f"{material} {question}",
                "expected_route": "multi",
                "required_source_types": ["case"],
            })
    if len(rows) != 80:
        raise AssertionError(f"Frozen evaluation set must contain 80 rows, got {len(rows)}")
    return rows


def main() -> None:
    rows = build()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    payload = "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows) + "\n"
    encoded = payload.encode("utf-8")
    OUTPUT.write_bytes(encoded)
    digest = hashlib.sha256(encoded).hexdigest()
    ATTESTATION.write_text(f"{digest}  {OUTPUT.name}\n", encoding="ascii")
    print(json.dumps({"rows": len(rows), "sha256": digest, "output": str(OUTPUT)}, sort_keys=True))


if __name__ == "__main__":
    main()
