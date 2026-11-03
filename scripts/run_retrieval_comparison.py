"""Full/API retrieval comparison on an isolated project; synthetic v3 corpus."""

from __future__ import annotations

import asyncio
import hashlib
import json
import statistics
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.run_business_eval import code_digest
from src.core.config import get_settings
from src.documents.parsing import parse_document
from src.evaluation.metrics import latency_summary, retrieval_metrics, unique_documents
from src.infrastructure.database import storage
from src.infrastructure.full_backends import get_full_backends
from src.infrastructure.retrieval import RetrievalService
from src.main import app

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "data/eval/frozen_difficult_retrieval_v3.jsonl"
CANDIDATE_LIMIT = 30


def load_frozen() -> tuple[list[dict], str]:
    content = DATASET.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    if digest != DATASET.with_suffix(".sha256").read_text(encoding="ascii").split()[0]:
        raise RuntimeError("Retrieval dataset SHA mismatch")
    rows = [json.loads(line) for line in content.decode("utf-8").splitlines() if line]
    if len(rows) != 60 or len({row["eval_id"] for row in rows}) != len(rows):
        raise ValueError("60 unique evaluation IDs required")
    return rows, digest


async def ensure_documents(rows: list[dict], project_id: str) -> dict[str, str]:
    settings = get_settings()
    ids = {}
    unique = {row["document_key"]: row for row in rows}
    for key, item in unique.items():
        document = await storage.add_document(
            item["filename"],
            "text/plain",
            item["content"].encode(),
            "pending",
            tenant_id=settings.DEFAULT_TENANT_ID,
            project_id=project_id,
            data_classification="public",
            parse_method="text",
            version=item["business_version"],
        )
        ids[key] = document["id"]
        if not await storage.acquire_document_ingest(document["id"]):
            raise RuntimeError("Fresh evaluation document was not acquired")
        chunks, parser = await parse_document(str(await storage.resolve_document_path(document)), "text")
        await storage.save_chunks(document["id"], chunks, parser)
    return ids


async def main():
    settings = get_settings()
    if settings.RUNTIME_MODE.lower() != "full" or settings.MODEL_MODE.lower() != "api" or not settings.RERANKER_ENABLED:
        raise RuntimeError("Requires Full/API, real embeddings and enabled neural reranker; no Fake fallback")
    rows, digest = load_frozen()
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    output = ROOT / "data/eval/results/retrieval_v4" / run_id
    output.mkdir(parents=True)
    observations = []
    async with app.router.lifespan_context(app):
        project = await storage.create_project(f"eval-retrieval-{run_id}", settings.DEFAULT_TENANT_ID)
        project_id = project["id"]
        ids = await ensure_documents(rows, project_id)
        backends = get_full_backends()
        retrieval = RetrievalService()
        for row in rows:
            relevant = {ids[key] for key in row.get("relevant_document_keys", [row["document_key"]])}
            item = {
                "eval_id": row["eval_id"],
                "category": row["difficulty"],
                "relevant_ids": sorted(relevant),
                "profiles": {},
            }
            for profile in ("pure_vector", "hybrid", "hybrid_rerank"):
                started = time.perf_counter()
                record = {}
                try:
                    if profile == "pure_vector":
                        candidates = await backends.search_documents(
                            row["query"], limit=CANDIDATE_LIMIT, project_id=project_id
                        )
                    elif profile == "hybrid":
                        candidates = await storage.search_chunks(
                            row["query"],
                            limit=CANDIDATE_LIMIT,
                            project_id=project_id,
                            tenant_id=settings.DEFAULT_TENANT_ID,
                            classifications={"public"},
                        )
                    else:
                        packet = await retrieval.retrieve(
                            row["query"],
                            project_id,
                            tenant_id=settings.DEFAULT_TENANT_ID,
                            classifications={"public"},
                            channels={"documents"},
                            limit=CANDIDATE_LIMIT,
                        )
                        candidates = packet.sources
                    ranked = unique_documents(candidates)
                    record.update(retrieval_metrics(ranked, relevant, 10))
                    record.update(
                        {"ranked_document_ids": ranked, "candidate_chunk_count": len(candidates), "error": None}
                    )
                except Exception as exc:
                    record["error"] = type(exc).__name__
                record["latency_ms"] = (time.perf_counter() - started) * 1000
                item["profiles"][profile] = record
            observations.append(item)
            (output / "predictions.jsonl").write_text(
                "\n".join(json.dumps(item, ensure_ascii=False) for item in observations) + "\n", encoding="utf-8"
            )
    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset": "frozen_difficult_retrieval_v3",
        "dataset_kind": "synthetic_30_documents_60_answerable_queries",
        "dataset_sha256": digest,
        "code_sha256": code_digest(),
        "project_id": project_id,
        "rows": len(rows),
        "corpus_documents": len(ids),
        "candidate_chunks_per_profile": CANDIDATE_LIMIT,
        "ranking_unit": "unique_document_best_chunk_position_then_top10",
        "aggregation": "macro_over_queries",
        "embedding_model": settings.EMBEDDING_MODEL,
        "reranker_model": settings.RERANKER_MODEL,
        "profiles": {},
        "limitations": [
            "Not the historical internal resume set",
            "No unanswerable queries in v3",
            "Small synthetic corpus; no production quality inference",
            "Failed queries retained; quality scores are completed-only",
        ],
    }
    for profile in ("pure_vector", "hybrid", "hybrid_rerank"):
        records = [item["profiles"][profile] for item in observations]
        completed = [item for item in records if item["error"] is None]
        summary["profiles"][profile] = {
            "n": len(records),
            "failures": len(records) - len(completed),
            "recall_at_10": statistics.mean(item["recall_at_10"] for item in completed) if completed else None,
            "mrr_at_10": statistics.mean(item["rr_at_10"] for item in completed) if completed else None,
            "latency_ms": latency_summary([item["latency_ms"] for item in records]),
        }
    base = summary["profiles"]["pure_vector"]["mrr_at_10"]
    revised = summary["profiles"]["hybrid_rerank"]["mrr_at_10"]
    summary["mrr_relative_improvement"] = revised / base - 1 if base and revised is not None else None
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if any(profile["failures"] for profile in summary["profiles"].values()):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
