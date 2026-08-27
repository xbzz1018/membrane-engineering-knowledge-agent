from __future__ import annotations

import json
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
        if self.settings.RUNTIME_MODE.lower() == "full":
            from redis.asyncio import Redis

            redis = Redis(
                host=self.settings.REDIS_HOST,
                port=self.settings.REDIS_PORT,
                password=self.settings.REDIS_PASSWORD or None,
                db=self.settings.REDIS_DB,
                decode_responses=True,
            )
            try:
                values = await redis.lrange(f"membrane:short:{key}", -10, -1)
                return [json.loads(value) for value in values]
            finally:
                await redis.aclose()
        item = _short_term.get(key)
        if not item or item[0] <= time.time():
            _short_term.pop(key, None)
            return []
        return item[1][-10:]

    async def append_short(self, user_id: str, session_id: str, role: str, content: str) -> list[dict]:
        key = f"{user_id}:{session_id}"
        message = {"role": role, "content": content[:1200]}
        if self.settings.RUNTIME_MODE.lower() == "full":
            from redis.asyncio import Redis

            redis = Redis(
                host=self.settings.REDIS_HOST,
                port=self.settings.REDIS_PORT,
                password=self.settings.REDIS_PASSWORD or None,
                db=self.settings.REDIS_DB,
                decode_responses=True,
            )
            redis_key = f"membrane:short:{key}"
            try:
                async with redis.pipeline(transaction=True) as pipe:
                    pipe.rpush(redis_key, json.dumps(message, ensure_ascii=False))
                    pipe.ltrim(redis_key, -10, -1)
                    pipe.expire(redis_key, self.settings.SHORT_TERM_MEMORY_TTL)
                    await pipe.execute()
                return await self.load_short(user_id, session_id)
            finally:
                await redis.aclose()
        history = await self.load_short(user_id, session_id)
        history.append(message)
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
