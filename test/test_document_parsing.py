from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from src.engineering import parsing

FIXTURES = Path("data/fixtures/documents")


@pytest.mark.parametrize(
    ("filename", "marker"),
    [
        ("synthetic-membrane-document-01.pdf", "PTFE"),
        ("synthetic-membrane-document-11.docx", "PTFE"),
        ("synthetic-membrane-document-21.xlsx", "PTFE"),
    ],
)
def test_basic_parser_supports_pdf_docx_and_xlsx(filename: str, marker: str) -> None:
    chunks = parsing.parse_basic(FIXTURES / filename)
    assert chunks
    assert marker in "\n".join(chunk["text"] for chunk in chunks)
    assert all(chunk["page_number"] >= 1 for chunk in chunks)


def test_pdf_fixture_preserves_page_numbers() -> None:
    chunks = parsing.parse_basic(FIXTURES / "synthetic-membrane-document-01.pdf")
    assert {chunk["page_number"] for chunk in chunks} == {1, 2}


@pytest.mark.skipif(os.getenv("RUN_MINERU_TEST") != "1", reason="set RUN_MINERU_TEST=1 for real MinerU")
def test_real_mineru_parses_pdf_fixture(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(parsing.settings, "PARSER_MODE", "mineru")
    monkeypatch.setattr(
        parsing.settings,
        "MINERU_EXECUTABLE",
        r"F:\code\homework\project\1_membrane_project_precheck\runtime\envs\mineru\Scripts\mineru.exe",
    )
    monkeypatch.setattr(parsing.settings, "MINERU_WORK_ROOT", str(tmp_path))
    monkeypatch.setattr(parsing.settings, "MINERU_BACKEND", "pipeline")
    monkeypatch.setattr(parsing.settings, "MINERU_METHOD", "txt")

    chunks, parser = asyncio.run(
        parsing.parse_document(str(FIXTURES / "synthetic-membrane-document-01.pdf"))
    )

    assert parser == "mineru"
    assert chunks
    assert "SYNTHETIC MEMBRANE" in "\n".join(chunk["text"] for chunk in chunks)
