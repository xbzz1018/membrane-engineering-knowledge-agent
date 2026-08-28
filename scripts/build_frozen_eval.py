"""Build attested v2 retrieval and package-review evaluation sets."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path("data/eval")
RETRIEVAL_OUTPUT = ROOT / "frozen_retrieval_v2.jsonl"
PACKAGE_OUTPUT = ROOT / "frozen_packages_v2.jsonl"


def _read(path: str) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line]


def build_retrieval() -> list[dict]:
    rows: list[dict] = []
    for item in _read("data/processed/material_specs.jsonl")[:20]:
        rows.append({
            "eval_id": f"spec-{len(rows) + 1:03d}",
            "category": "material_spec",
            "query": (
                f"查询 {item['manufacturer']} 型号 {item['product_reference']} 的规格和版本 "
                f"{item['source_version']}"
            ),
            "expected_source_id": f"spec:{item['spec_id']}",
        })
    for item in _read("data/processed/price_records.jsonl")[:20]:
        rows.append({
            "eval_id": f"price-{len(rows) + 1:03d}",
            "category": "price",
            "query": (
                f"查询 {item['region']} {item['material']} {item['effective_date']} "
                f"{item['unit']} synthetic 历史价格"
            ),
            "expected_source_id": f"price:{item['price_id']}",
        })
    for item in _read("data/processed/synthetic_cases.jsonl")[:20]:
        rows.append({
            "eval_id": f"case-{len(rows) + 1:03d}",
            "category": "case",
            "query": (
                f"查找案例 {item['title']}，地点 {item['location']}，结构 {item['structure_type']}，"
                f"膜材 {item['membrane_material']}"
            ),
            "expected_source_id": f"case:{item['case_id']}",
        })
    if len(rows) != 60:
        raise AssertionError(f"retrieval set must contain 60 rows, got {len(rows)}")
    return rows


def build_packages() -> list[dict]:
    return [
        {
            "eval_id": f"package-{index:03d}",
            "question": "审查设计、膜材和价格资料，识别厚度与版本冲突。",
            "documents": [
                f"设计资料 {index}：PTFE 膜材厚度 0.7 mm，设计版本 1，日期 2025-01。",
                f"采购价格资料 {index}：PTFE 膜材厚度 0.8 mm，版本 2，日期 2025-02，synthetic 价格。",
            ],
            "expected_conflict": True,
        }
        for index in range(1, 21)
    ]


def _write(path: Path, rows: list[dict]) -> str:
    payload = "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows) + "\n"
    encoded = payload.encode("utf-8")
    path.write_bytes(encoded)
    digest = hashlib.sha256(encoded).hexdigest()
    path.with_suffix(".sha256").write_text(f"{digest}  {path.name}\n", encoding="ascii")
    return digest


def main() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    summary = {
        "retrieval": {"rows": 60, "sha256": _write(RETRIEVAL_OUTPUT, build_retrieval())},
        "packages": {"rows": 20, "sha256": _write(PACKAGE_OUTPUT, build_packages())},
    }
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
