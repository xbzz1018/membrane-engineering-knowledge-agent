"""Fail closed on deployment configuration, then start one container role."""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def validate_configuration(settings) -> None:
    if settings.RUNTIME_MODE.lower() != "full" or not settings.AUTH_ENABLED or not settings.TEMPORAL_ENABLED:
        raise ValueError("Deployment requires Full storage, authentication and Temporal")
    if settings.APP_DEBUG or settings.TRACE_CONTENT:
        raise ValueError("Deployment must disable APP_DEBUG and TRACE_CONTENT")
    if settings.EMBEDDING_DIMENSIONS != 1024:
        raise ValueError("Migration 0013 uses vector(1024); another dimension requires a schema migration")
    for key in ("JWT_SECRET", "BOOTSTRAP_ADMIN_PASSWORD", "DB_PASSWORD", "REDIS_PASSWORD", "MINIO_SECRET_KEY"):
        value = getattr(settings, key)
        if len(value) < 24 or value.lower() in {
            "replace-me", "admin-change-me", "local-development-only-change-me",
        }:
            raise ValueError(f"Generate a unique deployment credential for {key} (at least 24 characters)")
    if settings.PARSER_MODE != "mineru":
        raise ValueError("Deployment PDF/OCR must select MinerU; missing MinerU must fail explicitly")
    from src.infrastructure.model_provider import ModelProvider

    provider = ModelProvider(settings)
    provider._embedding_config()  # Check completeness without making a paid network call.
    if settings.MODEL_MODE.lower() == "fake":
        if not settings.EMBEDDING_MODEL.startswith("demo-hash-"):
            raise ValueError("Fake deployment embeddings must use a distinct demo-hash-* model name")
    elif settings.EMBEDDING_MODEL.startswith("demo-hash-"):
        raise ValueError("API embeddings must use the actual model name; reindex old demo vectors")
    if settings.RERANKER_ENABLED and not all((
        settings.RERANKER_API_BASE, settings.RERANKER_API_KEY, settings.RERANKER_MODEL,
    )):
        raise ValueError("Reranker is enabled but its configuration is incomplete")


async def wait_dependencies(settings, *, database_only: bool = False, timeout: float = 240) -> None:
    import httpx
    from redis.asyncio import Redis
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine
    from temporalio.api.workflowservice.v1 import DescribeNamespaceRequest
    from temporalio.client import Client

    engine = create_async_engine(settings.resolved_database_url, connect_args={"timeout": 5})
    redis = Redis(host=settings.REDIS_HOST, port=settings.REDIS_PORT, password=settings.REDIS_PASSWORD,
                  socket_connect_timeout=3, socket_timeout=3)

    async def database():
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

    async def minio():
        scheme = "https" if settings.MINIO_SECURE else "http"
        async with httpx.AsyncClient(timeout=3, trust_env=False) as client:
            response = await client.get(f"{scheme}://{settings.MINIO_ENDPOINT}/minio/health/ready")
            response.raise_for_status()

    async def temporal():
        client = await Client.connect(settings.TEMPORAL_TARGET, namespace=settings.TEMPORAL_NAMESPACE)
        await client.workflow_service.describe_namespace(DescribeNamespaceRequest(namespace=settings.TEMPORAL_NAMESPACE))

    checks = {"postgres": database}
    if not database_only:
        checks.update({"redis": redis.ping, "minio": minio, "temporal-namespace": temporal})
    deadline = time.monotonic() + timeout
    try:
        while checks:
            for name, check in list(checks.items()):
                try:
                    await asyncio.wait_for(check(), timeout=min(8, max(0.01, deadline - time.monotonic())))
                except Exception:
                    if time.monotonic() >= deadline:
                        # Do not print connection strings or dependency exception bodies.
                        raise TimeoutError(f"Deployment dependency unavailable: {', '.join(checks)}") from None
                else:
                    del checks[name]
                    print(f"Deployment dependency ready: {name}", flush=True)
            if checks:
                await asyncio.sleep(min(2, max(0, deadline - time.monotonic())))
    finally:
        await redis.aclose()
        await engine.dispose()


COMMANDS = {
    "migrate": ["-m", "alembic", "upgrade", "head"],
    "api": ["-m", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8080"],
    "worker": ["scripts/run_temporal_worker.py"],
    "mcp": ["-m", "src.mcp.server", "--transport", "streamable-http"],
    "smoke": ["scripts/validate_deployment.py"],
}


def main() -> None:
    from src.core.config import get_settings

    role = sys.argv[1] if len(sys.argv) == 2 else ""
    if role not in COMMANDS:
        raise SystemExit("Usage: entrypoint.py migrate|api|worker|mcp|smoke")
    settings = get_settings()
    try:
        validate_configuration(settings)
        asyncio.run(wait_dependencies(settings, database_only=role == "migrate"))
    except (ValueError, TimeoutError) as exc:
        raise SystemExit(str(exc)) from None
    os.execv(sys.executable, [sys.executable, *COMMANDS[role]])


if __name__ == "__main__":
    main()
