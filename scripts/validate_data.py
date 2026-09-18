from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _validate_provenance(row: dict, record_id: str, errors: list[str]) -> None:
    for field in ("source_url", "license", "retrieved_at", "source_sha256"):
        if not row.get(field):
            errors.append(f"record {record_id} missing {field}")
    digest = str(row.get("source_sha256", ""))
    if digest and not re.fullmatch(r"[0-9a-f]{64}", digest):
        errors.append(f"record {record_id} invalid source_sha256")


def validate() -> int:
    root = ROOT / "data" / "processed"
    public = read_jsonl(root / "public_cases.jsonl")
    synthetic = read_jsonl(root / "synthetic_cases.jsonl")
    fixtures = read_jsonl(ROOT / "data" / "fixtures" / "cases.jsonl")
    specs = read_jsonl(root / "material_specs.jsonl")
    prices = read_jsonl(root / "price_records.jsonl")
    errors: list[str] = []
    all_cases = public + synthetic
    if len(public) < 100:
        errors.append(f"public_cases < 100: {len(public)}")
    if len(synthetic) < 100:
        errors.append(f"synthetic_cases < 100: {len(synthetic)}")
    if len(fixtures) != 5:
        errors.append(f"case_fixtures != 5: {len(fixtures)}")
    if len({row.get('case_id') for row in all_cases}) != len(all_cases):
        errors.append("duplicate case_id")
    for row in public:
        for field in ("case_id", "title", "structure_type", "location", "source_url", "license"):
            if not row.get(field):
                errors.append(f"public case {row.get('case_id')} missing {field}")
        if row.get("synthetic") is not False:
            errors.append(f"public case {row.get('case_id')} not marked synthetic=false")
        if row.get("detail_status") == "ok":
            if not row.get("detail_source_url"):
                errors.append(f"public case {row.get('case_id')} missing detail_source_url")
            detail_sha = str(row.get("detail_source_sha256", ""))
            if not re.fullmatch(r"[0-9a-f]{64}", detail_sha):
                errors.append(f"public case {row.get('case_id')} invalid detail_source_sha256")

    detailed_fields = {
        "title", "application", "structure_type", "membrane_material", "location",
        "year", "area_m2", "design_goal", "material_selection_reason",
    }
    detailed_cases = [row for row in all_cases if all(row.get(field) is not None for field in detailed_fields)]
    if len(detailed_cases) < 50:
        errors.append(f"detailed_cases < 50: {len(detailed_cases)}")

    public_specs = [row for row in specs if row.get("synthetic") is False]
    if len(public_specs) < 40:
        errors.append(f"public_specs < 40: {len(public_specs)}")
    if len({row.get('spec_id') for row in specs}) != len(specs):
        errors.append("duplicate spec_id")
    public_detail_ok = sum(row.get("detail_status") == "ok" for row in public)
    if public_detail_ok < 90:
        errors.append(f"public case detail status ok < 90: {public_detail_ok}")
    if sum(bool(row.get("application")) for row in public) < 80:
        errors.append("public case application coverage < 80")
    if sum(row.get("year") is not None for row in public) < 70:
        errors.append("public case year coverage < 70")
    if sum(bool(row.get("membrane_material")) for row in public) < 45:
        errors.append("public case membrane material coverage < 45")
    for row in public_specs:
        if not isinstance(row.get("source_page"), int) or row.get("source_page", 0) < 1:
            errors.append(f"public spec {row.get('spec_id')} missing source_page")
        if not isinstance(row.get("source_page_count"), int) or row.get("source_page_count", 0) < 2:
            errors.append(f"public spec {row.get('spec_id')} missing source_page_count")
    for row in specs:
        if not row.get("tenant_id") or row.get("visibility") not in {"public", "internal", "restricted"}:
            errors.append(f"spec {row.get('spec_id')} missing tenant/visibility")

    if len(prices) < 60:
        errors.append(f"prices < 60: {len(prices)}")
    if len({row.get('price_id') for row in prices}) != len(prices):
        errors.append("duplicate price_id")
    for row in prices:
        if row.get("synthetic") is not True:
            errors.append(f"price {row.get('price_id')} not marked synthetic=true")
        if "synthetic" not in str(row.get("disclaimer", "")).lower():
            errors.append(f"price {row.get('price_id')} missing synthetic disclaimer")
        if row.get("min_price", 0) > row.get("max_price", 0):
            errors.append(f"price {row.get('price_id')} invalid range")
        if not row.get("tenant_id") or row.get("visibility") not in {"public", "internal", "restricted"}:
            errors.append(f"price {row.get('price_id')} missing tenant/visibility")

    for row in all_cases + fixtures + specs + prices:
        record_id = str(row.get("case_id") or row.get("spec_id") or row.get("price_id"))
        _validate_provenance(row, record_id, errors)

    document_manifest = read_jsonl(ROOT / "data" / "manifests" / "document_fixtures.jsonl")
    if len(document_manifest) < 30:
        errors.append(f"document_fixtures < 30: {len(document_manifest)}")
    format_counts = Counter(row.get("format") for row in document_manifest)
    for suffix in ("pdf", "docx", "xlsx"):
        if format_counts[suffix] < 10:
            errors.append(f"document format {suffix} < 10: {format_counts[suffix]}")
    fixture_root = ROOT / "data" / "fixtures" / "documents"
    for row in document_manifest:
        path = fixture_root / str(row.get("filename", ""))
        if not path.is_file():
            errors.append(f"missing document fixture {path.name}")
            continue
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != row.get("sha256"):
            errors.append(f"document fixture sha mismatch {path.name}")
        for field in ("source_url", "license", "retrieved_at", "sha256"):
            if not row.get(field):
                errors.append(f"document fixture {path.name} missing {field}")
        if row.get("format") == "pdf":
            try:
                import pymupdf

                with pymupdf.open(path) as document:
                    actual_pages = len(document)
                if actual_pages < 2:
                    errors.append(f"PDF fixture {path.name} has only one page")
                if row.get("page_count") != actual_pages:
                    errors.append(
                        f"PDF fixture {path.name} page_count mismatch: {row.get('page_count')} != {actual_pages}"
                    )
            except Exception as exc:
                errors.append(f"PDF fixture {path.name} unreadable: {type(exc).__name__}")

    print(
        f"business_cases={len(all_cases)} public={len(public)} synthetic={len(synthetic)} fixtures={len(fixtures)} "
        f"detailed={len(detailed_cases)} specs={len(specs)} public_specs={len(public_specs)} "
        f"prices={len(prices)} documents={len(document_manifest)} formats={dict(format_counts)} "
        f"public_detail_ok={public_detail_ok}"
    )
    if errors:
        print("\n".join(errors))
        return 1
    print("data-validation-ok")
    return 0


if __name__ == "__main__":
    sys.exit(validate())
