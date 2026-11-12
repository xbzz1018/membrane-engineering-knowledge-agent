"""Reproducible public PDF parser smoke check, independent of any LLM score."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SOURCE_URL = "https://www.birdair.com/files/specifications/GB_Precontraint_Carte_502.pdf"
EXPECTED_SHA = "2bf019cd06543dd9fecc6ef61e4f9da14fc78fb77500786d0d0055a87f5210bc"


async def run(args):
    from src.documents.parsing import parse_document

    folder = ROOT / "data/runtime/public-source-smoke"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "precontraint-502.pdf"
    if args.download:
        import httpx

        async with httpx.AsyncClient(timeout=45, follow_redirects=True) as client:
            response = await client.get(SOURCE_URL)
            response.raise_for_status()
        path.write_bytes(response.content)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != EXPECTED_SHA:
        raise ValueError("Public source changed; inspect new source and relabel before evaluation")
    chunks, parser = await parse_document(str(path), "text")
    pages = {}
    for item in chunks:
        page = int(item.get("page_number", 1))
        pages[page] = pages.get(page, "") + "\n" + item["text"]
    p3 = pages.get(3, "")
    p7 = pages.get(7, "")
    checks = {
        "seven_pages": len(pages) == 7,
        "p3_colour_502_1013_solar_10_61_29": bool(re.search(r"502-1013\s+10\s+61\s+29", p3)),
        "p7_weight_590_g_sqm": bool(re.search(r"Weight\s+590\s+g/sqm", p7)),
        "p7_tensile_250_250": bool(re.search(r"Tensile strength.*?250/250", p7, re.S)),
        "p7_tolerance_retained": "+/- 5%" in p7,
        "coating_protection_not_total_thickness": "160 µm - Protection area" in p3,
    }
    result = {
        "validated_at": datetime.now(UTC).isoformat(),
        "source_url": SOURCE_URL,
        "source_sha256": digest,
        "source_is_public": True,
        "source_kind": "manufacturer_datasheet_archived_snapshot",
        "content_version_note": "PDF contains multiple date/version markings; no current-spec claim",
        "parser": parser,
        "chunks": len(chunks),
        "page_count": len(pages),
        "checks": checks,
        "passed": all(checks.values()),
        "llm_used": False,
        "limitations": [
            "One text-based PDF; no scanned OCR, no MinerU claim in basic mode",
            "Table sequence checks do not prove layout-aware extraction for arbitrary PDFs",
            "160 micrometres describes coating protection area, not total membrane nominal thickness",
            "File retained only under ignored runtime directory; factual checks are small extracts",
        ],
    }
    (folder / f"{args.parser}-result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--parser", choices=["basic", "mineru"], default="basic")
    args = parser.parse_args()
    os.environ.update({"RUNTIME_MODE": "local", "MODEL_MODE": "fake", "PARSER_MODE": args.parser})
    asyncio.run(run(args))
