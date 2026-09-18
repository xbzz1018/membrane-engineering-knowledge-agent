from __future__ import annotations

import json
from pathlib import Path

from src.infrastructure.database import EngineeringStorage, cases, prices, specs


def load_local_data(store: EngineeringStorage) -> dict[str, list[dict]]:
    data_root = store.settings.data_path if hasattr(store, "settings") else Path(__file__).resolve().parents[2] / "data" / "processed"
    return {
        "cases": (
            _read_jsonl(data_root / "synthetic_cases.jsonl")
            + _read_jsonl(data_root / "public_cases.jsonl")
        ),
        "specs": _read_jsonl(data_root / "material_specs.jsonl"),
        "prices": _read_jsonl(data_root / "price_records.jsonl"),
    }


async def seed_local_data(store: EngineeringStorage) -> dict[str, int]:
    rows = load_local_data(store)
    return {
        "cases": await store.seed_payloads(cases, rows["cases"], "case_id", update_existing=True),
        "specs": await store.seed_payloads(specs, rows["specs"], "spec_id", update_existing=True),
        "prices": await store.seed_payloads(prices, rows["prices"], "price_id", update_existing=True),
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
