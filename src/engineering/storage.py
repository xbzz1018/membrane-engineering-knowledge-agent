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
    Column("published_at", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

inbox_events = Table(
    "inbox_events", metadata,
    Column("event_id", String(128), primary_key=True),
    Column("consumer", String(128), primary_key=True),
    Column("processed_at", DateTime(timezone=True), nullable=False),
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
        path = settings.upload_path / f"{document_id}_{Path(filename).name}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        row = {
            "id": document_id,
            "filename": filename,
            "content_type": content_type or "application/octet-stream",
            "stored_path": str(path),
            "version": 1,
            "parser": parser,
            "status": "uploaded",
            "created_at": _now(),
        }
        async with self.session_factory() as session:
            await session.execute(insert(documents).values(**row))
            await session.commit()
        return row

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
        return len(values)

    async def search_chunks(self, query: str, limit: int = 8) -> list[dict[str, Any]]:
        async with self.session_factory() as session:
            result = await session.execute(select(document_chunks))
            rows = [dict(row) for row in result.mappings().all()]
        ranked = sorted(rows, key=lambda row: _score(query, row["text"]), reverse=True)
        return [row for row in ranked if _score(query, row["text"]) > 0][:limit]

    async def _search_payload_table(self, table: Table, query: str, limit: int) -> list[dict[str, Any]]:
        async with self.session_factory() as session:
            result = await session.execute(select(table))
            rows = [json.loads(row["payload"]) for row in result.mappings().all()]
        ranked = sorted(rows, key=lambda row: _score(query, json.dumps(row, ensure_ascii=False)), reverse=True)
        return [row for row in ranked if _score(query, json.dumps(row, ensure_ascii=False)) > 0][:limit]

    async def search_cases(self, query: str, limit: int = 6) -> list[dict[str, Any]]:
        return await self._search_payload_table(cases, query, limit)

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

    async def save_memory(self, user_id: str, content: str, kind: str = "project_context") -> None:
        async with self.session_factory() as session:
            await session.execute(insert(memory_items).values(
                id=uuid.uuid4().hex, user_id=user_id, kind=kind,
                content=content[:2000], source="user_confirmed", created_at=_now(),
            ))
            await session.commit()

    async def search_memory(self, user_id: str, query: str, limit: int = 5) -> list[str]:
        async with self.session_factory() as session:
            result = await session.execute(select(memory_items).where(memory_items.c.user_id == user_id))
            rows = [dict(row) for row in result.mappings().all()]
        ranked = sorted(rows, key=lambda row: _score(query, row["content"]), reverse=True)
        return [row["content"] for row in ranked if _score(query, row["content"]) > 0][:limit]

    async def add_outbox_event(self, event_type: str, aggregate_id: str, payload: dict[str, Any]) -> str:
        event_id = uuid.uuid4().hex
        async with self.session_factory() as session:
            await session.execute(insert(outbox_events).values(
                id=event_id, event_type=event_type, aggregate_id=aggregate_id,
                payload=json.dumps(payload, ensure_ascii=False), created_at=_now(),
            ))
            await session.commit()
        return event_id

    async def claim_inbox_event(self, event_id: str, consumer: str) -> bool:
        """Idempotency guard for Kafka consumers."""
        async with self.session_factory() as session:
            existing = await session.execute(select(inbox_events).where(and_(
                inbox_events.c.event_id == event_id,
                inbox_events.c.consumer == consumer,
            )))
            if existing.mappings().first():
                return False
            await session.execute(insert(inbox_events).values(
                event_id=event_id, consumer=consumer, processed_at=_now(),
            ))
            await session.commit()
            return True


storage = EngineeringStorage()
