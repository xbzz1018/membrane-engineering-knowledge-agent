"""Generate deterministic synthetic price scenarios that are never market quotations."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

MATERIALS = [
    ("PTFE", "PTFE-coated fiberglass test scenario", 260),
    ("PVC/PVDF", "PVC/PVDF-coated polyester test scenario", 90),
    ("ETFE", "ETFE film test scenario", 380),
    ("PTFE mesh", "PTFE-coated mesh test scenario", 180),
    ("PVC mesh", "PVC-coated facade mesh test scenario", 70),
]
REGIONS = ["华东 synthetic", "华南 synthetic", "华北 synthetic", "西南 synthetic"]
DATES = ["2024-01", "2024-07", "2025-01"]
GENERATED_AT = "2026-08-27T00:00:00+00:00"


def _sha256(record: dict) -> str:
    payload = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build() -> list[dict]:
    rows = []
    for material_index, (material, specification, base_price) in enumerate(MATERIALS):
        for region_index, region in enumerate(REGIONS):
            for date_index, effective_date in enumerate(DATES):
                scenario = material_index * 12 + region_index * 3 + date_index + 1
                minimum = base_price + region_index * 7 + date_index * 5
                row = {
                    "price_id": f"synthetic-price-{scenario:03d}",
                    "material": material,
                    "specification": specification,
                    "unit": "CNY/m2 synthetic",
                    "min_price": minimum,
                    "max_price": minimum + 45 + material_index * 15,
                    "region": region,
                    "effective_date": effective_date,
                    "currency": "CNY",
                    "disclaimer": "Synthetic test data only; not a market price or formal quotation.",
                    "source_url": f"synthetic://price-scenarios/{scenario:03d}",
                    "source_type": "synthetic_price_scenario",
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
    parser.add_argument("--output", type=Path, default=Path("data/processed/price_records.jsonl"))
    args = parser.parse_args()
    rows = build()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )
    print(f"synthetic_prices={len(rows)} output={args.output}")


if __name__ == "__main__":
    main()
