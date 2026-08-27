from __future__ import annotations

import asyncio
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from src.core.config import get_settings

settings = get_settings()


def _chunks(text: str, chunk_size: int = 1200) -> list[str]:
    normalized = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    return [normalized[i:i + chunk_size] for i in range(0, len(normalized), chunk_size)] or [""]


def parse_basic(path: Path) -> list[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        try:
            import fitz

            pages = []
            with fitz.open(path) as doc:
                for page_number, page in enumerate(doc, 1):
                    pages.append((page_number, page.get_text("text")))
            chunks: list[dict[str, Any]] = []
            index = 0
            for page_number, text in pages:
                for item in _chunks(text):
                    chunks.append({"page_number": page_number, "chunk_index": index, "text": item})
                    index += 1
            return chunks
        except Exception:
            return [{"page_number": 1, "chunk_index": 0, "text": path.read_bytes().decode("utf-8", errors="ignore")}]
    if suffix == ".docx":
        from docx import Document

        text = "\n".join(paragraph.text for paragraph in Document(path).paragraphs)
        return [{"page_number": 1, "chunk_index": i, "text": value} for i, value in enumerate(_chunks(text))]
    if suffix in {".xlsx", ".xlsm"}:
        from openpyxl import load_workbook

        workbook = load_workbook(path, read_only=True, data_only=True)
        rows = []
        for sheet in workbook.worksheets:
            rows.append(f"[Sheet: {sheet.title}]")
            for row in sheet.iter_rows(values_only=True):
                values = [str(value) for value in row if value is not None]
                if values:
                    rows.append(" | ".join(values))
        return [{"page_number": 1, "chunk_index": i, "text": value} for i, value in enumerate(_chunks("\n".join(rows)))]
    text = path.read_text(encoding="utf-8", errors="ignore")
    return [{"page_number": 1, "chunk_index": i, "text": value} for i, value in enumerate(_chunks(text))]


async def parse_document(path: str) -> tuple[list[dict[str, Any]], str]:
    file_path = Path(path)
    if settings.PARSER_MODE.lower() == "mineru" and settings.MINERU_EXECUTABLE:
        executable = Path(settings.MINERU_EXECUTABLE)
        if executable.exists():
            # MinerU output formats vary by version; use it when successful and fall back safely.
            try:
                work_root = Path(settings.MINERU_WORK_ROOT or settings.upload_path / "mineru")
                work_root.mkdir(parents=True, exist_ok=True)
                with tempfile.TemporaryDirectory(prefix="ingest-", dir=work_root) as temporary:
                    command = [
                        str(executable),
                        "-p", str(file_path),
                        "-o", temporary,
                        "--backend", settings.MINERU_BACKEND,
                        "--method", settings.MINERU_METHOD,
                        "--lang", settings.MINERU_LANG,
                    ]
                    if settings.MINERU_API_URL:
                        command.extend(("--api-url", settings.MINERU_API_URL))
                    proc = await asyncio.create_subprocess_exec(
                        *command,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                    )
                    _, stderr = await asyncio.wait_for(proc.communicate(), timeout=settings.MINERU_TIMEOUT)
                    if proc.returncode != 0:
                        detail = stderr.decode("utf-8", errors="ignore")[-500:]
                        raise RuntimeError(f"MinerU exited with {proc.returncode}: {detail}")
                    markdown_files = sorted(Path(temporary).rglob("*.md"))
                    if markdown_files:
                        text = "\n".join(
                            path.read_text(encoding="utf-8", errors="ignore") for path in markdown_files
                        )
                        chunks = [
                            {"page_number": 1, "chunk_index": i, "text": item}
                            for i, item in enumerate(_chunks(text))
                        ]
                        return chunks, "mineru"
            except Exception:
                pass
    return await asyncio.to_thread(parse_basic, file_path), "basic"
