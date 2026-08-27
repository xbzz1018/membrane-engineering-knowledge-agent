"""Collect factual membrane specifications from an official public datasheet."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pymupdf

SOURCE_URL = "https://www.birdair.com/files/specifications/GB_Precontraint_Carte_502.pdf"
LICENSE_NOTE = (
    "Public manufacturer datasheet; factual technical values only. "
    "Copyright remains with Serge Ferrari; verify the current datasheet before engineering use."
)


def _record_sha256(record: dict) -> str:
    payload = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def parse_datasheet(content: bytes, retrieved_at: str) -> list[dict]:
    document = pymupdf.open(stream=content, filetype="pdf")
    text = "\n".join(page.get_text("text") for page in document)
    optical_rows = re.findall(
        r"(?m)^(502-\d{4})\s*\n(\d+(?:\.\d+)?)\s*\n(\d+(?:\.\d+)?)\s*\n(\d+(?:\.\d+)?)\s*$",
        text,
    )
    if len(optical_rows) != 40:
        raise ValueError(f"Expected 40 Precontraint 502 references, parsed {len(optical_rows)}")
    source_sha256 = hashlib.sha256(content).hexdigest()
    rows = []
    for reference, transmission, reflection, absorption in optical_rows:
        rows.append({
            "spec_id": f"public-precontraint-{reference.lower()}",
            "manufacturer": "Serge Ferrari",
            "material": "PVC/PVDF-coated polyester",
            "product_family": "Precontraint 502",
            "product_reference": reference,
            "specification": f"Precontraint 502 colour reference {reference}",
            "weight_g_m2": 590,
            "solar_transmittance_pct": float(transmission),
            "solar_reflectance_pct": float(reflection),
            "solar_absorptance_pct": float(absorption),
            "application": "solar protection, awnings, shade sails and light structures",
            "source_url": SOURCE_URL,
            "source_type": "manufacturer_datasheet",
            "source_version": "Technical features 2024",
            "license": LICENSE_NOTE,
            "retrieved_at": retrieved_at,
            "source_sha256": source_sha256,
            "synthetic": False,
        })
    return rows


def _enrich_synthetic(rows: list[dict]) -> list[dict]:
    enriched = []
    for original in rows:
        if not original.get("synthetic"):
            continue
        row = {
            **original,
            "license": original.get("license") or "Project-generated synthetic fixture; repository LICENSE applies.",
            "retrieved_at": original.get("retrieved_at") or "2026-08-27T00:00:00+00:00",
        }
        row["source_sha256"] = original.get("source_sha256") or _record_sha256(row)
        enriched.append(row)
    return enriched


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("data/processed/material_specs.jsonl"))
    args = parser.parse_args()
    existing = []
    if args.output.exists():
        existing = [json.loads(line) for line in args.output.read_text(encoding="utf-8").splitlines() if line]
    response = httpx.get(SOURCE_URL, follow_redirects=True, timeout=60)
    response.raise_for_status()
    retrieved_at = datetime.now(UTC).isoformat()
    rows = parse_datasheet(response.content, retrieved_at) + _enrich_synthetic(existing)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )
    print(f"public_specs=40 total={len(rows)} output={args.output}")


if __name__ == "__main__":
    main()
