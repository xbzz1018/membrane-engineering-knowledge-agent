from __future__ import annotations

import asyncio

from src.core.config import Settings, get_settings
from src.infrastructure.database import SessionFactory
from src.infrastructure.minio_store import MinioStore
from src.infrastructure.model_provider import ModelProvider, get_model_provider
from src.infrastructure.pgvector_store import PgVectorStore


class FullBackends(MinioStore, PgVectorStore):
    """Composition facade for Full-mode object and vector storage adapters."""

    def __init__(
        self,
        settings: Settings | None = None,
        provider: ModelProvider | None = None,
        session_factory=SessionFactory,
    ):
        self.settings = settings or get_settings()
        self.provider = provider or get_model_provider()
        self.session_factory = session_factory

    async def initialize(self) -> None:
        await asyncio.gather(self._init_minio(), self._init_pgvector())

    async def close(self) -> None:
        return None


_full_backends: FullBackends | None = None


def get_full_backends() -> FullBackends:
    global _full_backends
    if _full_backends is None:
        _full_backends = FullBackends()
    return _full_backends
