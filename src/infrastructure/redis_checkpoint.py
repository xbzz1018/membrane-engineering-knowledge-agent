from __future__ import annotations

import asyncio
import base64
import json
import time
from collections.abc import AsyncIterator, Sequence
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    get_checkpoint_id,
)
from redis.asyncio import Redis

from src.core.config import Settings, get_settings


class RedisCheckpointSaver(BaseCheckpointSaver):
    """Minimal async LangGraph checkpoint saver backed by Redis."""

    def __init__(self, settings: Settings | None = None):
        super().__init__()
        self.settings = settings or get_settings()
        self.prefix = self.settings.REDIS_CHECKPOINT_PREFIX
        self.redis = Redis(
            host=self.settings.REDIS_HOST,
            port=self.settings.REDIS_PORT,
            password=self.settings.REDIS_PASSWORD or None,
            db=self.settings.REDIS_DB,
            decode_responses=False,
        )

    @staticmethod
    def _config_parts(config: RunnableConfig) -> tuple[str, str]:
        configurable = config.get("configurable", {})
        thread_id = str(configurable.get("thread_id", ""))
        if not thread_id:
            raise ValueError("LangGraph checkpoint requires configurable.thread_id")
        return thread_id, str(configurable.get("checkpoint_ns", ""))

    def _base(self, thread_id: str, namespace: str) -> str:
        return f"{self.prefix}:{thread_id}:{namespace}"

    def _encode(self, value: Any) -> dict[str, str]:
        kind, payload = self.serde.dumps_typed(value)
        return {"kind": kind, "payload": base64.b64encode(payload).decode("ascii")}

    def _decode(self, value: dict[str, str]) -> Any:
        return self.serde.loads_typed((value["kind"], base64.b64decode(value["payload"])))

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        thread_id, namespace = self._config_parts(config)
        checkpoint_id = checkpoint["id"]
        parent_id = get_checkpoint_id(config)
        base = self._base(thread_id, namespace)
        record = {
            "checkpoint": self._encode(checkpoint),
            "metadata": self._encode(metadata),
            "parent_id": parent_id,
        }
        ttl = self.settings.SHORT_TERM_MEMORY_TTL
        key = f"{base}:item:{checkpoint_id}"
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.set(key, json.dumps(record).encode("utf-8"), ex=ttl)
            pipe.zadd(f"{base}:index", {checkpoint_id: time.time()})
            pipe.expire(f"{base}:index", ttl)
            pipe.set(f"{base}:latest", checkpoint_id, ex=ttl)
            await pipe.execute()
        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": namespace,
                "checkpoint_id": checkpoint_id,
            }
        }

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        thread_id, namespace = self._config_parts(config)
        checkpoint_id = get_checkpoint_id(config)
        if not checkpoint_id:
            return
        entries = [
            {"task_id": task_id, "channel": channel, "value": self._encode(value)}
            for channel, value in writes
        ]
        key = f"{self._base(thread_id, namespace)}:writes:{checkpoint_id}:{task_path}:{task_id}"
        await self.redis.set(
            key,
            json.dumps(entries).encode("utf-8"),
            ex=self.settings.SHORT_TERM_MEMORY_TTL,
        )

    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        thread_id, namespace = self._config_parts(config)
        base = self._base(thread_id, namespace)
        checkpoint_id = get_checkpoint_id(config)
        if not checkpoint_id:
            latest = await self.redis.get(f"{base}:latest")
            checkpoint_id = latest.decode("utf-8") if latest else None
        if not checkpoint_id:
            return None
        raw = await self.redis.get(f"{base}:item:{checkpoint_id}")
        if not raw:
            return None
        record = json.loads(raw)
        stored_config: RunnableConfig = {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": namespace,
                "checkpoint_id": checkpoint_id,
            }
        }
        parent_config = None
        if record.get("parent_id"):
            parent_config = {
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": namespace,
                    "checkpoint_id": record["parent_id"],
                }
            }
        pending_writes = []
        async for key in self.redis.scan_iter(match=f"{base}:writes:{checkpoint_id}:*"):
            encoded = await self.redis.get(key)
            if encoded:
                for item in json.loads(encoded):
                    pending_writes.append((item["task_id"], item["channel"], self._decode(item["value"])))
        return CheckpointTuple(
            stored_config,
            self._decode(record["checkpoint"]),
            self._decode(record["metadata"]),
            parent_config,
            pending_writes,
        )

    async def alist(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[CheckpointTuple]:
        if config is None:
            return
        thread_id, namespace = self._config_parts(config)
        base = self._base(thread_id, namespace)
        checkpoint_ids = await self.redis.zrevrange(f"{base}:index", 0, (limit or 100) - 1)
        for raw_id in checkpoint_ids:
            checkpoint_id = raw_id.decode("utf-8")
            item = await self.aget_tuple({
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": namespace,
                    "checkpoint_id": checkpoint_id,
                }
            })
            if item is not None:
                yield item

    async def adelete_thread(self, thread_id: str) -> None:
        keys = [key async for key in self.redis.scan_iter(match=f"{self.prefix}:{thread_id}:*")]
        if keys:
            await self.redis.delete(*keys)

    async def aclose(self) -> None:
        await self.redis.aclose()


_checkpoint_savers: dict[int, RedisCheckpointSaver] = {}


def get_redis_checkpointer() -> RedisCheckpointSaver:
    try:
        key = id(asyncio.get_running_loop())
    except RuntimeError:
        key = 0
    if key not in _checkpoint_savers:
        _checkpoint_savers[key] = RedisCheckpointSaver()
    return _checkpoint_savers[key]


async def close_redis_checkpointers() -> None:
    savers = list(_checkpoint_savers.values())
    _checkpoint_savers.clear()
    for saver in savers:
        await saver.aclose()


async def purge_legacy_short_memory(settings: Settings | None = None) -> int:
    """Remove the retired duplicate Redis chat-list namespace."""
    config = settings or get_settings()
    client = Redis(
        host=config.REDIS_HOST,
        port=config.REDIS_PORT,
        password=config.REDIS_PASSWORD or None,
        db=config.REDIS_DB,
        decode_responses=False,
    )
    try:
        keys = [key async for key in client.scan_iter(match="membrane:short:*")]
        if keys:
            await client.delete(*keys)
        return len(keys)
    finally:
        await client.aclose()
