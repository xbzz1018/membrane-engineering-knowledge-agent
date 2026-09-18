from __future__ import annotations

import asyncio
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from src.api.dependencies import current_principal, rate_limited_principal, require_project_role
from src.core.config import get_settings
from src.core.security import Principal
from src.domain.schemas import BatchImportRequest
from src.infrastructure.database import storage
from src.workflows.temporal_app import get_workflow_state, submit_batch_ingest

router = APIRouter(prefix="/api/v1", tags=["批量资料导入"])
TERMINAL = {"completed", "partial_failed", "failed", "cancelled", "canceled"}


@router.get("/batch-imports", summary="查看项目批量导入记录")
async def list_batch_imports(
    project_id: str = Query(description="项目ID"),
    status: str = Query(default="", max_length=32),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    principal: Principal = Depends(current_principal),
) -> dict:
    await require_project_role(project_id, principal)
    return await storage.list_batch_imports(
        tenant_id=principal.tenant_id,
        project_id=project_id,
        status=status,
        page=page,
        page_size=page_size,
    )


@router.post("/batch-imports", status_code=202, summary="启动最多100份资料的批量导入")
async def create_batch_import(
    request: BatchImportRequest,
    principal: Principal = Depends(rate_limited_principal),
) -> dict:
    settings = get_settings()
    if not settings.TEMPORAL_ENABLED:
        raise HTTPException(status_code=409, detail="批量导入要求启用Temporal")
    if len(request.document_ids) > settings.BATCH_DOCUMENT_LIMIT:
        raise HTTPException(status_code=422, detail="批次文档数量超过配置上限")
    await require_project_role(
        request.project_id, principal, {"admin", "design_engineer", "material_procurement"},
    )
    batch_id = uuid.uuid4().hex
    workflow_id = f"batch-ingest:{batch_id}"
    try:
        row = await storage.create_batch_import(
            request.document_ids,
            tenant_id=principal.tenant_id,
            project_id=request.project_id,
            workflow_id=workflow_id,
            batch_id=batch_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    workflow = await submit_batch_ingest(batch_id, request.document_ids)
    return {**row, "workflow": workflow}


@router.get("/batch-imports/{batch_id}", summary="查看批量导入状态")
async def get_batch_import(
    batch_id: str,
    principal: Principal = Depends(current_principal),
) -> dict:
    row = await storage.get_batch_import(batch_id, principal.tenant_id)
    if not row:
        raise HTTPException(status_code=404, detail="批次不存在")
    await require_project_role(row["project_id"], principal)
    state = await get_workflow_state(row["workflow_id"])
    return {**row, "workflow": state}


@router.get("/batch-imports/{batch_id}/stream", summary="订阅批量导入安全进度")
async def stream_batch_import(
    batch_id: str,
    principal: Principal = Depends(current_principal),
) -> StreamingResponse:
    row = await storage.get_batch_import(batch_id, principal.tenant_id)
    if not row:
        raise HTTPException(status_code=404, detail="批次不存在")
    await require_project_role(row["project_id"], principal)

    async def events():
        last = ""
        while True:
            state = await get_workflow_state(row["workflow_id"])
            safe = {
                key: state.get(key)
                for key in (
                    "workflow_id", "status", "temporal_status", "total", "completed_count",
                    "failed_count", "skipped_count", "documents", "errors",
                )
                if key in state
            }
            encoded = json.dumps(safe, ensure_ascii=False)
            if encoded != last:
                last = encoded
                yield f"data: {encoded}\n\n"
            if state.get("status") in TERMINAL or state.get("temporal_status") in TERMINAL:
                break
            await asyncio.sleep(1)

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
