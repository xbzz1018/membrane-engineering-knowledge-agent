from __future__ import annotations

import asyncio
import json
import re
import subprocess
import tempfile
from collections.abc import Iterable
from hashlib import sha256
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

from src.core.config import get_settings

settings = get_settings()
SUPPORTED_PARSE_METHODS = {"auto", "text", "ocr"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}


class ParserConfigurationError(RuntimeError):
    """Raised when an explicitly selected parser is unavailable."""


class ParserExecutionError(RuntimeError):
    """Raised when a parser cannot produce usable evidence."""


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _chunks(text: str, chunk_size: int = 1200) -> list[str]:
    normalized = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    return [normalized[index:index + chunk_size] for index in range(0, len(normalized), chunk_size)] or [""]


def _evidence(
    text: str,
    index: int,
    *,
    page_number: int = 1,
    location: str = "",
    heading_path: str = "",
    sheet_name: str = "",
    anchor: str = "",
    source_kind: str = "text",
    ocr_used: bool = False,
) -> dict[str, Any]:
    value = text.strip()
    return {
        "page_number": page_number,
        "chunk_index": index,
        "text": value,
        "location": location or (f"第{page_number}页" if page_number else ""),
        "heading_path": heading_path,
        "sheet_name": sheet_name,
        "anchor": anchor,
        "source_kind": source_kind,
        "ocr_used": ocr_used,
        "status": "processed",
        "token_count": max(1, len(value) // 3),
        "sha256": sha256(value.encode("utf-8")).hexdigest(),
    }


def _parse_pdf_basic(path: Path) -> list[dict[str, Any]]:
    import pymupdf as fitz

    result: list[dict[str, Any]] = []
    index = 0
    with fitz.open(path) as document:
        for page_number, page in enumerate(document, 1):
            for value in _chunks(page.get_text("text")):
                if value:
                    result.append(_evidence(value, index, page_number=page_number))
                    index += 1
    return result


def _extract_mineru_content(output_dir: Path) -> list[dict[str, Any]]:
    content_files = sorted(output_dir.rglob("*content_list.json"))
    result: list[dict[str, Any]] = []
    if content_files:
        rows = json.loads(content_files[0].read_text(encoding="utf-8"))
        for row in rows if isinstance(rows, list) else []:
            text = str(
                row.get("text")
                or row.get("table_body")
                or row.get("image_caption")
                or row.get("content")
                or ""
            ).strip()
            if not text:
                continue
            page = int(row.get("page_idx", row.get("page_number", 0))) + 1
            kind = str(row.get("type") or row.get("category") or "text")
            for value in _chunks(text):
                result.append(_evidence(
                    value,
                    len(result),
                    page_number=page,
                    source_kind=kind,
                    ocr_used=kind.lower() in {"ocr", "image", "table"},
                ))
        if result:
            return result
    markdown_files = sorted(output_dir.rglob("*.md"))
    if not markdown_files:
        raise ParserExecutionError("MinerU completed without structured or Markdown output")
    text = "\n".join(file.read_text(encoding="utf-8", errors="ignore") for file in markdown_files)
    return [_evidence(value, index, source_kind="mineru") for index, value in enumerate(_chunks(text)) if value]


async def _parse_with_mineru(path: Path, method: str) -> list[dict[str, Any]]:
    executable = Path(settings.MINERU_EXECUTABLE)
    if not executable.exists():
        raise ParserConfigurationError("MinerU executable is not available")
    work_root = Path(settings.MINERU_WORK_ROOT or settings.upload_path / "mineru")
    work_root.mkdir(parents=True, exist_ok=True)
    mineru_method = "txt" if method == "text" else method
    try:
        with tempfile.TemporaryDirectory(prefix="ingest-", dir=work_root) as temporary:
            command = [
                str(executable),
                "-p", str(path),
                "-o", temporary,
                "--backend", settings.MINERU_BACKEND,
                "--method", mineru_method,
                "--lang", settings.MINERU_LANG,
            ]
            if settings.MINERU_API_URL:
                command.extend(("--api-url", settings.MINERU_API_URL))
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(process.communicate(), timeout=settings.MINERU_TIMEOUT)
            if process.returncode != 0:
                detail = stderr.decode("utf-8", errors="ignore")[-500:]
                raise ParserExecutionError(f"MinerU exited with {process.returncode}: {detail}")
            return _extract_mineru_content(Path(temporary))
    except TimeoutError as exc:
        raise ParserExecutionError("MinerU parsing timed out") from exc


async def _ocr_blob(blob: bytes, suffix: str, location: str) -> list[dict[str, Any]]:
    if settings.PARSER_MODE.lower() != "mineru":
        return []
    work_root = Path(settings.MINERU_WORK_ROOT or settings.upload_path / "mineru")
    work_root.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=suffix, dir=work_root, delete=False) as handle:
        handle.write(blob)
        path = Path(handle.name)
    try:
        rows = await _parse_with_mineru(path, "ocr")
        asset_sha = sha256(blob).hexdigest()
        for row in rows:
            row["location"] = location
            row["ocr_used"] = True
            row["source_kind"] = "embedded_image_ocr"
            row["asset_sha256"] = asset_sha
            row["asset_suffix"] = suffix
            row["asset_bytes"] = blob
        return rows
    finally:
        path.unlink(missing_ok=True)


