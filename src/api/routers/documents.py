from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from src.core.config import get_settings
from src.engineering.parsing import parse_document
from src.engineering.schemas import DocumentResponse, IndexResponse
from src.engineering.storage import storage
from src.events.kafka_events import publisher
from src.workflows.temporal_app import submit_document_ingest

router = APIRouter(prefix="/api/v1/documents", tags=["documents"])
ALLOWED_SUFFIXES = {".pdf", ".docx", ".xlsx", ".xlsm", ".txt", ".md"}
MAX_BYTES = 25 * 1024 * 1024


@router.post("/upload", response_model=DocumentResponse)
async def upload_document(file: UploadFile = File(...)) -> DocumentResponse:
    filename = file.filename or "document"
    if Path(filename).suffix.lower() not in ALLOWED_SUFFIXES:
        raise HTTPException(status_code=415, detail="仅支持 PDF、DOCX、XLSX、TXT 和 Markdown")
    content = await file.read()
    if len(content) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="文件不能超过 25MB")
    row = await storage.add_document(filename, file.content_type or "application/octet-stream", content, "pending")
    return DocumentResponse(document_id=row["id"], filename=filename, version=1, parser="pending", status="uploaded")


@router.post("/{document_id}/index", response_model=IndexResponse)
async def index_document(document_id: str) -> IndexResponse:
    row = await storage.get_document(document_id)
    if not row:
        raise HTTPException(status_code=404, detail="文档不存在")
    if get_settings().TEMPORAL_ENABLED:
        workflow = await submit_document_ingest(document_id)
        return IndexResponse(
            document_id=document_id,
            chunks=0,
            parser="temporal",
            status=workflow["status"],
            workflow_id=workflow["workflow_id"],
        )
    local_path = await storage.resolve_document_path(row)
    chunks, parser = await parse_document(str(local_path))
    count = await storage.save_chunks(document_id, chunks, parser)
    await publisher.publish(
        "document.ingest.completed",
        document_id,
        {"document_id": document_id, "chunks": count, "parser": parser},
    )
    return IndexResponse(document_id=document_id, chunks=count, parser=parser, status="indexed")
