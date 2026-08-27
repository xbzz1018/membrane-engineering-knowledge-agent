"""Exercise and verify every Full-mode storage backend without printing secrets or model content."""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from pathlib import Path

import httpx
from minio import Minio
from neo4j import AsyncGraphDatabase
from pymilvus import MilvusClient
from redis.asyncio import Redis
from sqlalchemy import func, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core.config import get_settings
from src.engineering.storage import SessionFactory, cases, documents, memory_items
from src.main import app


async def main() -> None:
    settings = get_settings()
    if settings.RUNTIME_MODE.lower() != "full":
        raise RuntimeError("validate_full_runtime.py requires RUNTIME_MODE=full")
    suffix = uuid.uuid4().hex[:12]
    user_id = f"full-user-{suffix}"
    session_id = f"full-session-{suffix}"
    filename = f"full-runtime-{suffix}.pdf"
    fixture = Path("data/fixtures/documents/synthetic-membrane-document-01.pdf")

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=120) as client:
            uploaded = await client.post(
                "/api/v1/documents/upload",
                files={"file": (filename, fixture.read_bytes(), "application/pdf")},
            )
            uploaded.raise_for_status()
            document_id = uploaded.json()["document_id"]
            indexed = await client.post(f"/api/v1/documents/{document_id}/index")
            indexed.raise_for_status()
            if indexed.json()["chunks"] < 1:
                raise AssertionError("Full-mode document indexing produced no chunks")

            first_chat = await client.post(
                "/api/v1/chat",
                json={
                    "user_id": user_id,
                    "session_id": session_id,
                    "message": f"请记住我们的资料包文件是 {filename}",
                },
            )
            first_chat.raise_for_status()
            second_chat = await client.post(
                "/api/v1/chat",
                json={"user_id": user_id, "session_id": session_id, "message": f"检索 {filename}"},
            )
            second_chat.raise_for_status()
            sources = second_chat.json()["sources"]
            document_sources = [item for item in sources if item["source_type"] == "document"]
            if not document_sources:
                raise AssertionError("Full-mode chat returned no document evidence")
            retrieval_backends = {
                detail["backend"] for item in document_sources for detail in item.get("retrieval", [])
            }

            memories = await client.get(f"/api/v1/memories/{user_id}")
            memories.raise_for_status()
            if len(memories.json()) != 1:
                raise AssertionError("Long-term memory was not persisted")
            readiness = await client.get("/health/deps")
            readiness.raise_for_status()
            health = readiness.json()
            if health["status"] != "ok":
                raise AssertionError(f"Full readiness is not ok: {health}")

        async with SessionFactory() as session:
            case_count = await session.scalar(select(func.count()).select_from(cases))
            document_count = await session.scalar(select(func.count()).select_from(documents))
            memory_count = await session.scalar(
                select(func.count()).select_from(memory_items).where(memory_items.c.user_id == user_id)
            )

        redis = Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            password=settings.REDIS_PASSWORD or None,
            db=settings.REDIS_DB,
            decode_responses=True,
        )
        try:
            short_messages = await redis.llen(f"membrane:short:{user_id}:{session_id}")
            checkpoint_keys = [
                key async for key in redis.scan_iter(
                    match=f"{settings.REDIS_CHECKPOINT_PREFIX}:{user_id}:{session_id}:*"
                )
            ]
        finally:
            await redis.aclose()

        minio = Minio(
            settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE,
        )
        minio_object = f"documents/{document_id}/{filename}"
        minio_stat = await asyncio.to_thread(minio.stat_object, settings.MINIO_BUCKET, minio_object)

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
                filter=f'user_id == "{user_id}"',
                output_fields=["id"],
                limit=100,
            )
        finally:
            milvus.close()

        driver = AsyncGraphDatabase.driver(
            settings.NEO4J_URI,
            auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
        )
        try:
            async with driver.session() as session:
                record = await (
                    await session.run(
                        "MATCH (p:Project)-[r]->() RETURN count(DISTINCT p) AS projects, count(r) AS relationships"
                    )
                ).single()
                graph_projects = record["projects"]
                graph_relationships = record["relationships"]
        finally:
            await driver.close()

        summary = {
            "postgresql": {
                "cases": case_count,
                "documents": document_count,
                "user_memories": memory_count,
            },
            "redis": {"short_messages": short_messages, "checkpoint_keys": len(checkpoint_keys)},
            "minio": {"object_size": minio_stat.size},
            "milvus": {
                "document_vectors": len(document_vectors),
                "memory_vectors": len(memory_vectors),
            },
            "neo4j": {"projects": graph_projects, "relationships": graph_relationships},
            "retrieval_backends": sorted(retrieval_backends),
            "health": health["status"],
        }
        required = [
            case_count >= 205,
            document_count >= 1,
            memory_count == 1,
            short_messages >= 4,
            len(checkpoint_keys) >= 1,
            minio_stat.size > 0,
            len(document_vectors) >= 1,
            len(memory_vectors) == 1,
            graph_projects >= 205,
            graph_relationships >= 615,
            "milvus" in retrieval_backends,
        ]
        if not all(required):
            raise AssertionError(f"Full runtime validation failed: {summary}")
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
