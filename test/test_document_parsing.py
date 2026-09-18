from __future__ import annotations

import asyncio
import io
import os
from pathlib import Path

import pytest

from src.documents import parsing

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


def test_pdf_parser_preserves_all_nonempty_pages(tmp_path: Path) -> None:
    import pymupdf

    path = tmp_path / "two-page.pdf"
    document = pymupdf.open()
    document.new_page().insert_text((72, 72), "page one membrane evidence")
    document.new_page().insert_text((72, 72), "page two price evidence")
    document.save(path)
    document.close()

    chunks = parsing.parse_basic(path)
    assert {chunk["page_number"] for chunk in chunks} == {1, 2}
    assert "page two price evidence" in "\n".join(chunk["text"] for chunk in chunks)


def test_empty_pdf_produces_no_false_evidence(tmp_path: Path) -> None:
    import pymupdf

    path = tmp_path / "scan-only.pdf"
    document = pymupdf.open()
    document.new_page()
    document.save(path)
    document.close()

    assert parsing.parse_basic(path) == []


def test_corrupt_document_fails_explicitly(tmp_path: Path) -> None:
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"not a PDF")
    with pytest.raises(Exception):
        parsing.parse_basic(path)


def test_docx_embedded_image_is_located_and_ocr_merged(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from docx import Document
    from PIL import Image

    image_path = tmp_path / "embedded.png"
    Image.new("RGB", (20, 20), "white").save(image_path)
    document = Document()
    document.add_heading("膜材参数", level=1)
    document.add_paragraph("图片附近正文")
    document.add_picture(str(image_path))
    path = tmp_path / "embedded.docx"
    document.save(path)

    async def fake_ocr(blob: bytes, suffix: str, location: str) -> list[dict]:
        assert blob and suffix == ".png"
        return [parsing._evidence(
            "OCR识别膜材厚度0.8mm",
            0,
            location=location,
            source_kind="embedded_image_ocr",
            ocr_used=True,
        )]

    monkeypatch.setattr(parsing.settings, "PARSER_MODE", "mineru")
    monkeypatch.setattr(parsing, "_ocr_blob", fake_ocr)
    chunks, parser = asyncio.run(parsing.parse_document(str(path)))

    ocr = [item for item in chunks if item["ocr_used"]]
    assert parser == "docx-native+mineru-ocr"
    assert len(ocr) == 1
    assert "段落" in ocr[0]["location"] and "图片" in ocr[0]["location"]


def test_xlsx_anchored_image_is_located_and_ocr_merged(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from openpyxl import Workbook
    from openpyxl.drawing.image import Image as WorksheetImage
    from PIL import Image

    image_bytes = io.BytesIO()
    Image.new("RGB", (20, 20), "white").save(image_bytes, format="PNG")
    image_bytes.seek(0)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "膜材表"
    sheet["A1"] = "规格"
    sheet.add_image(WorksheetImage(image_bytes), "C4")
    path = tmp_path / "embedded.xlsx"
    workbook.save(path)

    async def fake_ocr(blob: bytes, suffix: str, location: str) -> list[dict]:
        assert blob and suffix == ".png"
        return [parsing._evidence(
            "OCR识别价格日期2026-08-01",
            0,
            location=location,
            source_kind="embedded_image_ocr",
            ocr_used=True,
        )]

    monkeypatch.setattr(parsing.settings, "PARSER_MODE", "mineru")
    monkeypatch.setattr(parsing, "_ocr_blob", fake_ocr)
    chunks, parser = asyncio.run(parsing.parse_document(str(path)))

    ocr = [item for item in chunks if item["ocr_used"]]
    assert parser == "xlsx-native+mineru-ocr"
    assert len(ocr) == 1
    assert ocr[0]["sheet_name"] == "膜材表" and ocr[0]["anchor"] == "C4"


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

    assert parser == "mineru:text"
    assert chunks
    assert "SYNTHETIC MEMBRANE" in "\n".join(chunk["text"] for chunk in chunks)


@pytest.mark.skipif(
    os.getenv("RUN_MINERU_OFFICE_OCR_TEST") != "1",
    reason="set RUN_MINERU_OFFICE_OCR_TEST=1 for real Office image OCR",
)
def test_real_mineru_ocrs_docx_and_xlsx_images(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from docx import Document
    from openpyxl import Workbook
    from openpyxl.drawing.image import Image as WorksheetImage
    from PIL import Image, ImageDraw, ImageFont

    image_path = tmp_path / "office-evidence.png"
    image = Image.new("RGB", (1000, 300), "white")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("arial.ttf", 64)
    except OSError:
        font = ImageFont.load_default()
    draw.text((40, 100), "PTFE THICKNESS 0.8 MM", fill="black", font=font)
    image.save(image_path)

    docx = Document()
    docx.add_heading("Material evidence", level=1)
    docx.add_picture(str(image_path))
    docx_path = tmp_path / "office-evidence.docx"
    docx.save(docx_path)

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Material"
    sheet.add_image(WorksheetImage(str(image_path)), "D5")
    xlsx_path = tmp_path / "office-evidence.xlsx"
    workbook.save(xlsx_path)

    monkeypatch.setattr(parsing.settings, "PARSER_MODE", "mineru")
    monkeypatch.setattr(
        parsing.settings,
        "MINERU_EXECUTABLE",
        r"F:\code\homework\project\1_membrane_project_precheck\runtime\envs\mineru\Scripts\mineru.exe",
    )
    monkeypatch.setattr(parsing.settings, "MINERU_WORK_ROOT", str(tmp_path / "mineru"))
    monkeypatch.setattr(parsing.settings, "MINERU_BACKEND", "pipeline")

    docx_chunks, docx_parser = asyncio.run(parsing.parse_document(str(docx_path)))
    xlsx_chunks, xlsx_parser = asyncio.run(parsing.parse_document(str(xlsx_path)))

    assert docx_parser == "docx-native+mineru-ocr"
    assert xlsx_parser == "xlsx-native+mineru-ocr"
    assert any(item["ocr_used"] and "图片" in item["location"] for item in docx_chunks)
    assert any(item["ocr_used"] and item["anchor"] == "D5" for item in xlsx_chunks)
