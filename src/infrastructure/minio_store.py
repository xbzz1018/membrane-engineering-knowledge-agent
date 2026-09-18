from __future__ import annotations

import asyncio
import io
from pathlib import Path


class MinioStore:
    """MinIO operations for original documents and derived OCR assets."""

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
