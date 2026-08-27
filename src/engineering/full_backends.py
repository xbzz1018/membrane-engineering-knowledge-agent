from __future__ import annotations

import asyncio
import io
import re
from pathlib import Path
from typing import Any

from src.core.config import Settings, get_settings
from src.engineering.provider import ModelProvider, get_model_provider


def _escape_filter(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


class FullBackends:
    """External storage adapters used only when RUNTIME_MODE=full."""

    def __init__(self, settings: Settings | None = None, provider: ModelProvider | None = None):
        self.settings = settings or get_settings()
        self.provider = provider or get_model_provider()
        self._neo4j_driver = None

    async def initialize(self) -> None:
        await asyncio.gather(self._init_minio(), self._init_milvus(), self._init_neo4j())

    async def _init_minio(self) -> None:
        from minio import Minio

        def initialize() -> None:
            client = Minio(
                self.settings.MINIO_ENDPOINT,
                access_key=self.settings.MINIO_ACCESS_KEY,
                secret_key=self.settings.MINIO_SECRET_KEY,
                secure=self.settings.MINIO_SECURE,
            )
            if not client.bucket_exists(self.settings.MINIO_BUCKET):
                client.make_bucket(self.settings.MINIO_BUCKET)

        await asyncio.to_thread(initialize)

    def _milvus_client(self):
        from pymilvus import MilvusClient

        return MilvusClient(uri=f"http://{self.settings.MILVUS_HOST}:{self.settings.MILVUS_PORT}")

    async def _init_milvus(self) -> None:
        def initialize() -> None:
            client = self._milvus_client()
            try:
                for collection in (
                    self.settings.MILVUS_DOCUMENT_COLLECTION,
                    self.settings.MILVUS_MEMORY_COLLECTION,
                ):
                    if not client.has_collection(collection):
                        client.create_collection(
                            collection_name=collection,
                            dimension=self.settings.EMBEDDING_DIMENSIONS,
                            id_type="string",
                            max_length=256,
                            metric_type="COSINE",
                            consistency_level="Strong",
                            enable_dynamic_field=True,
                        )
            finally:
                client.close()

        await asyncio.to_thread(initialize)

    async def _init_neo4j(self) -> None:
        from neo4j import AsyncGraphDatabase

        self._neo4j_driver = AsyncGraphDatabase.driver(
            self.settings.NEO4J_URI,
            auth=(self.settings.NEO4J_USER, self.settings.NEO4J_PASSWORD),
        )
        await self._neo4j_driver.verify_connectivity()
        async with self._neo4j_driver.session() as session:
            await session.run("CREATE CONSTRAINT project_case_id IF NOT EXISTS FOR (p:Project) REQUIRE p.case_id IS UNIQUE")

    async def close(self) -> None:
        if self._neo4j_driver is not None:
            await self._neo4j_driver.close()

    async def store_document(self, document_id: str, filename: str, content_type: str, content: bytes) -> str:
        from minio import Minio

        object_name = f"documents/{document_id}/{Path(filename).name}"

        def upload() -> None:
            client = Minio(
                self.settings.MINIO_ENDPOINT,
                access_key=self.settings.MINIO_ACCESS_KEY,
                secret_key=self.settings.MINIO_SECRET_KEY,
                secure=self.settings.MINIO_SECURE,
            )
            client.put_object(
                self.settings.MINIO_BUCKET,
                object_name,
                io.BytesIO(content),
                length=len(content),
                content_type=content_type or "application/octet-stream",
            )

        await asyncio.to_thread(upload)
        return f"minio://{self.settings.MINIO_BUCKET}/{object_name}"

    async def materialize_document(self, stored_path: str, document_id: str, filename: str) -> Path:
        from minio import Minio

        prefix = f"minio://{self.settings.MINIO_BUCKET}/"
        if not stored_path.startswith(prefix):
            raise ValueError("Document is not stored in the configured MinIO bucket")
        object_name = stored_path[len(prefix):]
        cache = self.settings.upload_path / "cache" / f"{document_id}_{Path(filename).name}"
        cache.parent.mkdir(parents=True, exist_ok=True)

        def download() -> None:
            client = Minio(
                self.settings.MINIO_ENDPOINT,
                access_key=self.settings.MINIO_ACCESS_KEY,
                secret_key=self.settings.MINIO_SECRET_KEY,
                secure=self.settings.MINIO_SECURE,
            )
            client.fget_object(self.settings.MINIO_BUCKET, object_name, str(cache))

        await asyncio.to_thread(download)
        return cache

    async def index_document(self, document: dict[str, Any], chunks: list[dict[str, Any]]) -> None:
        rows = []
        for chunk in chunks:
            rows.append({
                "id": f"{document['id']}:{chunk['chunk_index']}",
                "vector": await self.provider.embed(chunk["text"]),
                "text": chunk["text"][:8000],
                "document_id": document["id"],
                "filename": document["filename"],
                "page_number": int(chunk.get("page_number", 1)),
                "chunk_index": int(chunk["chunk_index"]),
                "version": int(document.get("version", 1)),
                "date": document["created_at"].isoformat(),
            })

        def replace() -> None:
            client = self._milvus_client()
            try:
                client.delete(
                    self.settings.MILVUS_DOCUMENT_COLLECTION,
                    filter=f'document_id == "{_escape_filter(document["id"])}"',
                )
                if rows:
                    client.insert(self.settings.MILVUS_DOCUMENT_COLLECTION, rows)
            finally:
                client.close()

        await asyncio.to_thread(replace)

    async def search_documents(self, query: str, limit: int = 8) -> list[dict[str, Any]]:
        vector = await self.provider.embed(query)

        def search() -> list[dict[str, Any]]:
            client = self._milvus_client()
            try:
                result = client.search(
                    self.settings.MILVUS_DOCUMENT_COLLECTION,
                    data=[vector],
                    limit=limit,
                    output_fields=[
                        "text", "document_id", "filename", "page_number", "chunk_index", "version", "date",
                    ],
                )
            finally:
                client.close()
            rows = []
            for rank, hit in enumerate(result[0] if result else [], 1):
                entity = hit.get("entity", {})
                rows.append({
                    "id": str(hit.get("id")),
                    **entity,
                    "created_at": entity.get("date", ""),
                    "retrieval": [{"backend": "milvus", "rank": rank, "score": float(hit.get("distance", 0))}],
                })
            return rows

        return await asyncio.to_thread(search)

    async def index_memory(self, memory_id: str, user_id: str, kind: str, content: str, created_at: str) -> None:
        row = {
            "id": memory_id,
            "vector": await self.provider.embed(content),
            "user_id": user_id,
            "kind": kind,
            "text": content,
            "date": created_at,
        }

        def insert() -> None:
            client = self._milvus_client()
            try:
                client.upsert(self.settings.MILVUS_MEMORY_COLLECTION, [row])
            finally:
                client.close()

        await asyncio.to_thread(insert)

    async def search_memories(self, user_id: str, query: str, limit: int = 5) -> list[str]:
        vector = await self.provider.embed(query)

        def search() -> list[str]:
            client = self._milvus_client()
            try:
                result = client.search(
                    self.settings.MILVUS_MEMORY_COLLECTION,
                    data=[vector],
                    filter=f'user_id == "{_escape_filter(user_id)}"',
                    limit=limit,
                    output_fields=["text"],
                )
            finally:
                client.close()
            return [str(hit.get("entity", {}).get("text", "")) for hit in (result[0] if result else [])]

        return await asyncio.to_thread(search)

    async def delete_memory(self, memory_id: str) -> None:
        def delete() -> None:
            client = self._milvus_client()
            try:
                client.delete(self.settings.MILVUS_MEMORY_COLLECTION, ids=[memory_id])
            finally:
                client.close()

        await asyncio.to_thread(delete)

    async def sync_graph_cases(self, rows: list[dict[str, Any]]) -> None:
        if self._neo4j_driver is None:
            raise RuntimeError("Neo4j backend is not initialized")
        payloads = [
            {
                "case_id": str(row.get("case_id", "")),
                "title": str(row.get("title", "")),
                "structure": str(row.get("structure_type", "unknown")),
                "material": str(row.get("membrane_material", "unknown")),
                "scenario": str(row.get("application", "unknown")),
                "source_url": str(row.get("source_url", "")),
                "date": str(row.get("year") or row.get("retrieved_at", "")),
                "version": str(row.get("source_version", "1")),
            }
            for row in rows
            if row.get("case_id")
        ]
        query = """
        UNWIND $rows AS row
        MERGE (p:Project {case_id: row.case_id})
        SET p.title = row.title, p.source_url = row.source_url, p.date = row.date, p.version = row.version
        MERGE (s:Structure {name: row.structure})
        MERGE (m:MembraneMaterial {name: row.material})
        MERGE (a:Scenario {name: row.scenario})
        MERGE (p)-[:USES_STRUCTURE]->(s)
        MERGE (p)-[:USES_MATERIAL]->(m)
        MERGE (p)-[:APPLIES_TO]->(a)
        """
        async with self._neo4j_driver.session() as session:
            await session.run(query, rows=payloads)

    async def search_graph_cases(self, query: str, limit: int = 6) -> list[dict[str, Any]]:
        if self._neo4j_driver is None:
            raise RuntimeError("Neo4j backend is not initialized")
        terms = re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]{2,}", query.lower())
        if not terms:
            return []
        cypher = """
        MATCH (p:Project)-[:USES_STRUCTURE]->(s:Structure)
        MATCH (p)-[:USES_MATERIAL]->(m:MembraneMaterial)
        MATCH (p)-[:APPLIES_TO]->(a:Scenario)
        WHERE any(term IN $terms WHERE
            toLower(p.title) CONTAINS term OR toLower(s.name) CONTAINS term OR
            toLower(m.name) CONTAINS term OR toLower(a.name) CONTAINS term)
        RETURN p, s.name AS structure_type, m.name AS membrane_material, a.name AS application
        LIMIT $limit
        """
        async with self._neo4j_driver.session() as session:
            result = await session.run(cypher, terms=terms, limit=limit)
            records = [record async for record in result]
        rows = []
        for rank, record in enumerate(records, 1):
            project = dict(record["p"])
            rows.append({
                "case_id": project["case_id"],
                "title": project.get("title", project["case_id"]),
                "structure_type": record["structure_type"],
                "membrane_material": record["membrane_material"],
                "application": record["application"],
                "source_url": project.get("source_url", ""),
                "retrieved_at": project.get("date", ""),
                "source_version": project.get("version", ""),
                "retrieval": [{"backend": "neo4j", "rank": rank, "score": 1.0}],
            })
        return rows


_full_backends: FullBackends | None = None


def get_full_backends() -> FullBackends:
    global _full_backends
    if _full_backends is None:
        _full_backends = FullBackends()
    return _full_backends
