from __future__ import annotations

import time

from src.core.config import get_settings
from src.engineering.storage import EngineeringStorage

_short_term: dict[str, tuple[float, list[dict]]] = {}


class MemoryService:
    def __init__(self, store: EngineeringStorage):
        self.store = store
        self.settings = get_settings()

    async def load_short(self, user_id: str, session_id: str) -> list[dict]:
        key = f"{user_id}:{session_id}"
        item = _short_term.get(key)
        if not item or item[0] <= time.time():
            _short_term.pop(key, None)
            return []
        return item[1][-10:]

    async def append_short(self, user_id: str, session_id: str, role: str, content: str) -> list[dict]:
        key = f"{user_id}:{session_id}"
        history = await self.load_short(user_id, session_id)
        history.append({"role": role, "content": content[:1200]})
        _short_term[key] = (time.time() + self.settings.SHORT_TERM_MEMORY_TTL, history[-10:])
        return history[-10:]

    async def maybe_save_long(self, user_id: str, message: str) -> None:
        markers = ("记住", "以后", "常用", "偏好", "项目是", "我们公司")
        if any(marker in message for marker in markers) and self.settings.LONG_TERM_MEMORY_ENABLED:
            await self.store.save_memory(user_id, message, kind="project_context")

    async def search_long(self, user_id: str, query: str) -> list[str]:
        if not self.settings.LONG_TERM_MEMORY_ENABLED:
            return []
        return await self.store.search_memory(user_id, query)


def get_memory_service(store: EngineeringStorage) -> MemoryService:
    return MemoryService(store)
