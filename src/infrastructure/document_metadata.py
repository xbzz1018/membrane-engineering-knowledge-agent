"""Authorized callers declare business metadata with provenance and document CAS."""

from datetime import UTC, datetime

from sqlalchemy import and_, delete, insert, select

from src.domain.document_search import DocumentBusinessMetadata
from src.infrastructure.database import document_business_metadata, documents


async def declare_metadata(store, document_id: str, metadata: DocumentBusinessMetadata, actor: str) -> dict:
    now = datetime.now(UTC)
    async with store.session_factory() as session:
        updated = await session.execute(documents.update().where(and_(
            documents.c.id == document_id, documents.c.lock_version == metadata.expected_lock_version,
        )).values(lock_version=documents.c.lock_version + 1, updated_at=now))
        if not updated.rowcount:
            raise ValueError("资料版本已变化，请刷新后重试")
        values = metadata.model_dump(exclude={"expected_lock_version"})
        values.update(document_id=document_id, declared_by=actor, updated_at=now)
        await session.execute(delete(document_business_metadata).where(
            document_business_metadata.c.document_id == document_id,
        ))
        await session.execute(insert(document_business_metadata).values(**values))
        await session.commit()
    return {**values, "lock_version": metadata.expected_lock_version + 1, "provenance": "user_declared"}


async def get_metadata(store, document_id: str) -> dict | None:
    async with store.session_factory() as session:
        row = (await session.execute(select(document_business_metadata).where(
            document_business_metadata.c.document_id == document_id,
        ))).mappings().first()
        return {**dict(row), "provenance": "user_declared"} if row else None
