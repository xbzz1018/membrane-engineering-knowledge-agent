"""Pinned public PDF parsing smoke; preserves failures, pages, hashes and Markdown."""

import argparse
import asyncio
import hashlib
import json
import os
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


async def run(args):
    from src.documents.parsing import parse_document
    from src.documents.representations import document_markdown

    folder = ROOT / "data/runtime/public-references"
    folder.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((ROOT / "data/manifests/public-references-v1.json").read_text(encoding="utf-8"))
    rows = []
    for source in manifest["sources"]:
        record = {"id": source["id"], "passed": False}
        try:
            path = folder / (source["id"] + ".pdf")
            if args.download:
                with urllib.request.urlopen(source["source_url"], timeout=45) as response:
                    data = response.read(20_000_001)
                if len(data) > 20_000_000 or not data.startswith(b"%PDF"):
                    raise ValueError("Invalid public PDF")
                path.write_bytes(data)
            if hashlib.sha256(path.read_bytes()).hexdigest() != source["sha256"]:
                raise ValueError("Public source changed; inspect before updating the manifest")
            chunks, parser = await parse_document(str(path), "text")
            pages = {}
            for chunk in chunks:
                page = str(chunk["page_number"])
                pages[page] = pages.get(page, "") + "\n" + chunk["text"]
            checks = {f"page_{page}_literal_{index}": literal in pages.get(page, "")
                      for page, literals in source["expected_page_literals"].items()
                      for index, literal in enumerate(literals)}
            checks["page_count"] = len(pages) == source["pages"]
            for chunk in chunks:
                chunk["id"] = f"{source['id']}:{chunk['chunk_index']}"
            document = {"id": source["id"], "filename": path.name, "version": 1,
                        "sha256": source["sha256"], "parser": parser}
            md = folder / (source["id"] + ".md")
            md.write_text(document_markdown(document, chunks), encoding="utf-8")
            record.update(passed=all(checks.values()), checks=checks, parser=parser,
                          chunks=len(chunks), source_sha256=source["sha256"], markdown=md.name)
        except Exception as exc:
            record["error_type"] = type(exc).__name__
        rows.append(record)
    summary = {"validated_at": datetime.now(UTC).isoformat(), "parser_mode": args.parser,
               "scope": "Two public archived PDFs; parsing/page/Markdown smoke only, not retrieval or review accuracy",
               "held_out_quality_test": False, "sources": rows, "passed": all(row["passed"] for row in rows)}
    (folder / f"validation-{args.parser}.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not summary["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--parser", choices=["basic", "mineru"], default="basic")
    args = parser.parse_args()
    os.environ.update(RUNTIME_MODE="local", MODEL_MODE="fake", PARSER_MODE=args.parser)
    asyncio.run(run(args))
