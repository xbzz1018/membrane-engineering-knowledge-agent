from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from src.core.config import Settings, get_settings
from src.engineering.provider import ModelProvider
from src.engineering.storage import EngineeringStorage, storage

Check = Callable[[], Awaitable[None]]


async def _checked(enabled: bool, check: Check, timeout: float) -> dict[str, Any]:
    if not enabled:
        return {"enabled": False, "healthy": None, "detail": "disabled"}
    try:
        await asyncio.wait_for(check(), timeout=timeout)
        return {"enabled": True, "healthy": True, "detail": "reachable"}
    except Exception as exc:
        return {"enabled": True, "healthy": False, "detail": type(exc).__name__}


async def _check_path(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(path.name)


async def _check_redis(settings: Settings) -> None:
    from redis.asyncio import Redis

    client = Redis(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        password=settings.REDIS_PASSWORD or None,
        db=settings.REDIS_DB,
        socket_connect_timeout=settings.HEALTHCHECK_TIMEOUT_SECONDS,
    )
    try:
        await client.ping()
    finally:
        await client.aclose()


async def _check_minio(settings: Settings) -> None:
    from minio import Minio

    client = Minio(
        settings.MINIO_ENDPOINT,
        access_key=settings.MINIO_ACCESS_KEY,
        secret_key=settings.MINIO_SECRET_KEY,
        secure=settings.MINIO_SECURE,
    )
    if not await asyncio.to_thread(client.bucket_exists, settings.MINIO_BUCKET):
        raise FileNotFoundError(settings.MINIO_BUCKET)


async def _check_milvus(settings: Settings) -> None:
    from pymilvus import MilvusClient

    def probe() -> None:
        client = MilvusClient(uri=f"http://{settings.MILVUS_HOST}:{settings.MILVUS_PORT}")
        try:
            client.list_collections()
        finally:
            client.close()

    await asyncio.to_thread(probe)


async def _check_temporal(settings: Settings) -> None:
    from temporalio.client import Client

    await Client.connect(settings.TEMPORAL_TARGET, namespace=settings.TEMPORAL_NAMESPACE)


async def dependency_health(
    settings: Settings | None = None,
    store: EngineeringStorage = storage,
) -> dict[str, Any]:
    config = settings or get_settings()
    timeout = config.HEALTHCHECK_TIMEOUT_SECONDS
    is_full = config.RUNTIME_MODE.lower() == "full"

    async def check_database() -> None:
        await store.check_connection()

    async def check_model() -> None:
        result = await ModelProvider(config).health()
        if not result["healthy"]:
            raise ConnectionError(result["detail"])

    parser_enabled = config.PARSER_MODE.lower() == "mineru"
    checks = {
        "database": await _checked(True, check_database, timeout),
        "model": await _checked(True, check_model, timeout),
        "upload_storage": await _checked(
            True,
            (lambda: _check_minio(config)) if is_full else (lambda: _check_path(config.upload_path)),
            timeout,
        ),
        "mineru": await _checked(
            parser_enabled,
            lambda: _check_path(Path(config.MINERU_EXECUTABLE)),
            timeout,
        ),
        "redis": await _checked(is_full, lambda: _check_redis(config), timeout),
        "minio": await _checked(is_full, lambda: _check_minio(config), timeout),
        "milvus": await _checked(is_full, lambda: _check_milvus(config), timeout),
        "temporal": await _checked(config.TEMPORAL_ENABLED, lambda: _check_temporal(config), timeout),
    }
    healthy = all(item["healthy"] is not False for item in checks.values())
    return {
        "status": "ok" if healthy else "degraded",
        "runtime_mode": config.RUNTIME_MODE,
        "checks": checks,
    }
