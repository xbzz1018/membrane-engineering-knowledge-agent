from __future__ import annotations

from src.core.config import get_settings
from src.engineering.storage import EngineeringStorage


class ProjectMemoryService:
    """Confirmed long-term context; never used as evidence."""

    def __init__(self, store: EngineeringStorage):
        self.store = store
        self.settings = get_settings()

    async def propose_from_message(
        self,
        *,
        tenant_id: str,
        user_id: str,
        project_id: str,
        message: str,
        source_id: str = "",
    ) -> dict | None:
        markers = ("记住", "以后", "常用", "偏好", "项目是", "本项目", "统一使用")
        if not self.settings.LONG_TERM_MEMORY_ENABLED or not any(marker in message for marker in markers):
            return None
        scope = "project" if any(marker in message for marker in ("项目", "本项目", "膜材", "结构")) else "user"
        return await self.store.create_memory_candidate(
            tenant_id=tenant_id,
            user_id=user_id,
            project_id=project_id if scope == "project" else None,
            scope=scope,
            kind="project_context" if scope == "project" else "user_preference",
            content=message,
            source_id=source_id,
        )

    async def search(
        self,
        *,
        tenant_id: str,
        user_id: str,
        project_id: str,
        query: str,
    ) -> list[str]:
        if not self.settings.LONG_TERM_MEMORY_ENABLED:
            return []
        return await self.store.search_memory(
            user_id,
            query,
            tenant_id=tenant_id,
            project_id=project_id,
        )


def get_memory_service(store: EngineeringStorage) -> ProjectMemoryService:
    return ProjectMemoryService(store)
