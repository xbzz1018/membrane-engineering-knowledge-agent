"""Frozen retrieval regression: exact filters, multiple relevant docs and no-answer."""

from __future__ import annotations

import argparse
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


def eligible(doc, filters):
    """Independent fixture oracle; never derive gold from system predictions."""
    if doc.get("scope", "target") != "target" or doc.get("classification", "public") != "public":
        return False
    meta = doc["metadata"]
    for key in ("engineering_model", "applicable_revision", "document_type"):
        if key in filters and meta[key] != filters[key]:
            return False
    if "upload_version" in filters and doc["upload_version"] != filters["upload_version"]:
        return False
    if "effective_on" in filters:
        day = filters["effective_on"]
        if not meta["effective_from"] or meta["effective_from"] > day:
            return False
        if meta["effective_to"] and meta["effective_to"] < day:
            return False
    return True


def aggregate(records):
    from src.evaluation.metrics import latency_summary

    completed = [r for r in records if r["error"] is None]
    answerable = [r for r in records if r["answerable"]]
    empty = [r for r in records if not r["answerable"]]
    return {
        "n": len(records), "completed": len(completed), "failures": len(records) - len(completed),
        "answerable_n": len(answerable), "no_answer_n": len(empty),
        "recall_at_10_all_answerable": statistics.mean(r.get("recall_at_10", 0) for r in answerable) if answerable else None,
        "mrr_at_10_all_answerable": statistics.mean(r.get("rr_at_10", 0) for r in answerable) if answerable else None,
        "no_answer_empty_return_rate_all": sum(r["error"] is None and not r["ranked_document_ids"] for r in empty) / len(empty) if empty else None,
        "hard_filter_violations": sum(len(r.get("violations", [])) for r in records),
        "latency_ms": latency_summary([r["latency_ms"] for r in records]),
    }