def _docx_native(path: Path) -> tuple[list[dict[str, Any]], list[tuple[bytes, str, str]]]:
    from docx import Document
    from docx.oxml.ns import qn

    document = Document(path)
    result: list[dict[str, Any]] = []
    images: list[tuple[bytes, str, str]] = []
    headings: list[str] = []
    for paragraph_index, paragraph in enumerate(document.paragraphs, 1):
        text = paragraph.text.strip()
        style = paragraph.style.name if paragraph.style else ""
        if text and style.lower().startswith("heading"):
            match = re.search(r"(\d+)$", style)
            level = int(match.group(1)) if match else 1
            headings = headings[: level - 1] + [text]
        if text:
            for value in _chunks(text):
                result.append(_evidence(
                    value,
                    len(result),
                    location=f"段落{paragraph_index}",
                    heading_path=" / ".join(headings),
                    source_kind="docx_text",
                ))
        for blip in paragraph._p.xpath(".//a:blip"):
            relationship_id = blip.get(qn("r:embed"))
            if not relationship_id or relationship_id not in document.part.rels:
                continue
            target = document.part.rels[relationship_id].target_part
            suffix = Path(str(getattr(target, "partname", ".png"))).suffix.lower() or ".png"
            if suffix in IMAGE_SUFFIXES:
                images.append((target.blob, suffix, f"段落{paragraph_index} / 图片{len(images) + 1}"))
    for table_index, table in enumerate(document.tables, 1):
        rows = [" | ".join(cell.text.strip() for cell in row.cells) for row in table.rows]
        text = "\n".join(value for value in rows if value.strip(" |"))
        for value in _chunks(text):
            result.append(_evidence(
                value,
                len(result),
                location=f"表格{table_index}",
                heading_path=" / ".join(headings),
                source_kind="docx_table",
            ))
    return result, images


def _xlsx_native(path: Path) -> tuple[list[dict[str, Any]], list[tuple[bytes, str, str, str]]]:
    workbook = load_workbook(path, read_only=False, data_only=True)
    result: list[dict[str, Any]] = []
    images: list[tuple[bytes, str, str, str]] = []
    for sheet in workbook.worksheets:
        lines = []
        for row in sheet.iter_rows(values_only=True):
            values = [str(value) for value in row if value is not None]
            if values:
                lines.append(" | ".join(values))
        for value in _chunks("\n".join(lines)):
            result.append(_evidence(
                value,
                len(result),
                location=f"工作表 {sheet.title}",
                sheet_name=sheet.title,
                source_kind="xlsx_cells",
            ))
        for image_index, image in enumerate(getattr(sheet, "_images", []), 1):
            marker = getattr(image.anchor, "_from", None)
            anchor = ""
            if marker is not None:
                anchor = f"{get_column_letter(marker.col + 1)}{marker.row + 1}"
            suffix = Path(str(getattr(image, "path", ".png"))).suffix.lower() or ".png"
            if suffix in IMAGE_SUFFIXES:
                images.append((image._data(), suffix, sheet.title, anchor or f"图片{image_index}"))
    workbook.close()
    return result, images


