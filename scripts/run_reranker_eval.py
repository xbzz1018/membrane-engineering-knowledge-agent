"""Explicit lexical-vs-neural-reranker ablation, independent of embedding service."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import statistics
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


async def run(output):
    from scripts.run_business_eval import code_digest
    from src.core.config import get_settings
    from src.evaluation.metrics import latency_summary, retrieval_metrics
    from src.infrastructure.database import _score
    from src.infrastructure.model_provider import ModelProvider

    settings = get_settings()
    provider = ModelProvider(settings)
    if settings.MODEL_MODE != "api" or not settings.RERANKER_ENABLED:
        raise ValueError("API mode and enabled real reranker required")
    source_hash = code_digest()
    path = ROOT / "data/eval/frozen_difficult_retrieval_v3.jsonl"
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != path.with_suffix(".sha256").read_text(encoding="ascii").split()[0]:
        raise ValueError("Dataset SHA mismatch")
    rows = [json.loads(line) for line in raw.decode().splitlines() if line]
    corpus = {row["document_key"]: row for row in rows}
    results = []
    semaphore = asyncio.Semaphore(3)

    async def query(row):
        async with semaphore:
            result = {"eval_id": row["eval_id"], "category": row["difficulty"], "error": None}
            try:
                candidates = [
                    {
                        "id": key,
                        "text": f"文件名：{item['filename']}\n正文：{item['content']}",
                        "score": _score(row["query"], item["filename"]) * 4 + _score(row["query"], item["content"]),
                    }
                    for key, item in sorted(corpus.items())
                ]
                candidates = sorted(candidates, key=lambda item: item["score"], reverse=True)
                candidates = [item for item in candidates if item["score"] > 0][:30]
                started = time.perf_counter()
                reranked = await provider.rerank(row["query"], candidates, top_n=30)
                result["rerank_ms"] = (time.perf_counter() - started) * 1000
                relevant = {row["document_key"]}
                result.update(
                    {
                        "relevant_ids": sorted(relevant),
                        "candidate_count": len(candidates),
                        "lexical": retrieval_metrics([item["id"] for item in candidates], relevant, 10),
                        "reranked": retrieval_metrics([item["id"] for item in reranked], relevant, 10),
                        "lexical_order": [item["id"] for item in candidates],
                        "reranked_order": [item["id"] for item in reranked],
                    }
                )
            except Exception as exc:
                result["error"] = type(exc).__name__
            results.append(result)
            (output / "predictions.jsonl").write_text(
                "\n".join(
                    json.dumps(item, ensure_ascii=False) for item in sorted(results, key=lambda item: item["eval_id"])
                )
                + "\n",
                encoding="utf-8",
            )

    await asyncio.gather(*(query(row) for row in rows))
    completed = [item for item in results if item["error"] is None]

    def aggregate(items, profile):
        return {
            metric: statistics.mean(item[profile][metric] for item in items) if items else None
            for metric in ("recall_at_10", "rr_at_10")
        }

    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset": "frozen_difficult_retrieval_v3",
        "dataset_sha256": digest,
        "code_sha256": source_hash,
        "source_changed_during_run": code_digest() != source_hash,
        "experiment": "lexical_vs_real_neural_reranker_no_vectors",
        "model": settings.RERANKER_MODEL,
        "corpus_documents": len(corpus),
        "n": len(rows),
        "completed": len(completed),
        "failures": len(rows) - len(completed),
        "lexical": aggregate(completed, "lexical"),
        "reranked": aggregate(completed, "reranked"),
        "rerank_ms": latency_summary([item["rerank_ms"] for item in completed]),
        "by_category": {
            category: {
                "n": len(items),
                "lexical": aggregate(items, "lexical"),
                "reranked": aggregate(items, "reranked"),
            }
            for category in sorted({row["difficulty"] for row in rows})
            if (items := [item for item in completed if item["category"] == category])
        },
        "limitations": [
            "Synthetic developer corpus, not held-out or internal resume data",
            "No vector/pgvector/RRF performance claim",
            "30 candidates may cover entire 30-document corpus; favorable reranking ceiling",
            "Only answerable single-relevance queries, no production extrapolation",
        ],
    }
    summary["lexical"]["mrr_at_10"] = summary["lexical"].pop("rr_at_10")
    summary["reranked"]["mrr_at_10"] = summary["reranked"].pop("rr_at_10")
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary["failures"]:
        raise SystemExit(1)


if __name__ == "__main__":
    output = (
        ROOT
        / "data/eval/results/reranker_ablation_v1"
        / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8])
    )
    output.mkdir(parents=True)
    os.environ.update(
        {
            "RUNTIME_MODE": "local",
            "MODEL_MODE": "api",
            "TEMPORAL_ENABLED": "false",
            "DATABASE_URL": "",
            "LOCAL_DB_PATH": str(output / "unused.db"),
            "RERANKER_ENABLED": "true",
        }
    )
    asyncio.run(run(output))
