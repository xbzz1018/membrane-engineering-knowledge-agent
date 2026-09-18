from __future__ import annotations

import time
from typing import Any

from src.core.config import Settings, get_settings
from src.infrastructure.model_provider import ModelProvider

VECTOR_RERANK_CATALOG = (
    ("gte-rerank-v2", "文本重排序", "文本"),
    ("tongyi-embedding-vision-plus-2026-03-06", "多模态向量", "图文"),
    ("tongyi-embedding-vision-flash-2026-03-06", "多模态向量", "图文"),
    ("qwen3.7-text-embedding", "文本向量", "文本"),
    ("qwen3-vl-rerank", "多模态重排序", "图文视频"),
    ("tongyi-embedding-vision-flash", "多模态向量", "图文"),
    ("qwen3-vl-embedding", "多模态向量", "图文"),
    ("multimodal-embedding-v1", "多模态向量", "图文"),
    ("qwen3-rerank", "文本重排序", "文本"),
    ("text-embedding-v1", "文本向量", "文本"),
    ("tongyi-embedding-vision-plus", "多模态向量", "图文"),
    ("text-embedding-v3", "文本向量", "文本"),
    ("text-embedding-v2", "文本向量", "文本"),
    ("qwen2.5-vl-embedding", "多模态向量", "图文"),
    ("text-embedding-v4", "文本向量", "文本"),
    ("text-embedding-async-v1", "异步文本向量", "文本"),
    ("text-embedding-async-v2", "异步文本向量", "文本"),
)


class ModelCapabilityService:
    def __init__(self, provider: ModelProvider | None = None, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.provider = provider or ModelProvider(self.settings)

    def overview(self) -> dict[str, Any]:
        embedding = self.provider._embedding_config()
        catalog = [
            {
                "model_code": code,
                "category": category,
                "modality": modality,
                "configured": code in {embedding[3], self.settings.RERANKER_MODEL},
            }
            for code, category, modality in VECTOR_RERANK_CATALOG
        ]
        return {
            "chat": {
                "provider": self.provider.provider,
                "model": self.provider.model,
                "configured": self.provider.provider != "fake",
            },
            "embedding": {
                "provider": embedding[0],
                "model": embedding[3],
                "dimensions": self.settings.EMBEDDING_DIMENSIONS,
                "configured": embedding[0] != "fake",
            },
            "review": {
                "provider": "dashscope_workspace" if self.settings.REVIEW_API_BASE else self.provider.provider,
                "model": self.settings.REVIEW_MODEL if self.settings.REVIEW_API_BASE else self.provider.model,
                "configured": bool(self.settings.REVIEW_API_BASE and self.settings.REVIEW_API_KEY),
            },
            "reranker": {
                "provider": self.settings.RERANKER_PROVIDER,
                "model": self.settings.RERANKER_MODEL,
                "top_n": self.settings.RERANKER_TOP_N,
                "enabled": self.settings.RERANKER_ENABLED,
                "configured": bool(self.settings.RERANKER_API_BASE and self.settings.RERANKER_API_KEY),
            },
            "vector_rerank_catalog": catalog,
            "catalog_count": len(catalog),
        }

    async def discover(self) -> dict[str, Any]:
        started = time.perf_counter()
        models = await self.provider.discover_workspace_models()
        return {
            "models": models,
            "count": len(models),
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        }

    async def validate_reranker(self) -> dict[str, Any]:
        candidates = [
            {"text": "项目价格记录，不包含膜材规格。", "candidate_id": "price"},
            {"text": "PTFE膜材型号A，厚度0.8毫米。", "candidate_id": "material"},
            {"text": "ETFE气枕设计说明。", "candidate_id": "design"},
        ]
        started = time.perf_counter()
        ranked = await self.provider.rerank("PTFE膜材厚度和型号要求", candidates, top_n=2)
        return {
            "provider": self.settings.RERANKER_PROVIDER,
            "model": self.settings.RERANKER_MODEL,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "results": [
                {
                    "candidate_id": item["candidate_id"],
                    "rank": item["rerank"]["rank"],
                    "score": item["rerank"]["score"],
                }
                for item in ranked
            ],
        }


_model_capability_service: ModelCapabilityService | None = None


def get_model_capability_service() -> ModelCapabilityService:
    global _model_capability_service
    if _model_capability_service is None:
        _model_capability_service = ModelCapabilityService()
    return _model_capability_service
