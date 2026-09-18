"""Evaluate 20 deterministic package reviews for schema, evidence, and conflict metrics."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import statistics
import sys
import time
import uuid
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Load the app only after isolating this deterministic evaluation from any
# developer database or Full-mode environment in the repository .env.
os.environ["RUNTIME_MODE"] = "local"
os.environ["MODEL_MODE"] = "fake"
os.environ["TEMPORAL_ENABLED"] = "false"
os.environ["AUTH_ENABLED"] = "false"
os.environ["LOCAL_DB_PATH"] = f"data/runtime/package-regression-{uuid.uuid4().hex}.db"

from src.core.config import get_settings
from src.main import app

DATASET = Path("data/eval/frozen_package_review_v3.jsonl")


def load_frozen() -> list[dict]:
    content = DATASET.read_bytes()
    expected = DATASET.with_suffix(".sha256").read_text(encoding="ascii").split()[0]
    if hashlib.sha256(content).hexdigest() != expected:
        raise RuntimeError("Frozen package SHA mismatch")
    rows = [json.loads(line) for line in content.decode("utf-8").splitlines() if line]
    if len(rows) != 20:
        raise RuntimeError(f"Frozen package set must contain 20 rows, got {len(rows)}")
    return rows


async def main() -> None:
    settings = get_settings()
    if settings.MODEL_MODE.lower() != "fake" or settings.TEMPORAL_ENABLED:
        raise RuntimeError("Package structure evaluation requires MODEL_MODE=fake and TEMPORAL_ENABLED=false")
    rows = load_frozen()
    results = []
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=120) as client:
            for row in rows:
                started = time.perf_counter()
                document_ids = []
                for index, content in enumerate(row["documents"], 1):
                    uploaded = await client.post(
                        "/api/v1/documents/upload",
                        data={"project_id": settings.DEFAULT_PROJECT_ID},
                        files={
                            "file": (
                                f"{row['eval_id']}-{index}.txt",
                                content.encode("utf-8"),
                                "text/plain",
                            )
                        },
                    )
                    uploaded.raise_for_status()
                    document_id = uploaded.json()["document_id"]
                    indexed = await client.post(f"/api/v1/documents/{document_id}/index")
                    indexed.raise_for_status()
                    document_ids.append(document_id)
                response = await client.post("/api/v1/package-reviews", json={
                    "project_id": settings.DEFAULT_PROJECT_ID,
                    "document_ids": document_ids,
                    "question": row["question"],
                })
                response.raise_for_status()
                payload = response.json()
                workers = payload["worker_results"]
                findings = [finding for result in workers.values() for finding in result["findings"]]
                cited = sum(bool(finding["evidence_ids"]) for finding in findings)
                processed = [item for result in workers.values() for item in result["processed_evidence_ids"]]
                predicted_conflict = bool(payload["conflicts"])
                results.append({
                    "schema": set(workers) == {"design", "material", "price"},
                    "citation_coverage": cited / len(findings) if findings else 1.0,
                    "processed": bool(processed),
                    "expected_conflict": bool(row["expected_conflict"]),
                    "predicted_conflict": predicted_conflict,
                    "latency_ms": (time.perf_counter() - started) * 1000,
                })
    tp = sum(item["expected_conflict"] and item["predicted_conflict"] for item in results)
    fp = sum(not item["expected_conflict"] and item["predicted_conflict"] for item in results)
    fn = sum(item["expected_conflict"] and not item["predicted_conflict"] for item in results)
    conflict_f1 = (2 * tp) / ((2 * tp) + fp + fn) if tp or fp or fn else 1.0
    latencies = sorted(item["latency_ms"] for item in results)
    summary = {
        "dataset": "frozen_package_review_v3",
        "rows": len(results),
        "worker_schema_rate": round(sum(item["schema"] for item in results) / len(results), 4),
        "citation_coverage": round(statistics.mean(item["citation_coverage"] for item in results), 4),
        "evidence_processed_rate": round(sum(item["processed"] for item in results) / len(results), 4),
        "conflict_f1": round(conflict_f1, 4),
        "latency_ms": {
            "p50": round(statistics.median(latencies), 2),
            "p95": round(latencies[int(len(latencies) * 0.95) - 1], 2),
        },
    }
    if min(summary["worker_schema_rate"], summary["citation_coverage"], summary["evidence_processed_rate"]) < 0.90:
        raise AssertionError(json.dumps(summary, ensure_ascii=False))
    if conflict_f1 < 0.80:
        raise AssertionError(json.dumps(summary, ensure_ascii=False))
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
