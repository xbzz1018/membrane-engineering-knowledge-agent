"""Validate the Full storage, JWT, Agent, retrieval, and memory chain without exposing content."""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from pathlib import Path

import httpx
from minio import Minio
from pymilvus import MilvusClient
from redis.asyncio import Redis
from sqlalchemy import func, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core.config import get_settings
from src.engineering.storage import SessionFactory, agent_runs, documents, memory_items
from src.main import app


async def main() -> None:
    settings = get_settings()
    if settings.RUNTIME_MODE.lower() != "full" or settings.MODEL_MODE.lower() != "api":
        raise RuntimeError("Full validation requires RUNTIME_MODE=full and MODEL_MODE=api")
    if settings.TEMPORAL_ENABLED:
        raise RuntimeError("Run Full storage validation with TEMPORAL_ENABLED=false; validate Temporal separately")
    suffix = uuid.uuid4().hex[:12]
    session_id = f"full-session-{suffix}"
    filename = f"full-runtime-{suffix}.pdf"
    version = int(suffix[:6], 16)
    fixture = Path("data/fixtures/documents/synthetic-membrane-document-01.pdf")

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=600) as client:
            headers: dict[str, str] = {}
            if settings.AUTH_ENABLED:
                login = await client.post("/api/v1/auth/login", json={
                    "username": settings.BOOTSTRAP_ADMIN_USERNAME,
                    "password": settings.BOOTSTRAP_ADMIN_PASSWORD,
                })
                login.raise_for_status()
                token_payload = login.json()
                headers["Authorization"] = f"Bearer {token_payload['access_token']}"
                principal = token_payload["principal"]
            else:
                me = await client.get("/api/v1/auth/me")
                me.raise_for_status()
                principal = me.json()

            uploaded = await client.post(
                "/api/v1/documents/upload",
                headers=headers,
                data={"project_id": settings.DEFAULT_PROJECT_ID, "version": str(version)},
                files={"file": (filename, fixture.read_bytes(), "application/pdf")},
            )
            uploaded.raise_for_status()
            uploaded_payload = uploaded.json()
            document_id = uploaded_payload["document_id"]
            indexed = await client.post(f"/api/v1/documents/{document_id}/index", headers=headers)
            indexed.raise_for_status()
            if indexed.json()["chunks"] < 1:
                raise AssertionError("Document indexing produced no chunks")

            first = await client.post("/api/v1/chat", headers=headers, json={
                "project_id": settings.DEFAULT_PROJECT_ID,
                "session_id": session_id,
                "message": f"请记住本项目资料版本是 {version}",
            })
            first.raise_for_status()
            candidates = first.json().get("memory_candidates", [])
            if len(candidates) != 1 or candidates[0]["status"] != "pending":
                raise AssertionError("Chat did not create exactly one pending memory candidate")
            memory_id = candidates[0]["id"]
            confirmed = await client.post(f"/api/v1/memories/{memory_id}/confirm", headers=headers)
            confirmed.raise_for_status()
            second = await client.post("/api/v1/chat", headers=headers, json={
                "project_id": settings.DEFAULT_PROJECT_ID,
                "session_id": session_id,
                "message": f"检索 {filename}",
            })
            second.raise_for_status()
            document_sources = [
                item for item in second.json()["sources"]
                if item["source_type"] == "document" and item["title"] == filename
            ]
            if not document_sources:
                raise AssertionError("Filename retrieval returned no matching document evidence")
            readiness = await client.get("/health/deps")
            readiness.raise_for_status()
            health = readiness.json()
            if health["status"] != "ok":
                raise AssertionError("Full dependency health is not ready")

        async with SessionFactory() as session:
            document_count = await session.scalar(select(func.count()).select_from(documents))
            memory_count = await session.scalar(select(func.count()).select_from(memory_items).where(
                memory_items.c.id == memory_id,
                memory_items.c.status == "confirmed",
            ))
            run_count = await session.scalar(select(func.count()).select_from(agent_runs).where(
                agent_runs.c.user_id == principal["user_id"],
                agent_runs.c.status == "completed",
            ))

        thread_id = (
            f"{principal['tenant_id']}:{principal['user_id']}:"
            f"{settings.DEFAULT_PROJECT_ID}:{session_id}"
        )
        redis = Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            password=settings.REDIS_PASSWORD or None,
            db=settings.REDIS_DB,
            decode_responses=True,
        )
        try:
            checkpoint_keys = [
                key async for key in redis.scan_iter(
                    match=f"{settings.REDIS_CHECKPOINT_PREFIX}:{thread_id}:*"
                )
            ]
            duplicate_short_keys = [key async for key in redis.scan_iter(match="membrane:short:*")]
        finally:
            await redis.aclose()

        minio = Minio(
            settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE,
        )
        object_name = f"documents/{uploaded_payload['sha256']}/v{version}/{filename}"
        object_stat = await asyncio.to_thread(minio.stat_object, settings.MINIO_BUCKET, object_name)

        milvus = MilvusClient(uri=f"http://{settings.MILVUS_HOST}:{settings.MILVUS_PORT}")
        try:
            document_vectors = milvus.query(
                settings.MILVUS_DOCUMENT_COLLECTION,
                filter=f'document_id == "{document_id}"',
                output_fields=["id"],
                limit=100,
            )
            memory_vectors = milvus.query(
                settings.MILVUS_MEMORY_COLLECTION,
                filter=f'id == "{memory_id}"',
                output_fields=["id"],
                limit=10,
            )
        finally:
            milvus.close()

        summary = {
            "postgresql": {
                "documents": document_count,
                "confirmed_memory": memory_count,
                "completed_agent_runs": run_count,
            },
            "redis": {
                "checkpoint_keys": len(checkpoint_keys),
                "duplicate_short_history_keys": len(duplicate_short_keys),
            },
            "minio": {"object_size": object_stat.size},
            "milvus": {
                "document_vectors": len(document_vectors),
                "memory_vectors": len(memory_vectors),
            },
            "health": health["status"],
        }
        required = (
            document_count >= 1,
            memory_count == 1,
            run_count >= 2,
            len(checkpoint_keys) >= 1,
            len(duplicate_short_keys) == 0,
            object_stat.size > 0,
            len(document_vectors) >= 1,
            len(memory_vectors) == 1,
        )
        if not all(required):
            raise AssertionError(f"Full runtime validation failed: {summary}")
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