def _append_deduplicated(
    target: list[dict[str, Any]],
    rows: Iterable[dict[str, Any]],
    seen: set[str],
    *,
    heading_path: str = "",
    sheet_name: str = "",
    anchor: str = "",
) -> None:
    native_text = _normalize(" ".join(item["text"] for item in target))
    for row in rows:
        normalized = _normalize(row["text"])
        if not normalized or normalized in native_text:
            continue
        digest = sha256(normalized.encode("utf-8")).hexdigest()
        if digest in seen:
            continue
        seen.add(digest)
        row.update(
            chunk_index=len(target),
            heading_path=heading_path or row.get("heading_path", ""),
            sheet_name=sheet_name or row.get("sheet_name", ""),
            anchor=anchor or row.get("anchor", ""),
            sha256=digest,
        )
        target.append(row)


def parse_basic(path: str | Path) -> list[dict[str, Any]]:
    """Synchronous native parser used by local tests and lightweight tooling."""
    file_path = Path(path)
    suffix = file_path.suffix.lower()
    if suffix == ".pdf":
        return _parse_pdf_basic(file_path)
    if suffix == ".docx":
        return _docx_native(file_path)[0]
    if suffix in {".xlsx", ".xlsm"}:
        return _xlsx_native(file_path)[0]
    text = file_path.read_text(encoding="utf-8", errors="ignore")
    return [_evidence(value, index, source_kind="plain_text") for index, value in enumerate(_chunks(text))]


async def parse_document(path: str, parse_method: str | None = None) -> tuple[list[dict[str, Any]], str]:
    file_path = Path(path)
    method = (parse_method or settings.MINERU_METHOD or "auto").lower()
    if method == "txt":
        method = "text"
    if method not in SUPPORTED_PARSE_METHODS:
        raise ParserConfigurationError(f"Unsupported parse method: {method}")
    suffix = file_path.suffix.lower()
    if suffix == ".pdf":
        if settings.PARSER_MODE.lower() == "mineru":
            rows = await _parse_with_mineru(file_path, method)
            return rows, f"mineru:{method}"
        return await asyncio.to_thread(parse_basic, file_path), "basic:pdf"
    if suffix == ".docx":
        rows, images = await asyncio.to_thread(_docx_native, file_path)
        seen: set[str] = set()
        for blob, image_suffix, location in images:
            ocr_rows = await _ocr_blob(blob, image_suffix, location)
            _append_deduplicated(rows, ocr_rows, seen)
        return rows, "docx-native+mineru-ocr" if images and settings.PARSER_MODE.lower() == "mineru" else "docx-native"
    if suffix in {".xlsx", ".xlsm"}:
        rows, images = await asyncio.to_thread(_xlsx_native, file_path)
        seen = set()
        for blob, image_suffix, sheet_name, anchor in images:
            location = f"工作表 {sheet_name} / {anchor} / 图片"
            ocr_rows = await _ocr_blob(blob, image_suffix, location)
            _append_deduplicated(rows, ocr_rows, seen, sheet_name=sheet_name, anchor=anchor)
        return rows, "xlsx-native+mineru-ocr" if images and settings.PARSER_MODE.lower() == "mineru" else "xlsx-native"
    text = file_path.read_text(encoding="utf-8", errors="ignore")
    return [_evidence(value, index, source_kind="plain_text") for index, value in enumerate(_chunks(text))], "plain-text"
