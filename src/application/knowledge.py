from __future__ import annotations

from typing import Any

from src.application.authorization import ProjectAuthorizationService, project_authorization
from src.core.security import Principal
from src.infrastructure.database import EngineeringStorage, storage
from src.infrastructure.retrieval import RetrievalService


class KnowledgeQueryError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class KnowledgeQueryService:
    def __init__(
        self,
        store: EngineeringStorage = storage,
        authorization: ProjectAuthorizationService = project_authorization,
        retrieval: RetrievalService | None = None,
    ):
        self.store = store
        self.authorization = authorization
        self.retrieval = retrieval or RetrievalService(store)

    async def search_documents(
        self,
        principal: Principal,
        project_id: str,
        query: str,
        *,
        limit: int = 8,
        classifications: set[str] | None = None,
    ) -> dict[str, Any]:
        scope = await self.authorization.authorize(principal, project_id)
        packet = await self.retrieval.retrieve(
            query,
            project_id,
            tenant_id=scope.tenant_id,
            classifications=classifications,
            channels={"documents"},
            limit=max(1, min(limit, 10)),
        )
        return {"tool": "search_project_documents", **packet.as_tool_result()}

    async def query_material_specs(
        self,
        principal: Principal,
        project_id: str,
        query: str,
        *,
        limit: int = 8,
        visibility: set[str] | None = None,
    ) -> dict[str, Any]:
        scope = await self.authorization.authorize(principal, project_id)
        packet = await self.retrieval.retrieve(
            query,
            project_id,
            tenant_id=scope.tenant_id,
            classifications=visibility,
            channels={"materials"},
            limit=max(1, min(limit, 10)),
        )
        return {"tool": "query_material_specs", **packet.as_tool_result()}

    async def query_price_records(
        self,
        principal: Principal,
        project_id: str,
        query: str,
        *,
        limit: int = 8,
        visibility: set[str] | None = None,
    ) -> dict[str, Any]:
        scope = await self.authorization.authorize(principal, project_id)
        packet = await self.retrieval.retrieve(
            query,
            project_id,
            tenant_id=scope.tenant_id,
            classifications=visibility,
            channels={"prices"},
            limit=max(1, min(limit, 10)),
        )
        result = {"tool": "query_price_records", **packet.as_tool_result()}
        result["disclaimer"] = "历史测试价格仅用于资料比对，不构成市场价格或正式报价。"
        return result

    async def get_document_evidence(
        self,
        principal: Principal,
        document_id: str,
        *,
        limit: int = 20,
        classifications: set[str] | None = None,
    ) -> dict[str, Any]:
        document = await self.store.get_document(document_id)
        if document is None:
            raise KnowledgeQueryError("not_found", "资料不存在或无访问权限")
        await self.authorization.authorize(principal, str(document["project_id"]))
        if document["tenant_id"] != principal.tenant_id:
            raise KnowledgeQueryError("not_found", "资料不存在或无访问权限")
        if classifications and document["data_classification"] not in classifications:
            raise KnowledgeQueryError("not_found", "资料不存在或无访问权限")
        rows = await self.store.list_document_chunks(document_id, limit=max(1, min(limit, 50)))
        evidence = [
            {
                "evidence_id": str(row["id"]),
                "document_id": document_id,
                "filename": document["filename"],
                "location": row.get("location") or f"第{row['page_number']}页",
                "version": str(document["version"]),
                "text": str(row["text"])[:1200],
                "status": row.get("status", "processed"),
            }
            for row in rows
        ]
        sources = [
            {
                "source_id": item["evidence_id"],
                "title": document["filename"],
                "source_type": "document",
                "location": item["location"],
                "excerpt": item["text"][:300],
                "date": document["created_at"].isoformat(),
                "version": str(document["version"]),
                "url": "",
                "retrieval": [],
                "fusion_method": "",
                "fusion_score": None,
            }
            for item in evidence
        ]
        return {
            "tool": "get_document_evidence",
            "project_id": document["project_id"],
            "document_id": document_id,
            "evidence": evidence,
            "sources": sources,
            "uncertainties": [] if evidence else ["资料尚未产生可用Evidence"],
        }

    async def get_document_metadata(
        self,
        principal: Principal,
        document_id: str,
        *,
        classifications: set[str] | None = None,
    ) -> dict[str, Any]:
        document = await self.store.get_document(document_id)
        if document is None:
            raise KnowledgeQueryError("not_found", "资料不存在或无访问权限")
        await self.authorization.authorize(principal, str(document["project_id"]))
        if document["tenant_id"] != principal.tenant_id:
            raise KnowledgeQueryError("not_found", "资料不存在或无访问权限")
        if classifications and document["data_classification"] not in classifications:
            raise KnowledgeQueryError("not_found", "资料不存在或无访问权限")
        return {
            "document_id": document["id"],
            "project_id": document["project_id"],
            "filename": document["filename"],
            "content_type": document["content_type"],
            "sha256": document["sha256"],
            "classification": document["data_classification"],
            "parse_method": document["parse_method"],
            "parser": document["parser"],
            "parser_version": document["parser_version"],
            "embedding_model": document["embedding_model"],
            "version": document["version"],
            "status": document["status"],
            "created_at": document["created_at"].isoformat(),
            "updated_at": document["updated_at"].isoformat(),
        }

    async def get_evidence_unit(
        self,
        principal: Principal,
        document_id: str,
        evidence_id: str,
        *,
        classifications: set[str] | None = None,
    ) -> dict[str, Any]:
        metadata = await self.get_document_metadata(
            principal, document_id, classifications=classifications,
        )
        rows = await self.store.list_document_chunks(document_id, limit=1000)
        row = next((item for item in rows if str(item["id"]) == evidence_id), None)
        if row is None:
            raise KnowledgeQueryError("not_found", "Evidence不存在或无访问权限")
        return {
            "evidence_id": evidence_id,
            "document_id": document_id,
            "project_id": metadata["project_id"],
            "filename": metadata["filename"],
            "location": row.get("location") or f"第{row['page_number']}页",
            "page_number": row["page_number"],
            "version": str(metadata["version"]),
            "source_kind": row.get("source_kind", "text"),
            "ocr_used": bool(row.get("ocr_used", False)),
            "status": row.get("status", "processed"),
            "excerpt": str(row["text"])[:1200],
        }
