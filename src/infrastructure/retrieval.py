from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from src.core.observability import span
from src.domain.document_search import DocumentSearchFilters
from src.domain.schemas import SourceRef
from src.infrastructure.database import EngineeringStorage, storage
from src.infrastructure.model_provider import ModelProvider, get_model_provider


@dataclass(slots=True)
class RetrievalPacket:
    query: str
    project_id: str
    evidence: list[dict[str, Any]]
    sources: list[dict[str, Any]]
    uncertainties: list[str]

    @property
    def context(self) -> str:
        return "\n\n".join(
            f"[{item['evidence_id']}] {item['text']}" for item in self.evidence
        )

    def as_tool_result(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "project_id": self.project_id,
            "evidence": self.evidence,
            "sources": self.sources,
            "uncertainties": self.uncertainties,
        }


class RetrievalService:
    """Project-scoped retrieval facade; memories are deliberately excluded."""

    def __init__(
        self,
        store: EngineeringStorage = storage,
        provider: ModelProvider | None = None,
    ):
        self.store = store
        self.provider = provider or get_model_provider()

    async def retrieve(
        self,
        query: str,
        project_id: str,
        *,
        tenant_id: str = "",
        classifications: set[str] | None = None,
        channels: set[str] | None = None,
        limit: int = 8,
        filters: DocumentSearchFilters | None = None,
    ) -> RetrievalPacket:
        enabled = channels or {"documents", "cases", "materials", "prices"}
        channel_candidates: dict[str, list[dict[str, Any]]] = {
            channel: [] for channel in ("documents", "cases", "materials", "prices")
        }
        if "documents" in enabled:
            with span("gen_ai.retrieval", {"retrieval.channel": "documents", "retrieval.top_k": 30}):
                document_rows = await self.store.search_chunks(
                    query,
                    limit=30,
                    project_id=project_id,
                    tenant_id=tenant_id,
                    classifications=classifications,
                    **({"filters": filters} if filters is not None else {}),
                )
            for item in document_rows:
                candidate_text = (
                    f"文件名：{item.get('filename', '')}\n"
                    f"版本：{item.get('version', '')}\n"
                    f"位置：{item.get('location') or f'第{item.get('page_number', 1)}页'}\n"
                    f"正文：{item['text']}"
                )
                channel_candidates["documents"].append({
                    "evidence_id": str(item["id"]),
                    "source_type": "document",
                    "text": candidate_text,
                    "raw": item,
                })
        if "cases" in enabled:
            for item in await self.store.search_cases(query, limit=12):
                channel_candidates["cases"].append({
                    "evidence_id": f"case:{item.get('case_id', '')}",
                    "source_type": "case",
                    "text": json.dumps(item, ensure_ascii=False),
                    "raw": item,
                })
        if "materials" in enabled:
            for item in await self.store.search_specs(
                query,
                limit=12,
                tenant_id=tenant_id,
                visibility=classifications,
            ):
                channel_candidates["materials"].append({
                    "evidence_id": f"spec:{item.get('spec_id', '')}",
                    "source_type": "material_spec",
                    "text": json.dumps(item, ensure_ascii=False),
                    "raw": item,
                })
        if "prices" in enabled:
            for item in await self.store.search_prices(
                query,
                limit=12,
                tenant_id=tenant_id,
                project_id=project_id,
                visibility=classifications,
            ):
                channel_candidates["prices"].append({
                    "evidence_id": f"price:{item.get('price_id', '')}",
                    "source_type": "price",
                    "text": json.dumps(item, ensure_ascii=False),
                    "raw": item,
                })

        active = [channel_candidates[channel] for channel in channel_candidates if channel in enabled]
        candidates = [
            rows[rank]
            for rank in range(max((len(rows) for rows in active), default=0))
            for rows in active
            if rank < len(rows)
        ]
        with span("gen_ai.rerank", {"rerank.candidate_count": len(candidates), "rerank.top_n": limit}):
            # Exact-only requests have no semantic query to rerank.
            selected = await self.provider.rerank(query, candidates, top_n=limit) if query.strip() else candidates[:limit]
        evidence: list[dict[str, Any]] = []
        sources: list[dict[str, Any]] = []
        for item in selected:
            raw = item["raw"]
            evidence.append({
                "evidence_id": item["evidence_id"],
                "source_type": item["source_type"],
                "text": item["text"][:8000],
                "rerank": item.get("rerank", {}),
            })
            sources.append(self._source(item["source_type"], item["evidence_id"], raw))
        uncertainties = [] if evidence else ["没有找到可引用的项目资料"]
        return RetrievalPacket(query, project_id, evidence, sources, uncertainties)

    @staticmethod
    def _source(source_type: str, evidence_id: str, item: dict[str, Any]) -> dict[str, Any]:
        if source_type == "document":
            created_at = item.get("created_at")
            location = item.get("location") or f"第{item.get('page_number', 1)}页"
            return SourceRef(
                source_id=evidence_id,
                title=item.get("filename", evidence_id),
                source_type="document",
                location=location,
                excerpt=item.get("text", "")[:300],
                date=created_at.isoformat() if hasattr(created_at, "isoformat") else str(created_at or ""),
                version=str(item.get("version", "")),
                retrieval=item.get("retrieval", []),
                fusion_score=item.get("fusion_score"),
                fusion_method=item.get("fusion_method", ""),
            ).model_dump()
        if source_type == "case":
            return SourceRef(
                source_id=evidence_id,
                title=item.get("title", evidence_id),
                source_type=source_type,
                url=item.get("source_url", ""),
                date=str(item.get("year") or item.get("retrieved_at", "")),
                version=str(item.get("source_version", "")),
            ).model_dump()
        return SourceRef(
            source_id=evidence_id,
            title=item.get("material", evidence_id),
            source_type=source_type,
            location=(
                f"第{item.get('source_page')}页"
                if item.get("source_page")
                else ""
            ),
            url=item.get("source_url", ""),
            date=str(item.get("effective_date") or item.get("retrieved_at", "")),
            version=str(item.get("source_version", "")),
        ).model_dump()
