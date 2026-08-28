"""Evaluate v2 retrieval Recall@10 and MRR without generation-model variance."""

from __future__ import annotations

import asyncio
import hashlib
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core.config import get_settings
from src.engineering.retrieval import RetrievalService
from src.main import app

DATASET = Path("data/eval/frozen_retrieval_v2.jsonl")


def load_frozen() -> list[dict]:
    content = DATASET.read_bytes()
    expected = DATASET.with_suffix(".sha256").read_text(encoding="ascii").split()[0]
    actual = hashlib.sha256(content).hexdigest()
    if actual != expected:
        raise RuntimeError("Frozen retrieval SHA mismatch")
    rows = [json.loads(line) for line in content.decode("utf-8").splitlines() if line]
    if len(rows) != 60:
        raise RuntimeError(f"Frozen retrieval set must contain 60 rows, got {len(rows)}")
    return rows


async def main() -> None:
    settings = get_settings()
    rows = load_frozen()
    service = RetrievalService()
    results = []
    async with app.router.lifespan_context(app):
        for row in rows:
            started = time.perf_counter()
            packet = await service.retrieve(row["query"], settings.DEFAULT_PROJECT_ID, limit=10)
            source_ids = [source["source_id"] for source in packet.sources]
            expected = row["expected_source_id"]
            rank = source_ids.index(expected) + 1 if expected in source_ids else None
            results.append({
                "eval_id": row["eval_id"],
                "hit": rank is not None,
                "reciprocal_rank": 1 / rank if rank else 0,
                "latency_ms": (time.perf_counter() - started) * 1000,
            })
    recall = sum(item["hit"] for item in results) / len(results)
    mrr = statistics.mean(item["reciprocal_rank"] for item in results)
    latencies = sorted(item["latency_ms"] for item in results)
    summary = {
        "dataset": "frozen_retrieval_v2",
        "rows": len(rows),
        "recall_at_10": round(recall, 4),
        "mrr": round(mrr, 4),
        "latency_ms": {
            "p50": round(statistics.median(latencies), 2),
            "p95": round(latencies[int(len(latencies) * 0.95) - 1], 2),
        },
        "misses": [item["eval_id"] for item in results if not item["hit"]],
    }
    if recall < 0.90:
        raise AssertionError(json.dumps(summary, ensure_ascii=False))
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
