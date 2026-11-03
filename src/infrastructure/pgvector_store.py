from __future__ import annotations

import math
from typing import Any

from pgvector import Vector
from sqlalchemy import text


def _vector_literal(values: list[float], expected_dimensions: int) -> str:
    if len(values) != expected_dimensions:
        raise ValueError(f"Embedding dimension mismatch: expected {expected_dimensions}, got {len(values)}")
    normalized = [float(value) for value in values]
    if not all(math.isfinite(value) for value in normalized):
        raise ValueError("Embedding contains a non-finite value")
    return Vector(normalized).to_text()


class PgVectorStore:
    """pgvector indexes for EvidenceUnit and confirmed long-term memory."""

    async def _init_pgvector(self) -> None:
        async with self.session_factory() as session:
            extension = await session.scalar(text("SELECT extversion FROM pg_extension WHERE extname = 'vector'"))
            if not extension:
                raise RuntimeError("PostgreSQL extension 'vector' is not installed")
            tables = await session.execute(
                text("""
                SELECT to_regclass('public.document_embeddings'),
                       to_regclass('public.memory_embeddings')
            """)
            )
            document_table, memory_table = tables.one()
            if not document_table or not memory_table:
                raise RuntimeError("pgvector tables are missing; run Alembic migrations")

    async def index_document(self, document: dict[str, Any], chunks: list[dict[str, Any]]) -> None:
        embedding_model = self.provider.embedding_model
        rows: list[dict[str, Any]] = []
        for chunk in chunks:
            vector = await self.provider.embed(chunk["text"])
            rows.append(
                {
                    "id": f"{document['id']}:{chunk['chunk_index']}",
                    "embedding": _vector_literal(vector, self.settings.EMBEDDING_DIMENSIONS),
                    "text": chunk["text"][:8000],
                    "document_id": document["id"],
                    "filename": document["filename"],
                    "page_number": int(chunk.get("page_number", 1)),
                    "chunk_index": int(chunk["chunk_index"]),
                    "version": int(document.get("version", 1)),
                    "created_at": document["created_at"].isoformat(),
                    "project_id": document.get("project_id", ""),
                    "tenant_id": document.get("tenant_id", ""),
                    "classification": document.get("data_classification", "public"),
                    "location": str(chunk.get("location", "")),
                    "heading_path": str(chunk.get("heading_path", "")),
                    "sheet_name": str(chunk.get("sheet_name", "")),
                    "anchor": str(chunk.get("anchor", "")),
                    "source_kind": str(chunk.get("source_kind", "text")),
                    "ocr_used": bool(chunk.get("ocr_used", False)),
                    "asset_sha256": str(chunk.get("asset_sha256", "")),
                    "embedding_model": embedding_model,
                }
            )

        async with self.session_factory() as session:
            if document.get("_ingest_claim") is not None:
                from src.infrastructure.ingest_claim import guard_claim

                await guard_claim(session, document["id"], tuple(document["_ingest_claim"]))
            await session.execute(
                text("DELETE FROM document_embeddings WHERE document_id = :document_id"),
                {"document_id": document["id"]},
            )
            if rows:
                await session.execute(
                    text("""
                    INSERT INTO document_embeddings (
                        id, embedding, text, document_id, filename, page_number, chunk_index,
                        version, created_at, project_id, tenant_id, classification, location,
                        heading_path, sheet_name, anchor, source_kind, ocr_used, asset_sha256,
                        embedding_model
                    ) VALUES (
                        :id, CAST(:embedding AS vector), :text, :document_id, :filename,
                        :page_number, :chunk_index, :version, :created_at, :project_id,
                        :tenant_id, :classification, :location, :heading_path, :sheet_name,
                        :anchor, :source_kind, :ocr_used, :asset_sha256, :embedding_model
                    )
                """),
                    rows,
                )
            await session.commit()

    async def search_documents(
        self,
        query: str,
        limit: int = 8,
        project_id: str = "",
        *,
        tenant_id: str = "",
        classifications: set[str] | None = None,
        filters=None,
    ) -> list[dict[str, Any]]:
        query_vector = _vector_literal(
            await self.provider.embed(query),
            self.settings.EMBEDDING_DIMENSIONS,
        )
        predicates = ["e.embedding_model = :embedding_model", "d.status = 'indexed'"]
        params: dict[str, Any] = {
            "embedding_model": self.provider.embedding_model,
            "query_vector": query_vector,
            "limit": limit,
        }
        if project_id:
            predicates.append("d.project_id = :project_id")
            params["project_id"] = project_id
        if tenant_id:
            predicates.append("d.tenant_id = :tenant_id")
            params["tenant_id"] = tenant_id
        if classifications:
            placeholders = []
            for index, classification in enumerate(sorted(classifications)):
                key = f"classification_{index}"
                placeholders.append(f":{key}")
                params[key] = classification
            predicates.append(f"d.data_classification IN ({', '.join(placeholders)})")

        if filters is not None:
            from src.infrastructure.document_filters import vector_filter_sql

            filter_clauses, filter_params = vector_filter_sql(filters)
            filters_sql = filter_clauses
            params.update(filter_params)
        else:
            filters_sql = []
        statement = text(f"""
            SELECT e.id, e.text, e.document_id, d.filename, e.page_number, e.chunk_index, d.version,
                   d.created_at, d.project_id, d.tenant_id, d.data_classification AS classification,
                   e.location, e.heading_path, e.sheet_name, e.anchor, e.source_kind, e.ocr_used,
                   e.asset_sha256, e.embedding_model,
                   1 - (e.embedding <=> CAST(:query_vector AS vector)) AS similarity
            FROM document_embeddings e JOIN documents d ON d.id = e.document_id
            WHERE {" AND ".join([*predicates, *filters_sql])}
            ORDER BY e.embedding <=> CAST(:query_vector AS vector)
            LIMIT :limit
        """)
        async with self.session_factory() as session:
            result = await session.execute(statement, params)
            records = result.mappings().all()

        rows: list[dict[str, Any]] = []
        for rank, record in enumerate(records, 1):
            row = dict(record)
            score = float(row.pop("similarity", 0.0) or 0.0)
            rows.append(
                {
                    **row,
                    "retrieval": [{"backend": "pgvector", "rank": rank, "score": score}],
                }
            )
        return rows

    async def index_memory(
        self,
        memory_id: str,
        user_id: str,
        kind: str,
        content: str,
        created_at: str,
        *,
        tenant_id: str = "",
        project_id: str = "",
        scope: str = "user",
    ) -> None:
        vector = _vector_literal(
            await self.provider.embed(content),
            self.settings.EMBEDDING_DIMENSIONS,
        )
        async with self.session_factory() as session:
            await session.execute(
                text("""
                INSERT INTO memory_embeddings (
                    id, embedding, user_id, kind, text, created_at, tenant_id, project_id,
                    scope, embedding_model
                ) VALUES (
                    :id, CAST(:embedding AS vector), :user_id, :kind, :text, :created_at,
                    :tenant_id, :project_id, :scope, :embedding_model
                )
                ON CONFLICT (id) DO UPDATE SET
                    embedding = EXCLUDED.embedding,
                    user_id = EXCLUDED.user_id,
                    kind = EXCLUDED.kind,
                    text = EXCLUDED.text,
                    created_at = EXCLUDED.created_at,
                    tenant_id = EXCLUDED.tenant_id,
                    project_id = EXCLUDED.project_id,
                    scope = EXCLUDED.scope,
                    embedding_model = EXCLUDED.embedding_model
            """),
                {
                    "id": memory_id,
                    "embedding": vector,
                    "user_id": user_id,
                    "kind": kind,
                    "text": content,
                    "created_at": created_at,
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "scope": scope,
                    "embedding_model": self.provider.embedding_model,
                },
            )
            await session.commit()

    async def search_memories(
        self,
        user_id: str,
        query: str,
        limit: int = 5,
        *,
        tenant_id: str = "",
        project_id: str = "",
    ) -> list[str]:
        query_vector = _vector_literal(
            await self.provider.embed(query),
            self.settings.EMBEDDING_DIMENSIONS,
        )
        filters = ["user_id = :user_id", "embedding_model = :embedding_model"]
        params: dict[str, Any] = {
            "user_id": user_id,
            "embedding_model": self.provider.embedding_model,
            "query_vector": query_vector,
            "limit": limit,
        }
        if tenant_id:
            filters.append("tenant_id = :tenant_id")
            params["tenant_id"] = tenant_id
        if project_id:
            filters.append("(scope = 'user' OR project_id = :project_id)")
            params["project_id"] = project_id
        statement = text(f"""
            SELECT text
            FROM memory_embeddings
            WHERE {" AND ".join(filters)}
            ORDER BY embedding <=> CAST(:query_vector AS vector)
            LIMIT :limit
        """)
        async with self.session_factory() as session:
            result = await session.execute(statement, params)
            return [str(row[0]) for row in result.all()]

    async def delete_memory(self, memory_id: str) -> None:
        async with self.session_factory() as session:
            await session.execute(
                text("DELETE FROM memory_embeddings WHERE id = :memory_id"),
                {"memory_id": memory_id},
            )
            await session.commit()