async def run(args, output):
    from scripts.run_business_eval import code_digest
    from src.core.config import get_settings
    from src.documents.parsing import parse_document
    from src.domain.document_search import DocumentBusinessMetadata, DocumentSearchFilters
    from src.evaluation.metrics import retrieval_metrics, unique_documents
    from src.infrastructure.database import storage
    from src.infrastructure.document_metadata import declare_metadata
    from src.main import app

    settings = get_settings()
    if args.mode == "full-api" and (settings.RUNTIME_MODE != "full" or settings.MODEL_MODE != "api" or not settings.RERANKER_ENABLED):
        raise ValueError("Full/API with real embedding and enabled reranker required; no fallback")
    raw = (ROOT / "data/eval/retrieval_business_v1.json").read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != (ROOT / "data/eval/retrieval_business_v1.sha256").read_text().strip():
        raise ValueError("Frozen dataset hash mismatch")
    dataset = json.loads(raw)
    corpus = {doc["key"]: doc for doc in dataset["documents"]}
    if len(corpus) != len(dataset["documents"]) or len({r["eval_id"] for r in dataset["queries"]}) != len(dataset["queries"]):
        raise ValueError("Duplicate fixture identity")
    for row in dataset["queries"]:
        for key in row["relevant_document_keys"]:
            if key not in corpus or not eligible(corpus[key], row["filters"]):
                raise ValueError("Gold violates fixture scope or explicit filters")
    source = code_digest()
    profiles = ["lexical"] if args.mode == "local-contract" else ["lexical", "pure_vector", "hybrid", "hybrid_rerank"]
    summary = {"mode": args.mode, "dataset_sha256": digest, "dataset_kind": dataset["dataset_kind"],
               "contextual_retrieval_enabled": settings.CONTEXTUAL_RETRIEVAL_ENABLED,
               "contextual_version": "metadata-v1" if settings.CONTEXTUAL_RETRIEVAL_ENABLED else None,
               "not_a_held_out_test": True, "code_sha256_at_start": source,
               "candidate_budget": 30, "ranking_unit": "unique_document_best_chunk_position_top10",
               "limitations": dataset["limitations"] + (["Local SQLite lexical contract only; no vector/RRF/neural quality claim"] if args.mode == "local-contract" else []),
               "profiles": {}}
    observations = []
    try:
        async with app.router.lifespan_context(app):
            project = await storage.create_project("retrieval-" + output.name, settings.DEFAULT_TENANT_ID)
            other = await storage.create_project("trap-" + output.name, settings.DEFAULT_TENANT_ID)
            ids = {}
            for doc in corpus.values():
                uploaded = await storage.add_document(doc["filename"], "text/plain", doc["content"].encode(), "pending",
                    project_id=project["id"] if doc.get("scope", "target") == "target" else other["id"],
                    tenant_id=settings.DEFAULT_TENANT_ID, data_classification="public",
                    version=doc["upload_version"])
                did = uploaded["id"]
                ids[doc["key"]] = did
                await storage.acquire_document_ingest(did)
                chunks, parser = await parse_document(str(await storage.resolve_document_path(uploaded)), "text")
                await storage.save_chunks(did, chunks, parser)
                if doc.get("classification") == "internal":
                    # All fixture bodies are public synthetic data. Simulate a later
                    # classification change, testing authoritative filtering over stale indexes.
                    from src.infrastructure.database import documents

                    async with storage.session_factory() as session:
                        await session.execute(documents.update().where(documents.c.id == did).values(data_classification="internal"))
                        await session.commit()
                current = await storage.get_document(did)
                await declare_metadata(storage, did, DocumentBusinessMetadata(**doc["metadata"],
                    source_note="SYNTHETIC developer metadata declaration", expected_lock_version=current["lock_version"]), "evaluation")
            reverse = {value: key for key, value in ids.items()}
            summary.update(project_id=project["id"], corpus_documents=len(ids), queries=len(dataset["queries"]))
            for row in dataset["queries"]:
                filters = DocumentSearchFilters.model_validate(row["filters"])
                relevant = {ids[key] for key in row["relevant_document_keys"]}
                item = {**row, "profiles": {}}
                scope = {"project_id": project["id"], "tenant_id": settings.DEFAULT_TENANT_ID,
                         "classifications": {"public"}, "filters": filters}
                for profile in profiles:
                    started = time.perf_counter()
                    record = {"answerable": bool(relevant), "error": None, "ranked_document_ids": []}
                    try:
                        if profile == "pure_vector" and row["query"].strip():
                            from src.infrastructure.full_backends import get_full_backends
                            rows = await get_full_backends().search_documents(row["query"], limit=30, **scope)
                        else:
                            rows = await storage.search_chunks(row["query"], limit=30, lexical_only=(profile == "lexical"), **scope)
                            if profile == "hybrid_rerank" and row["query"].strip():
                                from src.infrastructure.model_provider import get_model_provider
                                rows = await get_model_provider().rerank(row["query"], rows, top_n=30)
                        ranked = unique_documents(rows)
                        record.update(ranked_document_ids=ranked,
                                      ranked_document_keys=[reverse[did] for did in ranked],
                                      violations=[reverse[did] for did in ranked if not eligible(corpus[reverse[did]], row["filters"])])
                        if relevant:
                            record.update(retrieval_metrics(ranked, relevant, 10))
                    except Exception as exc:
                        record["error"] = type(exc).__name__
                    record["latency_ms"] = (time.perf_counter() - started) * 1000
                    item["profiles"][profile] = record
                observations.append(item)
                with (output / "predictions.jsonl").open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(item, ensure_ascii=False) + "\n")
        for profile in profiles:
            summary["profiles"][profile] = aggregate([item["profiles"][profile] for item in observations])
            summary["profiles"][profile]["by_category"] = {category: aggregate([
                item["profiles"][profile] for item in observations if item["category"] == category
            ]) for category in sorted({item["category"] for item in observations})}
        summary["passed_contract"] = all(not r["failures"] and not r["hard_filter_violations"] for r in summary["profiles"].values())
    except Exception as exc:
        summary.update(passed_contract=False, setup_error=type(exc).__name__)
        raise
    finally:
        summary.update(generated_at=datetime.now(UTC).isoformat(), code_sha256_at_end=code_digest())
        summary["source_changed_during_run"] = source != summary["code_sha256_at_end"]
        (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not summary["passed_contract"]:
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["local-contract", "full-api"], default="local-contract")
    parser.add_argument("--contextual", choices=["off", "on"], default="off")
    args = parser.parse_args()
    os.environ["CONTEXTUAL_RETRIEVAL_ENABLED"] = "true" if args.contextual == "on" else "false"
    output = ROOT / "data/eval/results/retrieval_business_v1" / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8])
    output.mkdir(parents=True)
    if args.mode == "local-contract":
        os.environ.update(RUNTIME_MODE="local", MODEL_MODE="fake", MODEL_PROVIDER="fake", RERANKER_ENABLED="false",
            DATABASE_URL="", LOCAL_DB_PATH=str(output / "evaluation.db"), LOCAL_UPLOAD_PATH=str(output / "uploads"),
            TEMPORAL_ENABLED="false", AUTH_ENABLED="false", PARSER_MODE="basic")
    try:
        asyncio.run(run(args, output))
    except Exception as exc:
        (output / "failure.json").write_text(json.dumps({"mode": args.mode, "error_type": type(exc).__name__,
            "generated_at": datetime.now(UTC).isoformat()}, indent=2), encoding="utf-8")
        raise
