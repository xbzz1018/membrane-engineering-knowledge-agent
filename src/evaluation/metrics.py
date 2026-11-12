from __future__ import annotations

import math
import statistics
from collections.abc import Iterable
from typing import Any


def percentile(values: list[float], ratio: float) -> float:
    """Nearest-rank percentile: sorted[ceil(p*n)-1], including n=1."""
    if not values or not 0 < ratio <= 1:
        raise ValueError("non-empty observations and 0 < ratio <= 1 required")
    return sorted(values)[math.ceil(ratio * len(values)) - 1]


def latency_summary(values: list[float]) -> dict:
    if not values:
        return {"n": 0}
    return {
        "n": len(values),
        "min": min(values),
        "max": max(values),
        "p50": statistics.median(values),
        "p95": percentile(values, 0.95),
        "percentile_method": "nearest_rank",
        "small_sample": len(values) < 20,
    }


def binary_metrics(pairs: Iterable[tuple[bool, bool]]) -> dict:
    pairs = list(pairs)
    tp = sum(expected and predicted for expected, predicted in pairs)
    fp = sum(not expected and predicted for expected, predicted in pairs)
    fn = sum(expected and not predicted for expected, predicted in pairs)
    tn = sum(not expected and not predicted for expected, predicted in pairs)
    return {
        "n": len(pairs),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": tp / (tp + fp) if tp + fp else None,
        "recall": tp / (tp + fn) if tp + fn else None,
        "specificity": tn / (tn + fp) if tn + fp else None,
        "f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None,
        "accuracy": (tp + tn) / len(pairs) if pairs else None,
    }


def document_key(row: dict[str, Any]) -> str:
    return str(row.get("document_id") or str(row.get("source_id", "")).split(":", 1)[0])


def unique_documents(rows: Iterable[dict[str, Any]]) -> list[str]:
    return list(dict.fromkeys(key for row in rows if (key := document_key(row))))


def retrieval_metrics(ranked_ids: list[str], relevant_ids: set[str], k: int = 10) -> dict:
    if not relevant_ids or k < 1:
        raise ValueError("at least one relevant document and k >= 1 required")
    top = list(dict.fromkeys(ranked_ids))[:k]
    hits = relevant_ids.intersection(top)
    ranks = [rank for rank, item in enumerate(top, 1) if item in relevant_ids]
    return {
        f"recall_at_{k}": len(hits) / len(relevant_ids),
        f"hit_at_{k}": float(bool(hits)),
        f"rr_at_{k}": 1 / min(ranks) if ranks else 0.0,
        "relevant_count": len(relevant_ids),
        "returned_unique_documents": len(top),
    }
