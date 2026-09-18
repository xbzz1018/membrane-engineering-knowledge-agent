from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from src.api.dependencies import rate_limited_principal, require_project_role
from src.core.config import get_settings
from src.core.security import Principal
from src.documents.parsing import parse_document
from src.domain.schemas import DocumentResponse, IndexResponse
from src.infrastructure.database import storage
from src.workflows.temporal_app import submit_document_ingest

router = APIRouter(prefix="/api/v1/documents", tags=["工程资料"])
ALLOWED_SUFFIXES = {".pdf", ".docx", ".xlsx", ".xlsm", ".txt", ".md"}
MAX_BYTES = 25 * 1024 * 1024


@router.get("", summary="查看项目资料列表")
async def list_documents(
    project_id: str = "demo-project",
    principal: Principal = Depends(rate_limited_principal),
) -> list[dict]:
    await require_project_role(project_id, principal)
    rows = await storage.list_documents(project_id=project_id, tenant_id=principal.tenant_id)
    return [
        {key: value for key, value in row.items() if key != "stored_path"}
        for row in sorted(rows, key=lambda item: item["created_at"], reverse=True)
    ]


@router.get("/{document_id}", summary="查看资料版本与解析状态")
async def get_document(
    document_id: str,
    principal: Principal = Depends(rate_limited_principal),
) -> dict:
    row = await storage.get_document(document_id)
    if not row:
        raise HTTPException(status_code=404, detail="文档不存在")
    await require_project_role(row["project_id"], principal)
    return {key: value for key, value in row.items() if key != "stored_path"}


@router.get("/{document_id}/evidence", summary="查看资料解析后的EvidenceUnit")
async def document_evidence(
    document_id: str,
    principal: Principal = Depends(rate_limited_principal),
) -> list[dict]:
    row = await storage.get_document(document_id)
    if not row:
        raise HTTPException(status_code=404, detail="文档不存在")
    await require_project_role(row["project_id"], principal)
    return await storage.list_document_chunks(document_id, limit=5000)


@router.post("/upload", response_model=DocumentResponse, summary="上传工程资料")
async def upload_document(
    file: UploadFile = File(...),
    project_id: str = Form(default="demo-project"),
    data_classification: str = Form(default="public"),
    parse_method: str = Form(default="auto"),
    version: int = Form(default=1, ge=1),
    principal: Principal = Depends(rate_limited_principal),
) -> DocumentResponse:
    await require_project_role(project_id, principal, {"admin", "design_engineer", "material_procurement"})
    if data_classification not in {"public", "internal", "restricted"}:
        raise HTTPException(status_code=422, detail="不支持的数据分级")
    if parse_method not in {"auto", "text", "ocr"}:
        raise HTTPException(status_code=422, detail="不支持的解析方式")
    filename = file.filename or "document"
    if Path(filename).suffix.lower() not in ALLOWED_SUFFIXES:
        raise HTTPException(status_code=415, detail="仅支持 PDF、DOCX、XLSX、TXT 和 Markdown")
    content = await file.read()
    if len(content) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="文件不能超过 25MB")
    row = await storage.add_document(
        filename,
        file.content_type or "application/octet-stream",
        content,
        "pending",
        tenant_id=principal.tenant_id,
        project_id=project_id,
        data_classification=data_classification,
        parse_method=parse_method,
        version=version,
    )
    return DocumentResponse(
        document_id=row["id"], filename=row["filename"], version=row["version"], parser=row["parser"],
        status=row["status"], project_id=row["project_id"], sha256=row["sha256"],
        data_classification=row["data_classification"], parse_method=row["parse_method"],
    )


@router.post("/{document_id}/index", response_model=IndexResponse, summary="启动资料解析与索引")
async def index_document(
    document_id: str,
    principal: Principal = Depends(rate_limited_principal),
) -> IndexResponse:
    row = await storage.get_document(document_id)
    if not row:
        raise HTTPException(status_code=404, detail="文档不存在")
    await require_project_role(row["project_id"], principal, {"admin", "design_engineer", "material_procurement"})
    if get_settings().TEMPORAL_ENABLED:
        workflow = await submit_document_ingest(document_id)
        return IndexResponse(
            document_id=document_id,
            chunks=0,
            parser="temporal",
            status=workflow["status"],
            workflow_id=workflow["workflow_id"],
        )
    refresh_embedding = (
        get_settings().RUNTIME_MODE.lower() == "full"
        and row.get("embedding_model", "") != get_settings().EMBEDDING_MODEL
    )
    acquired = await storage.acquire_document_ingest(document_id, refresh_embedding=refresh_embedding)
    if not acquired and row["status"] == "indexed":
        return IndexResponse(
            document_id=document_id,
            chunks=await storage.count_document_chunks(document_id),
            parser=row["parser"],
            status="existing",
        )
    if not acquired:
        raise HTTPException(status_code=409, detail="文档正在处理")
    try:
        local_path = await storage.resolve_document_path(row)
        chunks, parser = await parse_document(str(local_path), row["parse_method"])
        count = await storage.save_chunks(document_id, chunks, parser)
    except Exception as exc:
        current = await storage.get_document(document_id)
        if not current or current["status"] != "index_failed":
            await storage.fail_document(document_id, type(exc).__name__)
        raise HTTPException(status_code=422, detail=f"文档解析失败: {type(exc).__name__}") from exc
    return IndexResponse(document_id=document_id, chunks=count, parser=parser, status="indexed")
