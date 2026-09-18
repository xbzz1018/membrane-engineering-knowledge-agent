"""Build a dataset-level source manifest without storing public source documents."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "manifests" / "sources.csv"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _first(path: Path) -> dict:
    return json.loads(next(line for line in path.read_text(encoding="utf-8").splitlines() if line))


def main() -> None:
    processed = ROOT / "data" / "processed"
    documents = ROOT / "data" / "manifests" / "document_fixtures.jsonl"
    groups = [
        ("synthetic_cases", "synthetic_cases.jsonl", "commit generated JSONL with synthetic=true"),
        ("public_cases", "public_cases.jsonl", "store metadata and source links only"),
        ("material_specs", "material_specs.jsonl", "store factual fields; do not commit manufacturer PDF"),
        ("price_records", "price_records.jsonl", "synthetic scenarios only; never a market quotation"),
    ]
    rows = []
    for group, filename, policy in groups:
        path = processed / filename
        first = _first(path)
        rows.append({
            "record_group": group,
            "source_type": first["source_type"],
            "source_url": first["source_url"],
            "license_note": first["license"],
            "retrieved_at": first["retrieved_at"],
            "dataset_sha256": _sha(path),
            "local_policy": policy,
        })
    case_fixtures = ROOT / "data" / "fixtures" / "cases.jsonl"
    first_case_fixture = _first(case_fixtures)
    rows.append({
        "record_group": "fixture_cases",
        "source_type": first_case_fixture["source_type"],
        "source_url": first_case_fixture["source_url"],
        "license_note": first_case_fixture["license"],
        "retrieved_at": first_case_fixture["retrieved_at"],
        "dataset_sha256": _sha(case_fixtures),
        "local_policy": "commit small fixture outside the business case catalog",
    })
    first_document = _first(documents)
    rows.append({
        "record_group": "document_fixtures",
        "source_type": first_document["source_type"],
        "source_url": "synthetic://document-fixtures",
        "license_note": first_document["license"],
        "retrieved_at": first_document["retrieved_at"],
        "dataset_sha256": _sha(documents),
        "local_policy": "commit deterministic synthetic PDF/DOCX/XLSX fixtures",
    })
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(f"sources={len(rows)} output={OUTPUT}")


if __name__ == "__main__":
    main()
