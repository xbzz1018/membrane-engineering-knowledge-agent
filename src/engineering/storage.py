from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    and_,
    delete,
    insert,
    select,
)
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from src.core.config import get_settings

settings = get_settings()
metadata = MetaData()

documents = Table(
    "documents", metadata,
    Column("id", String(64), primary_key=True),
    Column("filename", String(512), nullable=False),
    Column("content_type", String(128), nullable=False),
    Column("stored_path", Text, nullable=False),
    Column("version", Integer, nullable=False, default=1),
    Column("parser", String(32), nullable=False, default="basic"),
    Column("status", String(32), nullable=False, default="uploaded"),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

document_chunks = Table(
    "document_chunks", metadata,
    Column("id", String(64), primary_key=True),
    Column("document_id", String(64), nullable=False),
    Column("page_number", Integer, nullable=False, default=1),
    Column("chunk_index", Integer, nullable=False),
    Column("text", Text, nullable=False),
)

cases = Table(
    "engineering_cases", metadata,
    Column("id", String(128), primary_key=True),
    Column("payload", Text, nullable=False),
)

specs = Table(
    "material_specs", metadata,
    Column("id", String(128), primary_key=True),
    Column("payload", Text, nullable=False),
)

prices = Table(
    "price_records", metadata,
    Column("id", String(128), primary_key=True),
    Column("payload", Text, nullable=False),
)

conversations = Table(
    "conversations", metadata,
    Column("id", String(128), primary_key=True),
    Column("user_id", String(64), nullable=False),
    Column("session_id", String(128), nullable=False),
    Column("role", String(16), nullable=False),
    Column("content", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

memory_items = Table(
    "memory_items", metadata,
    Column("id", String(128), primary_key=True),
    Column("user_id", String(64), nullable=False),
    Column("kind", String(32), nullable=False),
    Column("content", Text, nullable=False),
    Column("source", String(32), nullable=False, default="user_confirmed"),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

outbox_events = Table(
    "outbox_events", metadata,
    Column("id", String(128), primary_key=True),
    Column("event_type", String(128), nullable=False),
    Column("aggregate_id", String(128), nullable=False),
    Column("payload", Text, nullable=False),
    Column("topic", String(256), nullable=False, default=""),
    Column("publish_attempts", Integer, nullable=False, default=0),
    Column("last_error", Text, nullable=True),
    Column("published_at", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

inbox_events = Table(
    "inbox_events", metadata,
    Column("event_id", String(128), primary_key=True),
    Column("consumer", String(128), primary_key=True),
    Column("status", String(32), nullable=False, default="processing"),
    Column("attempts", Integer, nullable=False, default=1),
    Column("payload", Text, nullable=False, default="{}"),
    Column("last_error", Text, nullable=True),
    Column("processed_at", DateTime(timezone=True), nullable=True),
)

batch_imports = Table(
    "batch_imports", metadata,
    Column("id", String(128), primary_key=True),
    Column("status", String(32), nullable=False),
    Column("document_count", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

package_reviews = Table(
    "package_reviews", metadata,
    Column("id", String(128), primary_key=True),
    Column("user_id", String(64), nullable=False),
    Column("project_id", String(128), nullable=False),
    Column("question", Text, nullable=False),
    Column("status", String(32), nullable=False),
    Column("engine", String(32), nullable=False),
    Column("report", Text, nullable=False),
    Column("conflicts", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

package_review_evidence = Table(
    "package_review_evidence", metadata,
    Column("id", String(128), primary_key=True),
    Column("review_id", String(128), nullable=False),
    Column("source_id", String(256), nullable=False),
    Column("payload", Text, nullable=False),
)


def _build_engine() -> AsyncEngine:
    url = settings.resolved_database_url
    kwargs: dict[str, Any] = {"echo": False, "pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_async_engine(url, **kwargs)


engine = _build_engine()
SessionFactory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def _now() -> datetime:
    return datetime.now(UTC)


def _terms(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]{2,}", text.lower())


def _score(query: str, value: str) -> int:
    terms = _terms(query)
    haystack = value.lower()
    return sum(haystack.count(term) for term in terms)


def _fuse_ranked(
    groups: list[tuple[str, float, list[dict[str, Any]]]],
    key_field: str,
    limit: int,
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    scores: dict[str, float] = {}
    for backend, weight, rows in groups:
        for rank, row in enumerate(rows, 1):
            key = str(row.get(key_field, ""))
            if not key:
                continue
            item = merged.setdefault(key, dict(row))
            retrieval = item.setdefault("retrieval", [])
            existing = row.get("retrieval") or [{"backend": backend, "rank": rank, "score": row.get("raw_score", 0)}]
            for detail in existing:
                if detail not in retrieval:
                    retrieval.append(detail)
            scores[key] = scores.get(key, 0.0) + weight / (60 + rank)
    for key, item in merged.items():
        item["fusion_score"] = round(scores[key], 8)
        item["fusion_method"] = "weighted_rrf(k=60)"
    return sorted(merged.values(), key=lambda row: row["fusion_score"], reverse=True)[:limit]


class EngineeringStorage:
    def __init__(self, session_factory=SessionFactory):
        self.session_factory = session_factory
        self.settings = settings

    async def init(self) -> None:
        if settings.RUNTIME_MODE.lower() == "local":
            (settings.data_path / "../runtime").resolve().mkdir(parents=True, exist_ok=True)
            settings.upload_path.mkdir(parents=True, exist_ok=True)
        async with engine.begin() as conn:
            await conn.run_sync(metadata.create_all)

    async def close(self) -> None:
        await engine.dispose()

    async def add_document(
        self,
        filename: str,
        content_type: str,
        content: bytes,
        parser: str,
    ) -> dict[str, Any]:
        document_id = uuid.uuid4().hex
        if settings.RUNTIME_MODE.lower() == "full":
            from src.engineering.full_backends import get_full_backends

            stored_path = await get_full_backends().store_document(document_id, filename, content_type, content)
        else:
            path = settings.upload_path / f"{document_id}_{Path(filename).name}"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            stored_path = str(path)
        row = {
            "id": document_id,
            "filename": filename,
            "content_type": content_type or "application/octet-stream",
            "stored_path": stored_path,
            "version": 1,
            "parser": parser,
            "status": "uploaded",
            "created_at": _now(),
        }
        async with self.session_factory() as session:
            await session.execute(insert(documents).values(**row))
            await session.commit()
        return row

    async def resolve_document_path(self, row: dict[str, Any]) -> Path:
        if settings.RUNTIME_MODE.lower() == "full":
            from src.engineering.full_backends import get_full_backends

            return await get_full_backends().materialize_document(
                row["stored_path"], row["id"], row["filename"],
            )
        return Path(row["stored_path"])

    async def get_document(self, document_id: str) -> dict[str, Any] | None:
        async with self.session_factory() as session:
            result = await session.execute(select(documents).where(documents.c.id == document_id))
            row = result.mappings().first()
            return dict(row) if row else None

    async def list_documents(self, document_ids: list[str] | None = None) -> list[dict[str, Any]]:
        async with self.session_factory() as session:
            query = select(documents)
            if document_ids:
                query = query.where(documents.c.id.in_(document_ids))
            result = await session.execute(query)
            return [dict(row) for row in result.mappings().all()]

    async def save_chunks(self, document_id: str, chunks: list[dict[str, Any]], parser: str) -> int:
        async with self.session_factory() as session:
            await session.execute(delete(document_chunks).where(document_chunks.c.document_id == document_id))
            values = [
                {
                    "id": f"{document_id}:{item['chunk_index']}",
                    "document_id": document_id,
                    "page_number": int(item.get("page_number", 1)),
                    "chunk_index": int(item["chunk_index"]),
                    "text": item["text"],
                }
                for item in chunks
            ]
            if values:
                await session.execute(insert(document_chunks), values)
            await session.execute(
                documents.update().where(documents.c.id == document_id).values(status="indexed", parser=parser)
            )
            await session.commit()
        if settings.RUNTIME_MODE.lower() == "full":
            from src.engineering.full_backends import get_full_backends

            document = await self.get_document(document_id)
            if document is None:
                raise RuntimeError(f"Document disappeared after indexing: {document_id}")
            await get_full_backends().index_document(document, chunks)
        return len(values)

    async def search_chunks(self, query: str, limit: int = 8) -> list[dict[str, Any]]:
        async with self.session_factory() as session:
            result = await session.execute(
                select(
                    document_chunks,
                    documents.c.filename,
                    documents.c.version,
                    documents.c.created_at,
                ).select_from(document_chunks.join(documents, document_chunks.c.document_id == documents.c.id))
            )
            rows = [dict(row) for row in result.mappings().all()]
        def score(row: dict[str, Any]) -> int:
            return (_score(query, row["filename"]) * 4) + _score(query, row["text"])

        ranked = sorted(rows, key=score, reverse=True)
        lexical = [row for row in ranked if score(row) > 0][:limit]
        for rank, row in enumerate(lexical, 1):
            row["raw_score"] = score(row)
            row["retrieval"] = [{
                "backend": "postgresql" if settings.RUNTIME_MODE.lower() == "full" else "sqlite",
                "rank": rank,
                "score": score(row),
            }]
        if settings.RUNTIME_MODE.lower() != "full":
            return lexical
        from src.engineering.full_backends import get_full_backends

        vector = await get_full_backends().search_documents(query, limit=limit)
        return _fuse_ranked(
            [("postgresql", 1.0, lexical), ("milvus", 1.3, vector)],
            "id",
            limit,
        )

    async def list_document_chunks(self, document_id: str, limit: int = 100) -> list[dict[str, Any]]:
        async with self.session_factory() as session:
            result = await session.execute(
                select(
                    document_chunks,
                    documents.c.filename,
                    documents.c.version,
                    documents.c.created_at,
                )
                .select_from(document_chunks.join(documents, document_chunks.c.document_id == documents.c.id))
                .where(document_chunks.c.document_id == document_id)
                .order_by(document_chunks.c.chunk_index)
                .limit(limit)
            )
            return [dict(row) for row in result.mappings().all()]

    async def count_document_chunks(self, document_id: str) -> int:
        async with self.session_factory() as session:
            result = await session.execute(
                select(document_chunks.c.id).where(document_chunks.c.document_id == document_id)
            )
            return len(result.all())

    async def check_connection(self) -> None:
        async with self.session_factory() as session:
            await session.execute(select(1))

    async def _search_payload_table(self, table: Table, query: str, limit: int) -> list[dict[str, Any]]:
        async with self.session_factory() as session:
            result = await session.execute(select(table))
            rows = [json.loads(row["payload"]) for row in result.mappings().all()]
        def score(row: dict[str, Any]) -> int:
            return _score(query, json.dumps(row, ensure_ascii=False))

        ranked = sorted(rows, key=score, reverse=True)
        matched = [row for row in ranked if score(row) > 0][:limit]
        backend = "postgresql" if settings.RUNTIME_MODE.lower() == "full" else "sqlite"
        for rank, row in enumerate(matched, 1):
            row["raw_score"] = score(row)
            row["retrieval"] = [{"backend": backend, "rank": rank, "score": score(row)}]
        return matched

    async def search_cases(self, query: str, limit: int = 6) -> list[dict[str, Any]]:
        relational = await self._search_payload_table(cases, query, limit)
        if settings.RUNTIME_MODE.lower() != "full":
            return relational
        from src.engineering.full_backends import get_full_backends

        graph = await get_full_backends().search_graph_cases(query, limit)
        return _fuse_ranked(
            [("postgresql", 1.0, relational), ("neo4j", 1.15, graph)],
            "case_id",
            limit,
        )

    async def search_specs(self, query: str, limit: int = 8) -> list[dict[str, Any]]:
        return await self._search_payload_table(specs, query, limit)

    async def search_prices(self, query: str, limit: int = 8) -> list[dict[str, Any]]:
        return await self._search_payload_table(prices, query, limit)

    async def seed_payloads(self, table: Table, rows: list[dict[str, Any]], key: str) -> int:
        if not rows:
            return 0
        async with self.session_factory() as session:
            existing = await session.execute(select(table.c.id))
            existing_ids = {row[0] for row in existing.all()}
            values = [
                {"id": str(row.get(key) or uuid.uuid4().hex), "payload": json.dumps(row, ensure_ascii=False)}
                for row in rows
                if str(row.get(key) or "") not in existing_ids
            ]
            if values:
                await session.execute(insert(table), values)
                await session.commit()
            return len(values)

    async def append_message(self, user_id: str, session_id: str, role: str, content: str) -> None:
        async with self.session_factory() as session:
            await session.execute(insert(conversations).values(
                id=uuid.uuid4().hex, user_id=user_id, session_id=session_id,
                role=role, content=content[:8000], created_at=_now(),
            ))
            await session.commit()

    async def save_memory(self, user_id: str, content: str, kind: str = "project_context") -> str:
        memory_id = uuid.uuid4().hex
        created_at = _now()
        async with self.session_factory() as session:
            await session.execute(insert(memory_items).values(
                id=memory_id, user_id=user_id, kind=kind,
                content=content[:2000], source="user_confirmed", created_at=created_at,
            ))
            await session.commit()
        if settings.RUNTIME_MODE.lower() == "full":
            from src.engineering.full_backends import get_full_backends

            await get_full_backends().index_memory(
                memory_id, user_id, kind, content[:2000], created_at.isoformat(),
            )
        return memory_id

    async def search_memory(self, user_id: str, query: str, limit: int = 5) -> list[str]:
        if settings.RUNTIME_MODE.lower() == "full":
            from src.engineering.full_backends import get_full_backends

            return await get_full_backends().search_memories(user_id, query, limit)
        async with self.session_factory() as session:
            result = await session.execute(select(memory_items).where(memory_items.c.user_id == user_id))
            rows = [dict(row) for row in result.mappings().all()]
        ranked = sorted(rows, key=lambda row: _score(query, row["content"]), reverse=True)
        return [row["content"] for row in ranked if _score(query, row["content"]) > 0][:limit]

    async def list_memories(self, user_id: str) -> list[dict[str, Any]]:
        async with self.session_factory() as session:
            result = await session.execute(
                select(memory_items)
                .where(memory_items.c.user_id == user_id)
                .order_by(memory_items.c.created_at.desc())
            )
            return [dict(row) for row in result.mappings().all()]

    async def delete_memory(self, user_id: str, memory_id: str) -> bool:
        async with self.session_factory() as session:
            result = await session.execute(
                delete(memory_items).where(and_(
                    memory_items.c.id == memory_id,
                    memory_items.c.user_id == user_id,
                ))
            )
            await session.commit()
            deleted = bool(result.rowcount)
        if deleted and settings.RUNTIME_MODE.lower() == "full":
            from src.engineering.full_backends import get_full_backends

            await get_full_backends().delete_memory(memory_id)
        return deleted

    async def add_outbox_event(self, envelope: dict[str, Any], topic: str) -> str:
        event_id = str(envelope["event_id"])
        async with self.session_factory() as session:
            await session.execute(insert(outbox_events).values(
                id=event_id,
                event_type=envelope["event_type"],
                aggregate_id=envelope["aggregate_id"],
                payload=json.dumps(envelope, ensure_ascii=False),
                topic=topic,
                publish_attempts=0,
                created_at=_now(),
            ))
            await session.commit()
        return event_id

    async def create_batch_import(self, document_ids: list[str], topic_prefix: str) -> dict[str, Any]:
        from src.events.kafka_events import EventEnvelope

        batch_id = uuid.uuid4().hex
        envelopes = [
            EventEnvelope.create(
                event_type="document.ingest.requested",
                aggregate_type="document",
                aggregate_id=document_id,
                payload={"document_id": document_id, "batch_id": batch_id},
            ).model_dump(mode="json")
            for document_id in document_ids
        ]
        async with self.session_factory() as session:
            known = await session.execute(select(documents.c.id).where(documents.c.id.in_(document_ids)))
            known_ids = {row[0] for row in known.all()}
            missing = sorted(set(document_ids) - known_ids)
            if missing:
                raise ValueError(f"Documents not found: {', '.join(missing)}")
            await session.execute(insert(batch_imports).values(
                id=batch_id,
                status="accepted",
                document_count=len(document_ids),
                created_at=_now(),
            ))
            await session.execute(insert(outbox_events), [
                {
                    "id": envelope["event_id"],
                    "event_type": envelope["event_type"],
                    "aggregate_id": envelope["aggregate_id"],
                    "payload": json.dumps(envelope, ensure_ascii=False),
                    "topic": f"{topic_prefix}.{envelope['event_type']}",
                    "publish_attempts": 0,
                    "created_at": _now(),
                }
                for envelope in envelopes
            ])
            await session.commit()
        return {"batch_id": batch_id, "event_ids": [item["event_id"] for item in envelopes]}

    async def list_pending_outbox(self, limit: int = 100) -> list[dict[str, Any]]:
        async with self.session_factory() as session:
            result = await session.execute(
                select(outbox_events)
                .where(outbox_events.c.published_at.is_(None))
                .order_by(outbox_events.c.created_at)
                .limit(limit)
            )
            return [dict(row) for row in result.mappings().all()]

    async def get_outbox_event(self, event_id: str) -> dict[str, Any] | None:
        async with self.session_factory() as session:
            result = await session.execute(select(outbox_events).where(outbox_events.c.id == event_id))
            row = result.mappings().first()
            return dict(row) if row else None

    async def mark_outbox_published(self, event_id: str) -> None:
        async with self.session_factory() as session:
            await session.execute(
                outbox_events.update()
                .where(outbox_events.c.id == event_id)
                .values(
                    published_at=_now(),
                    publish_attempts=outbox_events.c.publish_attempts + 1,
                    last_error=None,
                )
            )
            await session.commit()

    async def mark_outbox_failed(self, event_id: str, error_type: str) -> None:
        async with self.session_factory() as session:
            await session.execute(
                outbox_events.update()
                .where(outbox_events.c.id == event_id)
                .values(
                    publish_attempts=outbox_events.c.publish_attempts + 1,
                    last_error=error_type[:256],
                )
            )
            await session.commit()

    async def begin_inbox_event(self, envelope: dict[str, Any], consumer: str) -> bool:
        event_id = str(envelope["event_id"])
        async with self.session_factory() as session:
            existing = await session.execute(select(inbox_events).where(and_(
                inbox_events.c.event_id == event_id,
                inbox_events.c.consumer == consumer,
            )))
            row = existing.mappings().first()
            if row and row["status"] == "processed":
                return False
            if row:
                await session.execute(
                    inbox_events.update()
                    .where(and_(inbox_events.c.event_id == event_id, inbox_events.c.consumer == consumer))
                    .values(
                        status="processing",
                        attempts=inbox_events.c.attempts + 1,
                        last_error=None,
                    )
                )
            else:
                await session.execute(insert(inbox_events).values(
                    event_id=event_id,
                    consumer=consumer,
                    status="processing",
                    attempts=1,
                    payload=json.dumps(envelope, ensure_ascii=False),
                ))
            await session.commit()
            return True

    async def complete_inbox_event(self, event_id: str, consumer: str) -> None:
        async with self.session_factory() as session:
            await session.execute(
                inbox_events.update()
                .where(and_(inbox_events.c.event_id == event_id, inbox_events.c.consumer == consumer))
                .values(status="processed", processed_at=_now(), last_error=None)
            )
            await session.commit()

    async def fail_inbox_event(self, event_id: str, consumer: str, error_type: str) -> None:
        async with self.session_factory() as session:
            await session.execute(
                inbox_events.update()
                .where(and_(inbox_events.c.event_id == event_id, inbox_events.c.consumer == consumer))
                .values(status="failed", last_error=error_type[:256])
            )
            await session.commit()

    async def save_package_review(
        self,
        result: dict[str, Any],
        *,
        user_id: str,
        project_id: str,
        question: str,
    ) -> None:
        now = _now()
        review_id = result["review_id"]
        async with self.session_factory() as session:
            await session.execute(delete(package_review_evidence).where(
                package_review_evidence.c.review_id == review_id
            ))
            await session.execute(delete(package_reviews).where(package_reviews.c.id == review_id))
            await session.execute(insert(package_reviews).values(
                id=review_id,
                user_id=user_id,
                project_id=project_id,
                question=question,
                status=result["status"],
                engine=result["engine"],
                report=result.get("report", ""),
                conflicts=json.dumps(result.get("conflicts", []), ensure_ascii=False),
                created_at=now,
                updated_at=now,
            ))
            evidence = [
                {
                    "id": f"{review_id}:{index}",
                    "review_id": review_id,
                    "source_id": str(source.get("source_id", index)),
                    "payload": json.dumps(source, ensure_ascii=False),
                }
                for index, source in enumerate(result.get("sources", []))
            ]
            if evidence:
                await session.execute(insert(package_review_evidence), evidence)
            await session.commit()

    async def get_package_review(self, review_id: str) -> dict[str, Any] | None:
        async with self.session_factory() as session:
            review_result = await session.execute(
                select(package_reviews).where(package_reviews.c.id == review_id)
            )
            row = review_result.mappings().first()
            if not row:
                return None
            evidence_result = await session.execute(
                select(package_review_evidence)
                .where(package_review_evidence.c.review_id == review_id)
                .order_by(package_review_evidence.c.id)
            )
            sources = [json.loads(item["payload"]) for item in evidence_result.mappings().all()]
            return {
                "review_id": row["id"],
                "status": row["status"],
                "engine": row["engine"],
                "report": row["report"],
                "sources": sources,
                "conflicts": json.loads(row["conflicts"]),
                "created_at": row["created_at"].isoformat(),
            }

    async def update_package_review_status(self, review_id: str, status: str) -> bool:
        async with self.session_factory() as session:
            result = await session.execute(
                package_reviews.update()
                .where(package_reviews.c.id == review_id)
                .values(status=status, updated_at=_now())
            )
            await session.commit()
            return bool(result.rowcount)


storage = EngineeringStorage()
