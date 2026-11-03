import asyncio
import uuid

import pytest

from scripts.build_retrieval_business_fixture import build
from scripts.run_business_retrieval_eval import aggregate, eligible
from src.domain.document_search import DocumentBusinessMetadata, DocumentSearchFilters
from src.infrastructure.database import settings, storage
from src.infrastructure.document_metadata import declare_metadata
from src.main import app


def test_frozen_fixture_labels_obey_scope_filters_and_have_multiple_relevance():
    data = build()
    corpus = {doc["key"]: doc for doc in data["documents"]}
    assert len(corpus) == 119 and len(data["queries"]) == 30
    assert sum(not query["relevant_document_keys"] for query in data["queries"]) == 7
    assert any(len(query["relevant_document_keys"]) > 1 for query in data["queries"])
    for query in data["queries"]:
        assert all(eligible(corpus[key], query["filters"]) for key in query["relevant_document_keys"])
    filters = {"engineering_model": "PTFE-502", "effective_on": "2026-11-02"}
    for kind in ("near-model", "private", "other-project", "unknown-date"):
        assert not eligible(corpus["PTFE-502-" + kind], filters)


def test_retrieval_failure_counts_as_zero_and_no_answer_is_separate():
    summary = aggregate([
        {"answerable": True, "error": None, "recall_at_10": 1, "rr_at_10": 0.5, "latency_ms": 1},
        {"answerable": True, "error": "Timeout", "latency_ms": 2},
        {"answerable": False, "error": None, "ranked_document_ids": [], "latency_ms": 1},
        {"answerable": False, "error": "Timeout", "ranked_document_ids": [], "latency_ms": 2},
    ])
    assert summary["recall_at_10_all_answerable"] == 0.5
    assert summary["mrr_at_10_all_answerable"] == 0.25
    assert summary["no_answer_empty_return_rate_all"] == 0.5
    assert summary["failures"] == 2


def test_full_exact_only_does_not_require_an_embedding_endpoint(monkeypatch):
    async def run():
        async with app.router.lifespan_context(app):
            doc = await storage.add_document("exact.txt", "text/plain", uuid.uuid4().hex.encode(), "basic")
            await storage.save_chunks(doc["id"], [{"chunk_index": 0, "text": "thickness"}], "basic")
            current = await storage.get_document(doc["id"])
            await declare_metadata(storage, doc["id"], DocumentBusinessMetadata(engineering_model="EXACT-TEST",
                applicable_revision="R1", document_type="material", source_note="SYNTHETIC",
                expected_lock_version=current["lock_version"]), "test")
            with monkeypatch.context() as patch:
                patch.setattr(settings, "RUNTIME_MODE", "full")
                from src.infrastructure import full_backends

                def forbidden():
                    pytest.fail("exact-only request must not use a vector backend")
                patch.setattr(full_backends, "get_full_backends", forbidden)
                rows = await storage.search_chunks("", project_id=doc["project_id"],
                    filters=DocumentSearchFilters(engineering_model="EXACT-TEST"))
                assert {row["document_id"] for row in rows} == {doc["id"]}
    asyncio.run(run())
