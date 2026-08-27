from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src.engineering.schemas import MemoryItemResponse
from src.engineering.storage import storage

router = APIRouter(prefix="/api/v1/memories", tags=["memories"])


@router.get("/{user_id}", response_model=list[MemoryItemResponse])
async def list_memories(user_id: str) -> list[MemoryItemResponse]:
    rows = await storage.list_memories(user_id)
    return [
        MemoryItemResponse(
            memory_id=row["id"],
            user_id=row["user_id"],
            kind=row["kind"],
            content=row["content"],
            source=row["source"],
            created_at=row["created_at"].isoformat(),
        )
        for row in rows
    ]


@router.delete("/{user_id}/{memory_id}", status_code=204)
async def delete_memory(user_id: str, memory_id: str) -> None:
    if not await storage.delete_memory(user_id, memory_id):
        raise HTTPException(status_code=404, detail="长期记忆不存在")
