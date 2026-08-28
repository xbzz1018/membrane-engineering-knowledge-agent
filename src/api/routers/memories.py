from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from src.api.dependencies import current_principal, require_project_role
from src.core.security import Principal
from src.engineering.schemas import MemoryCandidateRequest, MemoryItemResponse, MemoryUpdateRequest
from src.engineering.storage import storage

router = APIRouter(prefix="/api/v1/memories", tags=["memories"])


def _response(row: dict) -> MemoryItemResponse:
    return MemoryItemResponse(
        memory_id=row["id"],
        user_id=row["user_id"],
        kind=row["kind"],
        content=row["content"],
        source=row["source"],
        created_at=row["created_at"].isoformat(),
        project_id=row.get("project_id") or "",
        scope=row.get("scope", "user"),
        status=row.get("status", "pending"),
    )


@router.get("", response_model=list[MemoryItemResponse])
async def list_current_memories(
    project_id: str | None = Query(default=None),
    status: str | None = Query(default=None, pattern="^(pending|confirmed|rejected|superseded)$"),
    principal: Principal = Depends(current_principal),
) -> list[MemoryItemResponse]:
    if project_id:
        await require_project_role(project_id, principal)
    rows = await storage.list_memories(principal.user_id, project_id=project_id, status=status)
    return [_response(row) for row in rows]


@router.get("/{user_id}", response_model=list[MemoryItemResponse], deprecated=True)
async def list_memories_compat(
    user_id: str,
    principal: Principal = Depends(current_principal),
) -> list[MemoryItemResponse]:
    if user_id != principal.user_id and principal.role != "admin":
        raise HTTPException(status_code=403, detail="不能查看其他用户的记忆")
    return [_response(row) for row in await storage.list_memories(user_id)]


@router.post("/candidates", response_model=MemoryItemResponse, status_code=201)
async def create_candidate(
    request: MemoryCandidateRequest,
    principal: Principal = Depends(current_principal),
) -> MemoryItemResponse:
    if request.scope == "project":
        if not request.project_id:
            raise HTTPException(status_code=422, detail="项目级记忆必须指定project_id")
        await require_project_role(request.project_id, principal)
    row = await storage.create_memory_candidate(
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        project_id=request.project_id,
        scope=request.scope,
        kind=request.kind,
        content=request.content,
        source_id=request.source_id,
    )
    return _response(row)


@router.post("/{memory_id}/confirm", response_model=MemoryItemResponse)
async def confirm_memory(
    memory_id: str,
    principal: Principal = Depends(current_principal),
) -> MemoryItemResponse:
    row = await storage.set_memory_status(memory_id, principal.user_id, "confirmed")
    if not row:
        raise HTTPException(status_code=404, detail="待确认记忆不存在")
    return _response(row)


@router.post("/{memory_id}/reject", response_model=MemoryItemResponse)
async def reject_memory(
    memory_id: str,
    principal: Principal = Depends(current_principal),
) -> MemoryItemResponse:
    row = await storage.set_memory_status(memory_id, principal.user_id, "rejected")
    if not row:
        raise HTTPException(status_code=404, detail="待确认记忆不存在")
    return _response(row)


@router.patch("/{memory_id}", response_model=MemoryItemResponse)
async def update_memory(
    memory_id: str,
    request: MemoryUpdateRequest,
    principal: Principal = Depends(current_principal),
) -> MemoryItemResponse:
    row = await storage.update_memory(principal.user_id, memory_id, request.content)
    if not row:
        raise HTTPException(status_code=404, detail="长期记忆不存在")
    return _response(row)


@router.delete("/{memory_id}", status_code=204)
async def delete_current_memory(
    memory_id: str,
    principal: Principal = Depends(current_principal),
) -> None:
    if not await storage.delete_memory(principal.user_id, memory_id):
        raise HTTPException(status_code=404, detail="长期记忆不存在")


@router.delete("/{user_id}/{memory_id}", status_code=204, deprecated=True)
async def delete_memory_compat(
    user_id: str,
    memory_id: str,
    principal: Principal = Depends(current_principal),
) -> None:
    if user_id != principal.user_id and principal.role != "admin":
        raise HTTPException(status_code=403, detail="不能删除其他用户的记忆")
    if not await storage.delete_memory(user_id, memory_id):
        raise HTTPException(status_code=404, detail="长期记忆不存在")
