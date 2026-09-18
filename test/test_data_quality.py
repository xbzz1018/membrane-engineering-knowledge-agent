import json
from pathlib import Path

import pymupdf

from scripts.collect_public_case_metadata import parse_project_detail

ROOT = Path(__file__).resolve().parents[1]


def test_tensinet_detail_parser_extracts_engineering_fields() -> None:
    html = """
    <li><span class="project-subtitle">Location address</span><h5>Berlin</h5></li>
    <li><span class="project-subtitle">Year of construction</span><h5>2012</h5></li>
    <li><span class="project-subtitle">Function of building</span><h5>Airports</h5></li>
    <li><span class="project-subtitle">Cable-net/Fabric/Hybrid/Foil</span><h5>Fabric</h5></li>
    <li><span class="project-subtitle">Material Fabric/Foil</span><h5>Fiberglass</h5></li>
    """
    fields = parse_project_detail(html)
    assert fields["Location address"] == "Berlin"
    assert fields["Year of construction"] == "2012"
    assert fields["Function of building"] == "Airports"
    assert fields["Material Fabric/Foil"] == "Fiberglass"


def test_fixture_pdfs_are_multi_page() -> None:
    root = ROOT / "data" / "fixtures" / "documents"
    paths = sorted(root.glob("*.pdf"))
    assert len(paths) == 10
    for path in paths:
        with pymupdf.open(path) as document:
            assert len(document) >= 2


def test_public_case_dataset_has_detail_coverage() -> None:
    path = ROOT / "data" / "processed" / "public_cases.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(rows) == 100
    assert sum(row.get("detail_status") == "ok" for row in rows) >= 90
    assert sum(bool(row.get("application")) for row in rows) >= 80
    assert sum(row.get("year") is not None for row in rows) >= 70
