import asyncio
import uuid

import pytest

from src.infrastructure.database import storage
from src.infrastructure.ingest_claim import IngestOwnershipLost
from src.main import app


def test_crashed_ingest_reclaims_only_newer_attempt_and_fences_old_writes():
    async def run():
        async with app.router.lifespan_context(app):
            doc = await storage.add_document("retry.txt", "text/plain", uuid.uuid4().hex.encode(), "basic")
            did = doc["id"]
            first, second = ("workflow:run:activity", 1), ("workflow:run:activity", 2)
            assert await storage.acquire_document_ingest(did, claim=first)
            assert not await storage.acquire_document_ingest(did, claim=first)
            assert not await storage.acquire_document_ingest(did, claim=("another-run", 2))
            assert await storage.acquire_document_ingest(did, claim=second)
            chunk = [{"chunk_index": 0, "text": "recovered content"}]
            with pytest.raises(IngestOwnershipLost):
                await storage.save_chunks(did, chunk, "basic", claim=first)
            with pytest.raises(IngestOwnershipLost):
                await storage.fail_document(did, "late failure", claim=first)
            assert (await storage.get_document(did))["status"] == "indexing"
            await storage.save_chunks(did, chunk, "basic", claim=second)
            assert (await storage.get_document(did))["status"] == "indexed"
            assert await storage.count_document_chunks(did) == 1
    asyncio.run(run())


def test_failed_attempt_can_retry_but_old_attempt_cannot_reclaim():
    async def run():
        async with app.router.lifespan_context(app):
            doc = await storage.add_document("failed.txt", "text/plain", uuid.uuid4().hex.encode(), "basic")
            assert await storage.acquire_document_ingest(doc["id"], claim=("execution", 1))
            await storage.fail_document(doc["id"], "parser", claim=("execution", 1))
            assert not await storage.acquire_document_ingest(doc["id"], claim=("execution", 1))
            assert await storage.acquire_document_ingest(doc["id"], claim=("execution", 2))
    asyncio.run(run())
