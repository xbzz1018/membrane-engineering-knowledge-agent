"""Rebuild pgvector indexes after storage or embedding-model changes."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from sqlalchemy import or_, select, text, update

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core.config import get_settings
from src.documents.representations import document_index_model
from src.infrastructure.database import SessionFactory, memory_items, storage
from src.infrastructure.database import documents as documents_table
from src.infrastructure.full_backends import get_full_backends
from src.infrastructure.model_provider import get_model_provider
from src.main import app


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-id", default=get_settings().DEFAULT_PROJECT_ID)
    parser.add_argument("--limit", type=int, default=0, help="0 means every mismatched indexed document")
    args = parser.parse_args()
    settings = get_settings()
    if settings.RUNTIME_MODE.lower() != "full":
        raise RuntimeError("Embedding rebuild requires RUNTIME_MODE=full")
    index_model = document_index_model(get_model_provider(), settings)
    rows: list[dict] = []
    async with app.router.lifespan_context(app):
        document_rows = await storage.list_documents(
            project_id=args.project_id,
            tenant_id=settings.DEFAULT_TENANT_ID,
        )
        async with SessionFactory() as session:
            indexed_vector_ids = set((await session.execute(text(
                "SELECT DISTINCT document_id FROM document_embeddings"
            ))).scalars().all())
        candidates = [
            item
            for item in document_rows
            if item["status"] == "indexed"
            and (
                item.get("embedding_model", "") != index_model
                or item["id"] not in indexed_vector_ids
            )
        ]
        if args.limit > 0:
            candidates = candidates[:args.limit]
        for document in candidates:
            try:
                chunks = await storage.list_document_chunks(document["id"], limit=10_000)
                if not chunks:
                    raise RuntimeError("Indexed document has no Evidence chunks")
                await get_full_backends().index_document(document, chunks)
                async with SessionFactory() as session:
                    await session.execute(update(documents_table).where(
                        documents_table.c.id == document["id"]
                    ).values(embedding_model=index_model))
                    await session.commit()
                count = len(chunks)
                rows.append({"document_id": document["id"], "status": "indexed", "chunks": count})
            except Exception as exc:
                rows.append({
                    "document_id": document["id"],
                    "status": "failed",
                    "error": type(exc).__name__,
                    "detail": str(exc)[:300],
                })
        async with SessionFactory() as session:
            result = await session.execute(select(memory_items).where(
                memory_items.c.tenant_id == settings.DEFAULT_TENANT_ID,
                memory_items.c.status == "confirmed",
                or_(memory_items.c.project_id == args.project_id, memory_items.c.project_id.is_(None)),
            ))
            memories = result.mappings().all()
        memory_failures = 0
        for memory in memories:
            try:
                await get_full_backends().index_memory(
                    memory["id"],
                    memory["user_id"],
                    memory["kind"],
                    memory["content"],
                    memory["created_at"].isoformat(),
                    tenant_id=memory["tenant_id"],
                    project_id=memory["project_id"] or "",
                    scope=memory["scope"],
                )
            except Exception:
                memory_failures += 1
        summary = {
            "project_id": args.project_id,
            "embedding_model": index_model,
            "indexed": sum(item["status"] == "indexed" for item in rows),
            "failed": sum(item["status"] == "failed" for item in rows),
            "skipped": sum(item["status"] == "skipped" for item in rows),
            "confirmed_memories_indexed": len(memories) - memory_failures,
            "memory_failures": memory_failures,
        }
    print(json.dumps(summary, ensure_ascii=False))
    if summary["failed"] or summary["memory_failures"]:
        raise RuntimeError(json.dumps(rows, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
