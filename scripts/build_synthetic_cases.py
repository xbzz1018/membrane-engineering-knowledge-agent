"""Generate reproducible synthetic engineering cases for local evaluation."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

APPLICATIONS = ["体育场", "入口雨棚", "交通连廊", "停车棚", "景观廊架", "环保设施"]
STRUCTURES = ["索膜结构", "张拉膜结构", "骨架式", "气枕式"]
MATERIALS = ["PTFE", "PVC/PVDF", "ETFE"]
LOCATIONS = ["上海", "苏州", "杭州", "南京", "嘉兴", "宁波"]
GENERATED_AT = "2026-08-27T00:00:00+00:00"


def _sha256(record: dict) -> str:
    payload = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def enrich_case_fixtures(path: Path) -> int:
    if not path.exists():
        return 0
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    enriched = []
    for original in rows:
        row = {
            **original,
            "license": original.get("license") or "Project-generated synthetic fixture; repository LICENSE applies.",
            "retrieved_at": original.get("retrieved_at") or GENERATED_AT,
        }
        row["source_sha256"] = original.get("source_sha256") or _sha256(row)
        enriched.append(row)
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in enriched) + "\n",
        encoding="utf-8",
    )
    return len(enriched)


def build(count: int) -> list[dict]:
    rows = []
    for index in range(1, count + 1):
        material = MATERIALS[(index - 1) % len(MATERIALS)]
        application = APPLICATIONS[(index - 1) % len(APPLICATIONS)]
        row = {
            "case_id": f"synthetic-case-{index:04d}",
            "title": f"{LOCATIONS[(index - 1) % len(LOCATIONS)]}{application}{index:03d}",
            "application": application,
            "structure_type": STRUCTURES[(index - 1) % len(STRUCTURES)],
            "membrane_material": material,
            "location": LOCATIONS[(index - 1) % len(LOCATIONS)],
            "year": 2020 + index % 6,
            "area_m2": 300 + (index % 18) * 180,
            "design_goal": "遮阳、采光、通行和耐久性之间的方案比较",
            "material_selection_reason": f"{material} 作为合成测试样例，不代表真实项目结论",
            "source_url": "synthetic://generated-cases",
            "source_type": "synthetic",
            "source_version": "v1",
            "license": "Project-generated synthetic fixture; repository LICENSE applies.",
            "retrieved_at": GENERATED_AT,
            "synthetic": True,
        }
        row["source_sha256"] = _sha256(row)
        rows.append(row)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--output", type=Path, default=Path("data/processed/synthetic_cases.jsonl"))
    parser.add_argument("--fixture-path", type=Path, default=Path("data/fixtures/cases.jsonl"))
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in build(args.count)) + "\n", encoding="utf-8")
    fixture_count = enrich_case_fixtures(args.fixture_path)
    print(f"generated={args.count} output={args.output} fixtures={fixture_count}")


if __name__ == "__main__":
    main()
