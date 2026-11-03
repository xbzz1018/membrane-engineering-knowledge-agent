"""Temporal attempt ownership; all writes fence stale Activity attempts."""

from sqlalchemy import insert, select

from src.infrastructure.database import document_ingest_claims, documents


class IngestOwnershipLost(RuntimeError):
    pass


async def _lock_document(session, document_id: str) -> bool:
    # An UPDATE locks on PostgreSQL and SQLite, unlike SQLite SELECT FOR UPDATE.
    result = await session.execute(documents.update().where(documents.c.id == document_id).values(
        updated_at=documents.c.updated_at,
    ))
    return bool(result.rowcount)


async def guard_claim(session, document_id: str, claim: tuple[str, int]) -> None:
    if not await _lock_document(session, document_id):
        raise IngestOwnershipLost("document no longer exists")
    row = (await session.execute(select(document_ingest_claims).where(
        document_ingest_claims.c.document_id == document_id,
    ))).mappings().first()
    if row is None or (row["execution_id"], row["attempt"]) != tuple(claim):
        raise IngestOwnershipLost("a newer Activity attempt owns this document")


async def acquire_claim(store, document_id: str, claim: tuple[str, int], *, refresh_embedding: bool) -> bool:
    from src.infrastructure.database import _now

    execution_id, attempt = claim
    if not execution_id or attempt < 1:
        raise ValueError("valid Temporal execution and attempt required")
    async with store.session_factory() as session:
        if not await _lock_document(session, document_id):
            return False
        status = await session.scalar(select(documents.c.status).where(documents.c.id == document_id))
        old = (await session.execute(select(document_ingest_claims).where(
            document_ingest_claims.c.document_id == document_id,
        ))).mappings().first()
        ordinary = status in {"uploaded", "failed", "index_failed"} or (refresh_embedding and status == "indexed")
        retry = (status == "indexing" and old is not None
                 and old["execution_id"] == execution_id and attempt > old["attempt"])
        # Even a failed document cannot be reclaimed by an older attempt.
        stale = old is not None and old["execution_id"] == execution_id and attempt <= old["attempt"]
        if stale or not (ordinary or retry):
            return False
        values = {"execution_id": execution_id, "attempt": attempt}
        if old is None:
            await session.execute(insert(document_ingest_claims).values(document_id=document_id, **values))
        else:
            await session.execute(document_ingest_claims.update().where(
                document_ingest_claims.c.document_id == document_id,
            ).values(**values))
        await session.execute(documents.update().where(documents.c.id == document_id).values(
            status="indexing", error_type=None, updated_at=_now(), lock_version=documents.c.lock_version + 1,
        ))
        await session.commit()
        return True
