"""Isolated business regression via HTTP; optionally run configured public-data LLM."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import os
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def load_frozen(path: Path) -> tuple[list[dict], str]:
    content = path.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    expected = path.with_suffix(".sha256").read_text(encoding="ascii").split()[0]
    if digest != expected:
        raise ValueError("Dataset SHA mismatch")
    rows = [json.loads(line) for line in content.decode("utf-8").splitlines() if line]
    ids = [row["eval_id"] for row in rows]
    if len(ids) != len(set(ids)) or {row["expected_human_review"] for row in rows} != {True, False}:
        raise ValueError("Unique IDs and positive/negative examples required")
    return rows, digest


def code_digest() -> str:
    digest = hashlib.sha256()
    for folder in ("src", "scripts"):
        for path in sorted((ROOT / folder).rglob("*.py")):
            digest.update(path.relative_to(ROOT).as_posix().encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


async def run(args, run_dir: Path) -> dict:
    import httpx

    from src.agents.prompts import PROMPTS
    from src.core.config import get_settings
    from src.evaluation.business_checks import match_issues
    from src.evaluation.metrics import binary_metrics, latency_summary
    from src.infrastructure.model_provider import get_review_model_provider
    from src.main import app

    settings = get_settings()
    source_at_start = code_digest()
    provider_metadata = get_review_model_provider().metadata
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "code_sha256": source_at_start,
                "started_at": datetime.now(UTC).isoformat(),
                "model": provider_metadata,
                "config": {
                    key: getattr(settings, key)
                    for key in (
                        "MODEL_TEMPERATURE",
                        "MODEL_TIMEOUT_SECONDS",
                        "MODEL_CONTEXT_WINDOW",
                        "MODEL_MAX_TOKENS",
                        "REVIEW_MAX_TOKENS",
                        "REVIEW_SUPERVISOR_ENABLED",
                        "MODEL_RETRY_ATTEMPTS",
                        "REVIEW_MAX_EVIDENCE_UNITS",
                        "REVIEW_MAX_EVIDENCE_TOKENS",
                    )
                },
                "prompts": {name: {"version": spec.version, "sha256": spec.digest} for name, spec in PROMPTS.items()},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    rows, digest = load_frozen(ROOT / "data/eval/business_review_v1.jsonl")
    gold_path = ROOT / "data/eval/business_expectations_v2.json"
    gold_digest = hashlib.sha256(gold_path.read_bytes()).hexdigest()
    if gold_digest != gold_path.with_suffix(".sha256").read_text(encoding="ascii").split()[0]:
        raise ValueError("Issue expectation SHA mismatch")
    gold = json.loads(gold_path.read_text(encoding="utf-8"))["cases"]
    if args.eval_ids:
        selected = set(args.eval_ids.split(","))
        rows = [row for row in rows if row["eval_id"] in selected]
        if {row["eval_id"] for row in rows} != selected:
            raise ValueError("Unknown evaluation ID")
    if args.limit:
        rows = rows[: args.limit]
    if not rows:
        raise ValueError("No evaluation cases selected")
    results = []
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://eval", timeout=180) as client:
            # A fresh project *and* fresh DB/uploads prevent corpus contamination.
            created = await client.post("/api/v1/projects", json={"name": f"eval-{run_dir.name}"})
            created.raise_for_status()
            project_id = created.json()["id"]
            for row in rows:
                started = time.perf_counter()
                observation = {
                    "eval_id": row["eval_id"],
                    "category": row["category"],
                    "expected_human_review": row["expected_human_review"],
                    "error": None,
                }
                try:
                    document_ids = []
                    for doc in row["documents"]:
                        uploaded = await client.post(
                            "/api/v1/documents/upload",
                            data={"project_id": project_id, "data_classification": "public"},
                            files={"file": (f"{row['eval_id']}-{doc['filename']}", doc["text"].encode(), "text/plain")},
                        )
                        uploaded.raise_for_status()
                        doc_id = uploaded.json()["document_id"]
                        indexed = await client.post(f"/api/v1/documents/{doc_id}/index")
                        indexed.raise_for_status()
                        document_ids.append(doc_id)
                    response = await client.post(
                        "/api/v1/package-reviews",
                        json={
                            "project_id": project_id,
                            "document_ids": document_ids,
                            "question": row["question"],
                            "review_mode": "full",
                        },
                    )
                    response.raise_for_status()
                    payload = response.json()
                    known = {source["source_id"] for source in payload["sources"]}
                    factual = [
                        issue
                        for issue in payload["issues"]
                        if issue["issue_type"] not in {"missing_domain_evidence", "review_uncertainty"}
                    ]
                    citations_valid = all(
                        issue["evidence_ids"] and set(issue["evidence_ids"]) <= known for issue in factual
                    )
                    actual_types = {issue["issue_type"] for issue in payload["issues"]}
                    target_issues = [
                        issue for issue in payload["issues"] if issue["issue_type"] in row["expected_issue_types"]
                    ]
                    cited_docs = {eid.split(":", 1)[0] for issue in target_issues for eid in issue["evidence_ids"]}
                    expected_docs = {document_ids[i] for i in row["expected_evidence_documents"]}
                    predicted = payload["human_review_required"]
                    schema_valid = set(payload["worker_results"]) == {"design", "material", "price"}
                    issue_checks = match_issues(payload["issues"], gold[row["eval_id"]], document_ids)
                    observation.update(
                        {
                            "predicted_human_review": predicted,
                            "schema_valid": schema_valid,
                            "issue_checks": issue_checks,
                            "citations_valid": citations_valid,
                            "factual_issue_count": len(factual),
                            "expected_types_present": set(row["expected_issue_types"]) <= actual_types,
                            "expected_evidence_present": expected_docs <= cited_docs,
                            "actual_issue_types": sorted(actual_types),
                            "correct": predicted == row["expected_human_review"]
                            and set(row["expected_issue_types"]) <= actual_types
                            and expected_docs <= cited_docs
                            and citations_valid and schema_valid and issue_checks["strict_issue_pass"],
                            "document_ids": document_ids,
                            "response": payload,
                        }
                    )
                except Exception as exc:
                    observation.update({"correct": False, "error": type(exc).__name__})
                    if isinstance(exc, httpx.HTTPStatusError):
                        observation.update(
                            {"http_status": exc.response.status_code, "error_detail": exc.response.text[:800]}
                        )
                observation["latency_ms"] = (time.perf_counter() - started) * 1000
                results.append(observation)
                # Preserve failures/partial progress as they happen; no successful-run cache.
                (run_dir / "predictions.jsonl").write_text(
                    "\n".join(json.dumps(item, ensure_ascii=False) for item in results) + "\n", encoding="utf-8"
                )
    completed = [item for item in results if item["error"] is None]
    pairs = [(item["expected_human_review"], item["predicted_human_review"]) for item in completed]
    summary = {
        "run_id": run_dir.name,
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset": "business_review_v1",
        "protocol": "business_review_v2",
        "issue_gold_sha256": gold_digest,
        "dataset_sha256": digest,
        "code_sha256": source_at_start,
        "source_changed_during_run": code_digest() != source_at_start,
        "dataset_kind": "hand_authored_synthetic_regression_used_during_development",
        "not_a_held_out_test": True,
        "mode": args.mode,
        "review_date_utc": datetime.now(UTC).date().isoformat(),
        "storage": "isolated_sqlite",
        "project_id": project_id,
        "model": provider_metadata,
        "runtime": {name: importlib.metadata.version(name) for name in ["langchain", "langchain-core", "pydantic"]},
        "n": len(results),
        "completed": len(completed),
        "failures": len(results) - len(completed),
        "strict_issue_counts_completed_only": {
            key: sum(item["issue_checks"][key] for item in completed) for key in ("tp", "fp", "fn")
        },
        "end_to_end_case_accuracy": sum(item["correct"] for item in results) / len(results),
        "human_review_detection_completed_only": binary_metrics(pairs),
        "issue_type_and_evidence_pass_count": sum(item["correct"] for item in results),
        "latency_ms_including_ingestion": latency_summary([item["latency_ms"] for item in results]),
        "by_category": {
            category: {
                "n": sum(item["category"] == category for item in results),
                "passed": sum(item["category"] == category and item["correct"] for item in results),
            }
            for category in sorted({item["category"] for item in results})
        },
        "limitations": [
            "Synthetic developer regression; no generalization claim",
            "Fake mode checks rules and tool orchestration, not LLM semantics",
            "No pgvector/reranker/Temporal/MinerU quality claim",
            "Valid citation ID is not proof of semantic support; no judge score is fabricated",
        ],
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["fake", "api"], default="fake")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--eval-ids", default="")
    args = parser.parse_args()
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    run_dir = ROOT / "data/eval/results/business_review_v2" / run_id
    run_dir.mkdir(parents=True)
    os.environ.update(
        {
            "RUNTIME_MODE": "local",
            "MODEL_MODE": args.mode,
            "DATABASE_URL": "",
            "LOCAL_DB_PATH": str(run_dir / "eval.db"),
            "LOCAL_UPLOAD_PATH": str(run_dir / "uploads"),
            "PARSER_MODE": "basic",
            "TEMPORAL_ENABLED": "false",
            "AUTH_ENABLED": "false",
            "RERANKER_ENABLED": "false",
        }
    )
    if args.mode == "fake":
        os.environ["MODEL_PROVIDER"] = "fake"
    summary = asyncio.run(run(args, run_dir))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary["end_to_end_case_accuracy"] < 1:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
