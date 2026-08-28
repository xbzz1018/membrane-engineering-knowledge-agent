from __future__ import annotations

import asyncio
import io
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

    async def initialize(self) -> None:
        await asyncio.gather(self._init_minio(), self._init_milvus())

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

    async def close(self) -> None:
        return None

    async def store_document(
        self,
        document_id: str,
        filename: str,
        content_type: str,
        content: bytes,
        *,
        content_sha: str,
        version: int,
    ) -> str:
        from minio import Minio

        object_name = f"documents/{content_sha}/v{version}/{Path(filename).name}"

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

    async def store_derived_asset(
        self,
        document_sha: str,
        asset_sha: str,
        suffix: str,
        content: bytes,
    ) -> str:
        from minio import Minio

        normalized_suffix = suffix.lower() if suffix.startswith(".") else f".{suffix.lower()}"
        object_name = f"derived/{document_sha}/{asset_sha}{normalized_suffix}"

        def put_if_missing() -> None:
            client = Minio(
                self.settings.MINIO_ENDPOINT,
                access_key=self.settings.MINIO_ACCESS_KEY,
                secret_key=self.settings.MINIO_SECRET_KEY,
                secure=self.settings.MINIO_SECURE,
            )
            try:
                client.stat_object(self.settings.MINIO_BUCKET, object_name)
                return
            except Exception:
                client.put_object(
                    self.settings.MINIO_BUCKET,
                    object_name,
                    io.BytesIO(content),
                    length=len(content),
                    content_type=f"image/{normalized_suffix.lstrip('.')}",
                )

        await asyncio.to_thread(put_if_missing)
        return f"minio://{self.settings.MINIO_BUCKET}/{object_name}"

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

    async def search_documents(self, query: str, limit: int = 8, project_id: str = "") -> list[dict[str, Any]]:
        vector = await self.provider.embed(query)

        def search() -> list[dict[str, Any]]:
            client = self._milvus_client()
            try:
                options = {
                    "collection_name": self.settings.MILVUS_DOCUMENT_COLLECTION,
                    "data": [vector],
                    "limit": limit,
                    "output_fields": [
                        "text", "document_id", "filename", "page_number", "chunk_index", "version", "date",
                        "project_id", "location", "heading_path", "sheet_name", "anchor", "source_kind", "ocr_used",
                        "asset_sha256",
                    ],
                }
                if project_id:
                    options["filter"] = f'project_id == "{_escape_filter(project_id)}"'
                result = client.search(**options)
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
        row = {
            "id": memory_id,
            "vector": await self.provider.embed(content),
            "user_id": user_id,
            "kind": kind,
            "text": content,
            "date": created_at,
            "tenant_id": tenant_id,
            "project_id": project_id,
            "scope": scope,
        }

        def insert() -> None:
            client = self._milvus_client()
            try:
                client.upsert(self.settings.MILVUS_MEMORY_COLLECTION, [row])
            finally:
                client.close()

        await asyncio.to_thread(insert)

    async def search_memories(
        self,
        user_id: str,
        query: str,
        limit: int = 5,
        *,
        tenant_id: str = "",
        project_id: str = "",
    ) -> list[str]:
        vector = await self.provider.embed(query)

        def search() -> list[str]:
            client = self._milvus_client()
            try:
                filters = [f'user_id == "{_escape_filter(user_id)}"']
                if tenant_id:
                    filters.append(f'tenant_id == "{_escape_filter(tenant_id)}"')
                if project_id:
                    filters.append(f'(scope == "user" or project_id == "{_escape_filter(project_id)}")')
                result = client.search(
                    self.settings.MILVUS_MEMORY_COLLECTION,
                    data=[vector],
                    filter=" and ".join(filters),
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

_full_backends: FullBackends | None = None


def get_full_backends() -> FullBackends:
    global _full_backends
    if _full_backends is None:
        _full_backends = FullBackends()
    return _full_backends
