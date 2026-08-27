from __future__ import annotations

import json
from pathlib import Path

from src.engineering.storage import EngineeringStorage, cases, prices, specs


async def seed_local_data(store: EngineeringStorage) -> dict[str, int]:
    data_root = store.settings.data_path if hasattr(store, "settings") else Path(__file__).resolve().parents[2] / "data" / "processed"
    # Keep the committed fixture small; larger datasets are imported by scripts.
    case_rows = _read_jsonl(data_root / "cases.jsonl")
    spec_rows = _read_jsonl(data_root / "material_specs.jsonl")
    price_rows = _read_jsonl(data_root / "price_records.jsonl")
    return {
        "cases": await store.seed_payloads(cases, case_rows, "case_id"),
        "specs": await store.seed_payloads(specs, spec_rows, "spec_id"),
        "prices": await store.seed_payloads(prices, price_rows, "price_id"),
    }


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows
