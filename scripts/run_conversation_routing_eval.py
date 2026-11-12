"""Development intent corpus only; never relabel as historical internship data."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import uuid
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from src.agents.conversation_supervisor import SupervisorRouter
from src.core.config import Settings
from src.infrastructure.model_provider import ModelProvider, get_role_model_provider


def code_digest() -> str:
    digest = hashlib.sha256()
    root = Path(__file__).resolve().parents[1]
    for folder in ("src", "scripts"):
        for path in sorted((root / folder).rglob("*.py")):
            digest.update(path.relative_to(root).as_posix().encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


async def run(mode: str, dataset: Path, output: Path) -> dict:
    source_at_start = code_digest()
    raw = dataset.read_bytes()
    samples = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
    if len({item["id"] for item in samples}) != len(samples):
        raise ValueError("duplicate sample IDs")
    if mode == "rules":
        settings = Settings(_env_file=None, RUNTIME_MODE="local", MODEL_MODE="fake", ROLE_MODEL_ROUTING_ENABLED=False)
        provider = ModelProvider(settings)
    else:
        settings = Settings()
        if settings.MODEL_MODE != "api":
            raise ValueError("--mode api requires explicit MODEL_MODE=api; no Fake fallback")
        provider = get_role_model_provider("supervisor", settings)
    router = SupervisorRouter(provider)
    predictions = []
    for sample in samples:
        record = {"id": sample["id"], "expected_intent": sample["intent"], "expected_mode": sample["execution_mode"]}
        try:
            decision, source, usage = await router.route(sample["message"], sample.get("history", []))
            record.update(
                intent=decision.intent, execution_mode=decision.execution_mode, decision_source=source, usage=usage,
                correct=decision.intent == sample["intent"] and decision.execution_mode == sample["execution_mode"],
            )
        except Exception as exc:
            record.update(correct=False, error_type=type(exc).__name__)
        predictions.append(record)
    correct = sum(item["correct"] for item in predictions)
    summary = {
        "mode": mode, "provider": provider.metadata, "dataset_sha256": hashlib.sha256(raw).hexdigest(),
        "dataset_kind": "hand_authored_development_cases", "not_a_held_out_test": True,
        "n": len(samples), "correct": correct,
        "joint_intent_execution_accuracy": correct / len(samples) if samples else None,
        "errors": sum("error_type" in item for item in predictions),
        "confusion": dict(Counter(f"{item['expected_intent']}->{item.get('intent', 'ERROR')}" for item in predictions)),
        "failed_ids": [item["id"] for item in predictions if not item["correct"]],
        "scope": "routing decisions only, not answer correctness or retrieval quality",
        "code_sha256_at_start": source_at_start, "code_sha256_at_end": code_digest(),
    }
    summary["source_changed_during_run"] = summary["code_sha256_at_start"] != summary["code_sha256_at_end"]
    output.mkdir(parents=True, exist_ok=False)
    (output / "predictions.jsonl").write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in predictions), encoding="utf-8",
    )
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("rules", "api"), default="rules")
    parser.add_argument("--dataset", type=Path, default=Path("data/eval/conversation_routes_v1.jsonl"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    output = args.output or Path("data/eval/results/conversation_routes_v1") / run_id
    print(json.dumps(asyncio.run(run(args.mode, args.dataset, output)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
