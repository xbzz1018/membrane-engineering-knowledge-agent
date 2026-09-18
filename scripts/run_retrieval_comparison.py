"""对比纯向量、混合检索和混合检索+Qwen3 Reranker。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core.config import get_settings
from src.documents.parsing import parse_document
from src.infrastructure.database import storage
from src.infrastructure.full_backends import get_full_backends
from src.infrastructure.retrieval import RetrievalService
from src.main import app

DATASET = Path("data/eval/frozen_difficult_retrieval_v3.jsonl")
RESULT = Path("data/eval/results/difficult_retrieval_v3.json")


def load_frozen() -> list[dict]:
    content = DATASET.read_bytes()
    expected = DATASET.with_suffix(".sha256").read_text(encoding="ascii").split()[0]
    if hashlib.sha256(content).hexdigest() != expected:
        raise RuntimeError("困难检索集SHA校验失败")
    rows = [json.loads(line) for line in content.decode("utf-8").splitlines() if line]
    if len(rows) != 60:
        raise RuntimeError(f"困难检索集必须为60条，当前{len(rows)}条")
    return rows


def rank_of_document(rows: list[dict], document_id: str) -> int | None:
    for rank, row in enumerate(rows, 1):
        if str(row.get("document_id", "")) == document_id or str(row.get("source_id", "")).startswith(
            f"{document_id}:"
        ):
            return rank
    return None


def metrics(ranks: list[int | None], latencies: list[float]) -> dict:
    ordered = sorted(latencies)
    return {
        "recall_at_10": round(sum(rank is not None and rank <= 10 for rank in ranks) / len(ranks), 4),
        "mrr": round(statistics.mean((1 / rank) if rank else 0 for rank in ranks), 4),
        "latency_ms": {
            "p50": round(statistics.median(ordered), 2),
            "p95": round(ordered[int(len(ordered) * 0.95) - 1], 2),
        },
    }


async def ensure_documents(rows: list[dict]) -> dict[str, str]:
    settings = get_settings()
    document_ids: dict[str, str] = {}
    unique = {row["document_key"]: row for row in rows}
    for key, item in unique.items():
        document = await storage.add_document(
            item["filename"],
            "text/plain",
            item["content"].encode(),
            "pending",
            tenant_id=settings.DEFAULT_TENANT_ID,
            project_id=settings.DEFAULT_PROJECT_ID,
            data_classification="public",
            parse_method="text",
            version=item["business_version"],
        )
        document_ids[key] = document["id"]
        if (
            document["status"] == "indexed"
            and document.get("embedding_model", "") == settings.EMBEDDING_MODEL
            and await storage.count_document_chunks(document["id"])
        ):
            continue
        if not await storage.acquire_document_ingest(document["id"], refresh_embedding=True):
            raise RuntimeError(f"评测资料无法取得索引处理权: {key}")
        local_path = await storage.resolve_document_path(document)
        chunks, parser = await parse_document(str(local_path), "text")
        await storage.save_chunks(document["id"], chunks, parser)
    return document_ids


async def main() -> None:
    settings = get_settings()
    if settings.RUNTIME_MODE.lower() != "full" or settings.MODEL_MODE.lower() != "api":
        raise RuntimeError("困难检索对照要求Full/API模式")
    if not settings.RERANKER_ENABLED:
        raise RuntimeError("困难检索对照要求启用Reranker")
    rows = load_frozen()
    pure_ranks: list[int | None] = []
    hybrid_ranks: list[int | None] = []
    rerank_ranks: list[int | None] = []
    pure_latency: list[float] = []
    hybrid_latency: list[float] = []
    rerank_latency: list[float] = []
    async with app.router.lifespan_context(app):
        document_ids = await ensure_documents(rows)
        backends = get_full_backends()
        retrieval = RetrievalService()
        for row in rows:
            expected_id = document_ids[row["document_key"]]

            started = time.perf_counter()
            pure = await backends.search_documents(row["query"], limit=10, project_id=settings.DEFAULT_PROJECT_ID)
            pure_latency.append((time.perf_counter() - started) * 1000)
            pure_ranks.append(rank_of_document(pure, expected_id))

            started = time.perf_counter()
            hybrid = await storage.search_chunks(row["query"], limit=10, project_id=settings.DEFAULT_PROJECT_ID)
            hybrid_latency.append((time.perf_counter() - started) * 1000)
            hybrid_ranks.append(rank_of_document(hybrid, expected_id))

            started = time.perf_counter()
            packet = await retrieval.retrieve(
                row["query"],
                settings.DEFAULT_PROJECT_ID,
                channels={"documents"},
                limit=10,
            )
            rerank_latency.append((time.perf_counter() - started) * 1000)
            rerank_ranks.append(rank_of_document(packet.sources, expected_id))

    summary = {
        "dataset": "frozen_difficult_retrieval_v3",
        "rows": len(rows),
        "generated_at": datetime.now(UTC).isoformat(),
        "pure_vector": metrics(pure_ranks, pure_latency),
        "hybrid": metrics(hybrid_ranks, hybrid_latency),
        "hybrid_qwen3_rerank": metrics(rerank_ranks, rerank_latency),
    }
    summary["recall_improvement_vs_vector"] = round(
        summary["hybrid_qwen3_rerank"]["recall_at_10"] - summary["pure_vector"]["recall_at_10"],
        4,
    )
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    if summary["recall_improvement_vs_vector"] < 0.05:
        raise AssertionError(json.dumps(summary, ensure_ascii=False))
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
