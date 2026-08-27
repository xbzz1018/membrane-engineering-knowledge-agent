from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def validate() -> int:
    root = ROOT / "data" / "processed"
    public = read_jsonl(root / "public_cases.jsonl")
    synthetic = read_jsonl(root / "synthetic_cases.jsonl")
    fixtures = read_jsonl(root / "cases.jsonl")
    specs = read_jsonl(root / "material_specs.jsonl")
    prices = read_jsonl(root / "price_records.jsonl")
    errors: list[str] = []
    all_cases = public + synthetic + fixtures
    if len(public) < 100:
        errors.append(f"public_cases < 100: {len(public)}")
    if len(synthetic) < 50:
        errors.append(f"synthetic_cases < 50: {len(synthetic)}")
    if len({row.get('case_id') for row in all_cases}) != len(all_cases):
        errors.append("duplicate case_id")
    for row in public:
        for field in ("case_id", "title", "structure_type", "location", "source_url", "license"):
            if not row.get(field):
                errors.append(f"public case {row.get('case_id')} missing {field}")
    for row in specs + prices:
        if not row.get("source_url") or "synthetic" not in row:
            errors.append(f"record {row.get('spec_id') or row.get('price_id')} missing provenance")
    print(f"public={len(public)} synthetic={len(synthetic)} fixtures={len(fixtures)} specs={len(specs)} prices={len(prices)}")
    if errors:
        print("\n".join(errors))
        return 1
    print("data-validation-ok")
    return 0


if __name__ == "__main__":
    sys.exit(validate())
