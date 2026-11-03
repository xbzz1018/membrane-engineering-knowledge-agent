"""Real embedding/reranker experiment using in-memory cosine; no pgvector claim."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import statistics
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left or not all(math.isfinite(v) for v in left + right):
        raise ValueError("Invalid vectors")
    denom = math.sqrt(sum(v * v for v in left) * sum(v * v for v in right))
    if not denom:
        raise ValueError("Zero vector")
    return sum(a * b for a, b in zip(left, right)) / denom


async def run(output: Path):
    from scripts.run_business_eval import code_digest
    from src.core.config import get_settings
    from src.evaluation.metrics import latency_summary, retrieval_metrics
    from src.infrastructure.database import _fuse_ranked, _score
    from src.infrastructure.model_provider import ModelProvider

    settings = get_settings()
    if settings.MODEL_MODE != "api" or not settings.RERANKER_ENABLED:
        raise ValueError("Real API embeddings and reranker required")
    provider = ModelProvider(settings)
    dataset = ROOT / "data/eval/frozen_difficult_retrieval_v3.jsonl"
    raw = dataset.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != dataset.with_suffix(".sha256").read_text(encoding="ascii").split()[0]:
        raise ValueError("Dataset SHA mismatch")
    rows = [json.loads(line) for line in raw.decode().splitlines() if line]
    corpus = {row["document_key"]: row for row in rows}
    semaphore = asyncio.Semaphore(3)

    async def embed(text):
        async with semaphore:
            return await provider.embed(text)

    started = time.perf_counter()
    vectors = await asyncio.gather(*(embed(item["content"]) for item in corpus.values()))
    document_vectors = dict(zip(corpus, vectors, strict=True))
    corpus_embedding_ms = (time.perf_counter() - started) * 1000

    # The same vector is shared by all profiles for each query.
    async def query(row):
        async with semaphore:
            started = time.perf_counter()
            query_vector = await provider.embed(row["query"])
            embedding_ms = (time.perf_counter() - started) * 1000
            candidates = [
                {
                    "id": key,
                    "document_id": key,
                    "filename": item["filename"],
                    "text": item["content"],
                    "raw_score": cosine(query_vector, document_vectors[key]),
                }
                for key, item in sorted(corpus.items())
            ]
            vector = sorted(candidates, key=lambda item: item["raw_score"], reverse=True)[:30]
            lexical = sorted(
                candidates,
                key=lambda item: _score(row["query"], item["filename"]) * 4 + _score(row["query"], item["text"]),
                reverse=True,
            )
            lexical = [
                dict(item, raw_score=_score(row["query"], item["filename"]) * 4 + _score(row["query"], item["text"]))
                for item in lexical
                if _score(row["query"], item["filename"]) * 4 + _score(row["query"], item["text"]) > 0
            ][:30]
            hybrid = _fuse_ranked([("lexical", 1.0, lexical), ("cosine", 1.3, vector)], "id", 30)
            rerank_start = time.perf_counter()
            reranked = await provider.rerank(row["query"], hybrid, top_n=30)
            rerank_ms = (time.perf_counter() - rerank_start) * 1000
            relevant = set(row.get("relevant_document_keys", [row["document_key"]]))
            return {
                "eval_id": row["eval_id"],
                "category": row["difficulty"],
                "relevant_ids": sorted(relevant),
                "query_embedding_ms": embedding_ms,
                "rerank_ms": rerank_ms,
                "profiles": {
                    name: {
                        **retrieval_metrics([item["id"] for item in ranking], relevant, 10),
                        "ranked_document_ids": [item["id"] for item in ranking],
                    }
                    for name, ranking in [("pure_vector", vector), ("hybrid", hybrid), ("hybrid_rerank", reranked)]
                },
            }

    results = []

    async def recorded(row):
        try:
            result = await query(row)
            result["error"] = None
        except Exception as exc:
            result = {"eval_id": row["eval_id"], "error": type(exc).__name__}
        results.append(result)
        (output / "predictions.jsonl").write_text(
            "\n".join(
                json.dumps(item, ensure_ascii=False) for item in sorted(results, key=lambda item: item["eval_id"])
            )
            + "\n",
            encoding="utf-8",
        )

    await asyncio.gather(*(recorded(row) for row in rows))
    completed = [item for item in results if item["error"] is None]
    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset": "frozen_difficult_retrieval_v3",
        "dataset_sha256": digest,
        "code_sha256": code_digest(),
        "dataset_kind": "synthetic_developer_fixture",
        "backend": "in_memory_exact_cosine_plus_existing_lexical_rrf",
        "embedding_model": provider.embedding_model,
        "embedding_dimensions": len(vectors[0]),
        "reranker_model": settings.RERANKER_MODEL,
        "rrf_weights": {"lexical": 1, "vector": 1.3},
        "rrf_k": 60,
        "corpus_documents": len(corpus),
        "queries": len(rows),
        "completed": len(completed),
        "failures": len(rows) - len(completed),
        "corpus_embedding_ms": corpus_embedding_ms,
        "candidate_budget": 30,
        "profiles": {},
        "query_embedding_ms": latency_summary([item["query_embedding_ms"] for item in completed]),
        "rerank_ms": latency_summary([item["rerank_ms"] for item in completed]),
        "limitations": [
            "Real models on synthetic data; not historical internal resume data",
            "In-memory exact cosine is not a PostgreSQL/pgvector acceptance test",
            "30 candidate documents equal the entire small corpus; reranker recall ceiling is favorable",
            "No unanswerable queries; no held-out generalization or production performance claim",
            "Paired profiles reuse each query embedding; timing components reported separately",
        ],
    }
    for name in ("pure_vector", "hybrid", "hybrid_rerank"):
        summary["profiles"][name] = {
            metric: statistics.mean(item["profiles"][name][metric] for item in completed) if completed else None
            for metric in ("recall_at_10", "rr_at_10")
        }
        summary["profiles"][name]["mrr_at_10"] = summary["profiles"][name].pop("rr_at_10")
    base = summary["profiles"]["pure_vector"]["mrr_at_10"]
    revised = summary["profiles"]["hybrid_rerank"]["mrr_at_10"]
    summary["mrr_relative_improvement"] = revised / base - 1 if base and revised is not None else None
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary["failures"]:
        raise SystemExit(1)


if __name__ == "__main__":
    output = (
        ROOT
        / "data/eval/results/offline_retrieval_v1"
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
        }
    )
    try:
        asyncio.run(run(output))
    except Exception as exc:
        (output / "failure.json").write_text(
            json.dumps({"error": type(exc).__name__, "at": datetime.now(UTC).isoformat()}), encoding="utf-8"
        )
        print(json.dumps({"status": "failed", "error": type(exc).__name__}))
        raise SystemExit(1) from None
