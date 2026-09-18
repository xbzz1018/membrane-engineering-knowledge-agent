from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.infrastructure.database import cases, prices, specs, storage


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


async def main() -> None:
    await storage.init()
    root = storage.settings.data_path
    case_rows = (
        read_jsonl(root / "synthetic_cases.jsonl")
        + read_jsonl(root / "public_cases.jsonl")
    )
    spec_rows = read_jsonl(root / "material_specs.jsonl")
    price_rows = read_jsonl(root / "price_records.jsonl")
    counts = {
        "cases": await storage.seed_payloads(cases, case_rows, "case_id", update_existing=True),
        "specs": await storage.seed_payloads(specs, spec_rows, "spec_id", update_existing=True),
        "prices": await storage.seed_payloads(prices, price_rows, "price_id", update_existing=True),
    }
    print(json.dumps(counts, ensure_ascii=False))
    await storage.close()


if __name__ == "__main__":
    asyncio.run(main())
