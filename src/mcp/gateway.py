from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import Awaitable, Callable
from typing import Any

from src.application.knowledge import KnowledgeQueryService
from src.application.reviews import PackageReviewApplicationService
from src.core.security import MCPIdentity
from src.domain.schemas import PackageReviewRequest
from src.infrastructure.database import EngineeringStorage, storage


class MCPGatewayError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class MCPGateway:
    def __init__(
        self,
        store: EngineeringStorage = storage,
        knowledge: KnowledgeQueryService | None = None,
        reviews: PackageReviewApplicationService | None = None,
    ):
        self.store = store
        self.knowledge = knowledge or KnowledgeQueryService(store)
        self.reviews = reviews or PackageReviewApplicationService(store)
        self._idempotency_locks: dict[tuple[str, str, str], asyncio.Lock] = {}

    @staticmethod
    def require_scope(identity: MCPIdentity, scope: str) -> None:
        if scope not in identity.scopes:
            raise MCPGatewayError("forbidden", f"MCP scope required: {scope}")

    async def _audited(
        self,
        identity: MCPIdentity,
        project_id: str,
        tool_name: str,
        operation: Callable[[], Awaitable[dict[str, Any]]],
    ) -> dict[str, Any]:
        started = time.perf_counter()
        call_id = await self.store.start_mcp_tool_call(
            tenant_id=identity.principal.tenant_id,
            user_id=identity.principal.user_id,
            client_id=identity.client_id,
            project_id=project_id,
            tool_name=tool_name,
        )
        try:
            result = await operation()
            result_count = len(result.get("evidence", [])) or len(result.get("sources", []))
            result_ref = str(result.get("review_id") or result.get("document_id") or "")
            await self.store.finish_mcp_tool_call(
                call_id,
                status="completed",
                duration_ms=(time.perf_counter() - started) * 1000,
                result_count=result_count,
                result_ref=result_ref,
            )
            return result
        except Exception as exc:
            await self.store.finish_mcp_tool_call(
                call_id,
                status="failed",
                duration_ms=(time.perf_counter() - started) * 1000,
                error_type=type(exc).__name__,
            )
            raise

    @staticmethod
    def _request_hash(payload: dict[str, Any]) -> str:
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    async def _idempotent(
        self,
        identity: MCPIdentity,
        tool_name: str,
        idempotency_key: str,
        payload: dict[str, Any],
        operation: Callable[[], Awaitable[dict[str, Any]]],
    ) -> dict[str, Any]:
        if not idempotency_key or len(idempotency_key) > 128:
            raise MCPGatewayError("invalid_request", "idempotency_key长度必须为1至128")
        request_hash = self._request_hash(payload)
        lock_key = (identity.principal.user_id, tool_name, idempotency_key)
        lock = self._idempotency_locks.setdefault(lock_key, asyncio.Lock())
        async with lock:
            existing = await self.store.get_mcp_idempotency(
                tenant_id=identity.principal.tenant_id,
                user_id=identity.principal.user_id,
                tool_name=tool_name,
                idempotency_key=idempotency_key,
            )
            if existing:
                if existing["request_hash"] != request_hash:
                    raise MCPGatewayError("conflict", "相同幂等键对应不同请求")
                return {**existing["result_payload"], "idempotent_replay": True}
            result = await operation()
            await self.store.save_mcp_idempotency(
                tenant_id=identity.principal.tenant_id,
                user_id=identity.principal.user_id,
                tool_name=tool_name,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                status="completed",
                result_ref=str(result.get("review_id") or ""),
                result_payload=result,
            )
            return result

    async def search_project_documents(
        self, identity: MCPIdentity, project_id: str, query: str, limit: int = 8,
    ) -> dict[str, Any]:
        self.require_scope(identity, "documents:read")
        return await self._audited(identity, project_id, "search_project_documents", lambda: self.knowledge.search_documents(
            identity.principal, project_id, query, limit=limit, classifications={"public"},
        ))

    async def query_material_specs(
        self, identity: MCPIdentity, project_id: str, query: str, limit: int = 8,
    ) -> dict[str, Any]:
        self.require_scope(identity, "materials:read")
        return await self._audited(identity, project_id, "query_material_specs", lambda: self.knowledge.query_material_specs(
            identity.principal, project_id, query, limit=limit, visibility={"public"},
        ))

    async def query_price_records(
        self, identity: MCPIdentity, project_id: str, query: str, limit: int = 8,
    ) -> dict[str, Any]:
        self.require_scope(identity, "prices:read")
        return await self._audited(identity, project_id, "query_price_records", lambda: self.knowledge.query_price_records(
            identity.principal, project_id, query, limit=limit, visibility={"public"},
        ))

    async def get_document_evidence(
        self, identity: MCPIdentity, document_id: str, limit: int = 20,
    ) -> dict[str, Any]:
        self.require_scope(identity, "documents:read")
        document = await self.store.get_document(document_id)
        project_id = str(document.get("project_id", "")) if document else ""
        return await self._audited(identity, project_id, "get_document_evidence", lambda: self.knowledge.get_document_evidence(
            identity.principal, document_id, limit=limit, classifications={"public"},
        ))

    async def get_review_status(self, identity: MCPIdentity, review_id: str) -> dict[str, Any]:
        self.require_scope(identity, "reviews:read")
        review = await self.store.get_package_review(review_id)
        project_id = str(review.get("project_id", "")) if review else ""
        return await self._audited(identity, project_id, "get_review_status", lambda: self.reviews.status(
            review_id, identity.principal,
        ))

    async def get_document_resource(self, identity: MCPIdentity, document_id: str) -> dict[str, Any]:
        self.require_scope(identity, "documents:read")
        document = await self.store.get_document(document_id)
        project_id = str(document.get("project_id", "")) if document else ""
        return await self._audited(
            identity,
            project_id,
            "resource:document",
            lambda: self.knowledge.get_document_metadata(
                identity.principal, document_id, classifications={"public"},
            ),
        )

    async def get_evidence_resource(
        self, identity: MCPIdentity, document_id: str, evidence_id: str,
    ) -> dict[str, Any]:
        self.require_scope(identity, "documents:read")
        document = await self.store.get_document(document_id)
        project_id = str(document.get("project_id", "")) if document else ""
        return await self._audited(
            identity,
            project_id,
            "resource:evidence",
            lambda: self.knowledge.get_evidence_unit(
                identity.principal, document_id, evidence_id, classifications={"public"},
            ),
        )

    async def get_review_report_resource(self, identity: MCPIdentity, review_id: str) -> dict[str, Any]:
        self.require_scope(identity, "reviews:read")
        review = await self.store.get_package_review(review_id)
        project_id = str(review.get("project_id", "")) if review else ""
        return await self._audited(
            identity,
            project_id,
            "resource:review-report",
            lambda: self.reviews.report(review_id, identity.principal, public_only=True),
        )

    async def create_review_request(
        self,
        identity: MCPIdentity,
        project_id: str,
        document_ids: list[str],
        question: str,
        review_mode: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        self.require_scope(identity, "reviews:create")
        payload = {
            "project_id": project_id,
            "document_ids": document_ids,
            "question": question,
            "review_mode": review_mode,
        }
        digest = hashlib.sha256(
            f"{identity.principal.tenant_id}|{identity.principal.user_id}|{idempotency_key}".encode()
        ).hexdigest()[:32]

        async def operation() -> dict[str, Any]:
            request = PackageReviewRequest(**payload)
            return await self.reviews.start(
                request, identity.principal, review_id=f"mcp-{digest}", public_only=True,
            )

        return await self._audited(identity, project_id, "create_review_request", lambda: self._idempotent(
            identity, "create_review_request", idempotency_key, payload, operation,
        ))

    async def cancel_review_request(
        self, identity: MCPIdentity, review_id: str, reason: str, idempotency_key: str,
    ) -> dict[str, Any]:
        self.require_scope(identity, "reviews:cancel")
        payload = {"review_id": review_id, "reason": reason}
        review = await self.store.get_package_review(review_id)
        project_id = str(review.get("project_id", "")) if review else ""
        return await self._audited(identity, project_id, "cancel_review_request", lambda: self._idempotent(
            identity,
            "cancel_review_request",
            idempotency_key,
            payload,
            lambda: self.reviews.cancel(review_id, identity.principal),
        ))

    async def decide_review_request(
        self,
        identity: MCPIdentity,
        review_id: str,
        decision: str,
        expected_lock_version: int,
        reason: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        self.require_scope(identity, "reviews:decide")
        tool_name = "approve_review_request" if decision == "approved" else "reject_review_request"
        payload = {
            "review_id": review_id,
            "decision": decision,
            "expected_lock_version": expected_lock_version,
            "reason": reason,
        }
        review = await self.store.get_package_review(review_id)
        project_id = str(review.get("project_id", "")) if review else ""
        return await self._audited(identity, project_id, tool_name, lambda: self._idempotent(
            identity,
            tool_name,
            idempotency_key,
            payload,
            lambda: self.reviews.decide(
                review_id,
                identity.principal,
                decision,
                expected_lock_version=expected_lock_version,
                reason=reason,
            ),
        ))
