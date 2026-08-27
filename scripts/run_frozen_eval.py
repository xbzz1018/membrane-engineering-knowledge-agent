"""Run the frozen evaluation set through the real application API."""

from __future__ import annotations

import asyncio
import hashlib
import json
import statistics
import sys
import time
import uuid
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core.config import get_settings
from src.main import app

DATASET = Path("data/eval/frozen_v1.jsonl")
ATTESTATION = Path("data/eval/frozen_v1.sha256")


def load_frozen() -> list[dict]:
    content = DATASET.read_bytes()
    expected = ATTESTATION.read_text(encoding="ascii").split()[0]
    actual = hashlib.sha256(content).hexdigest()
    if actual != expected:
        raise RuntimeError(f"Frozen evaluation SHA mismatch: expected {expected}, actual {actual}")
    rows = [json.loads(line) for line in content.decode("utf-8").splitlines() if line]
    if len(rows) != 80:
        raise RuntimeError(f"Frozen evaluation set must contain 80 rows, got {len(rows)}")
    return rows


async def main() -> None:
    settings = get_settings()
    if settings.MODEL_MODE.lower() != "api" or settings.RUNTIME_MODE.lower() != "full":
        raise RuntimeError("Frozen evaluation requires Full runtime and real API model mode")
    rows = load_frozen()
    run_id = uuid.uuid4().hex[:10]
    semaphore = asyncio.Semaphore(4)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=120) as client:
            async def evaluate(row: dict) -> dict:
                async with semaphore:
                    started = time.perf_counter()
                    response = await client.post(
                        "/api/v1/chat",
                        json={
                            "user_id": f"frozen-eval-v1-{run_id}",
                            "session_id": row["eval_id"],
                            "message": row["query"],
                        },
                    )
                    latency = (time.perf_counter() - started) * 1000
                if response.status_code != 200:
                    return {
                        "eval_id": row["eval_id"],
                        "route_ok": False,
                        "source_ok": False,
                        "answer_present": False,
                        "latency": latency,
                        "error": f"HTTP {response.status_code}",
                    }
                payload = response.json()
                source_types = {source["source_type"] for source in payload["sources"]}
                return {
                    "eval_id": row["eval_id"],
                    "route_ok": payload["route"] == row["expected_route"],
                    "source_ok": set(row["required_source_types"]) <= source_types,
                    "answer_present": bool(payload["answer"]),
                    "latency": latency,
                }

            results = await asyncio.gather(*(evaluate(row) for row in rows))
    route_passes = sum(result["route_ok"] for result in results)
    source_passes = sum(result["source_ok"] for result in results)
    errors = [
        {key: value for key, value in result.items() if key != "latency"}
        for result in results
        if not (result["route_ok"] and result["source_ok"] and result["answer_present"])
    ]
    latencies = [result["latency"] for result in results]
    summary = {
        "dataset": "frozen_v1",
        "run_id": run_id,
        "rows": len(rows),
        "route_passes": route_passes,
        "source_passes": source_passes,
        "errors": len(errors),
        "latency_ms": {
            "mean": round(statistics.mean(latencies), 2),
            "p95": round(sorted(latencies)[int(len(latencies) * 0.95) - 1], 2),
        },
    }
    if route_passes != len(rows) or source_passes < 76 or errors:
        raise AssertionError(json.dumps({**summary, "failures": errors[:20]}, ensure_ascii=False))
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
