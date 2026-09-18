"""Build deterministic synthetic PDF, DOCX and XLSX ingestion fixtures."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from docx import Document
from openpyxl import Workbook

FIXED_TIME = datetime(2026, 8, 27, tzinfo=UTC)
MATERIALS = ["PTFE", "PVC/PVDF", "ETFE", "PTFE mesh", "PVC mesh"]


def _content(index: int) -> list[str]:
    material = MATERIALS[(index - 1) % len(MATERIALS)]
    return [
        "SYNTHETIC MEMBRANE ENGINEERING FIXTURE",
        f"Document ID: fixture-document-{index:02d}",
        f"Material: {material}",
        f"Version: {1 + (index - 1) // 10}",
        "Purpose: parser, indexing, filename retrieval and evidence-page testing.",
        "This document is not an engineering safety conclusion or formal quotation.",
    ]


def _normalize_zip(path: Path) -> None:
    temporary = path.with_suffix(path.suffix + ".normalized")
    with zipfile.ZipFile(path, "r") as source, zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as target:
        for name in sorted(source.namelist()):
            info = zipfile.ZipInfo(name, date_time=(2026, 8, 27, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            content = source.read(name)
            if name == "docProps/core.xml":
                content = re.sub(
                    rb"(<dcterms:modified\b[^>]*>).*?(</dcterms:modified>)",
                    rb"\g<1>2026-08-27T00:00:00Z\g<2>",
                    content,
                )
            target.writestr(info, content)
    temporary.replace(path)


def _build_pdf(path: Path, index: int) -> None:
    def stream(page_number: int) -> bytes:
        lines = _content(index) + [f"Evidence page: {page_number}"]
        commands = ["BT", "/F1 11 Tf", "72 760 Td", "14 TL"]
        for line in lines:
            escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            commands.extend((f"({escaped}) Tj", "T*"))
        commands.append("ET")
        return ("\n".join(commands) + "\n").encode("ascii")

    first_stream = stream(1)
    second_stream = stream(2)
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R 5 0 R] /Count 2 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 7 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length %d >>\nstream\n" % len(first_stream) + first_stream + b"endstream",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 7 0 R >> >> /Contents 6 0 R >>",
        b"<< /Length %d >>\nstream\n" % len(second_stream) + second_stream + b"endstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    payload = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for object_number, body in enumerate(objects, 1):
        offsets.append(len(payload))
        payload.extend(f"{object_number} 0 obj\n".encode("ascii"))
        payload.extend(body)
        payload.extend(b"\nendobj\n")
    xref_offset = len(payload)
    payload.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    payload.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        payload.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    payload.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    path.write_bytes(payload)


def _build_docx(path: Path, index: int) -> None:
    document = Document()
    document.core_properties.created = FIXED_TIME
    document.core_properties.modified = FIXED_TIME
    for line in _content(index):
        document.add_paragraph(line)
    document.save(path)
    _normalize_zip(path)


def _build_xlsx(path: Path, index: int) -> None:
    workbook = Workbook()
    workbook.properties.created = FIXED_TIME.replace(tzinfo=None)
    workbook.properties.modified = FIXED_TIME.replace(tzinfo=None)
    sheet = workbook.active
    sheet.title = "Synthetic Spec"
    for row_index, line in enumerate(_content(index), 1):
        key, _, value = line.partition(":")
        sheet.cell(row=row_index, column=1, value=key)
        sheet.cell(row=row_index, column=2, value=value.strip())
    workbook.save(path)
    _normalize_zip(path)


def build(output_dir: Path) -> list[dict]:
    output_dir.mkdir(parents=True, exist_ok=True)
    builders = [("pdf", _build_pdf), ("docx", _build_docx), ("xlsx", _build_xlsx)]
    manifest = []
    for group, (suffix, builder) in enumerate(builders):
        for offset in range(1, 11):
            index = group * 10 + offset
            filename = f"synthetic-membrane-document-{index:02d}.{suffix}"
            path = output_dir / filename
            builder(path, index)
            manifest_row = {
                "document_id": f"fixture-document-{index:02d}",
                "filename": filename,
                "format": suffix,
                "version": 1 + (index - 1) // 10,
                "source_url": f"synthetic://document-fixtures/{filename}",
                "source_type": "synthetic_document_fixture",
                "license": "Project-generated synthetic fixture; repository LICENSE applies.",
                "retrieved_at": FIXED_TIME.isoformat(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "synthetic": True,
            }
            if suffix == "pdf":
                manifest_row["page_count"] = 2
            manifest.append(manifest_row)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=Path("data/fixtures/documents"))
    parser.add_argument("--manifest", type=Path, default=Path("data/manifests/document_fixtures.jsonl"))
    args = parser.parse_args()
    manifest = build(args.output_dir)
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in manifest) + "\n",
        encoding="utf-8",
    )
    print(f"documents={len(manifest)} output={args.output_dir} manifest={args.manifest}")


if __name__ == "__main__":
    main()
