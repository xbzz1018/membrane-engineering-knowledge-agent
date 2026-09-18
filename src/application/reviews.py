from __future__ import annotations

import uuid
from typing import Any

from src.agents.review_agents import ReviewAgentError, run_package_review
from src.application.authorization import ProjectAuthorizationService, project_authorization
from src.core.config import Settings, get_settings
from src.core.security import Principal
from src.domain.schemas import PackageReviewRequest
from src.infrastructure.database import EngineeringStorage, storage
from src.workflows.temporal_app import cancel_workflow, get_workflow_state, signal_workflow, submit_package_review


class ReviewApplicationError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class PackageReviewApplicationService:
    ROLES = {"admin", "design_engineer", "material_procurement", "reviewer"}

    def __init__(
        self,
        store: EngineeringStorage = storage,
        authorization: ProjectAuthorizationService = project_authorization,
        settings: Settings | None = None,
    ):
        self.store = store
        self.authorization = authorization
        self.settings = settings or get_settings()

    def estimated_tokens(self, document_count: int) -> int:
        return min(self.settings.DEFAULT_DAILY_TOKEN_LIMIT, 20_000 + (document_count * 15_000))

    def estimated_cost(self, tokens: int) -> int:
        return ((max(0, tokens) + 999) // 1000) * self.settings.MODEL_ESTIMATED_COST_MICROS_PER_1K_TOKENS

    @staticmethod
    def actual_tokens(usage: dict[str, Any]) -> int:
        return sum(
            int(item.get("input_tokens", 0) or 0) + int(item.get("output_tokens", 0) or 0)
            for item in usage.values()
            if isinstance(item, dict)
        )

    async def _validate_documents(
        self, request: PackageReviewRequest, principal: Principal, *, public_only: bool = False,
    ) -> None:
        documents = await self.store.list_documents(
            request.document_ids,
            project_id=request.project_id,
            tenant_id=principal.tenant_id,
        )
        if len(documents) != len(set(request.document_ids)):
            raise ReviewApplicationError("invalid_documents", "资料不存在或不属于当前项目")
        not_indexed = [item["id"] for item in documents if item["status"] != "indexed"]
        if not_indexed:
            raise ReviewApplicationError("invalid_documents", f"资料尚未完成索引: {', '.join(not_indexed)}")
        if public_only and any(item["data_classification"] != "public" for item in documents):
            raise ReviewApplicationError("forbidden", "MCP只允许使用public资料发起审查")

    async def start(
        self,
        request: PackageReviewRequest,
        principal: Principal,
        *,
        review_id: str | None = None,
        public_only: bool = False,
    ) -> dict[str, Any]:
        await self.authorization.authorize(principal, request.project_id, self.ROLES)
        await self._validate_documents(request, principal, public_only=public_only)
        review_id = review_id or uuid.uuid4().hex
        workflow_id = f"package-review:{review_id}"
        reserved_tokens = self.estimated_tokens(len(request.document_ids))
        try:
            await self.store.reserve_budget(
                request.project_id,
                workflow_id,
                reserved_tokens,
                self.estimated_cost(reserved_tokens),
            )
        except ValueError as exc:
            raise ReviewApplicationError("quota", str(exc)) from exc

        if self.settings.TEMPORAL_ENABLED:
            queued = {
                "review_id": review_id,
                "status": "queued",
                "engine": "temporal",
                "report": "",
                "sources": [],
                "conflicts": [],
                "review_mode": request.review_mode,
            }
            try:
                await self.store.save_package_review(
                    queued,
                    user_id=principal.user_id,
                    project_id=request.project_id,
                    question=request.question,
                    review_mode=request.review_mode,
                    tenant_id=principal.tenant_id,
                )
                workflow = await submit_package_review(
                    review_id,
                    request.document_ids,
                    request.question,
                    principal.user_id,
                    request.project_id,
                    principal.tenant_id,
                    review_mode=request.review_mode,
                )
            except Exception:
                await self.store.settle_budget(workflow_id, 0, status="failed")
                raise
            queued["workflow"] = workflow
            return queued

        try:
            result = await run_package_review(
                request,
                tenant_id=principal.tenant_id,
                user_id=principal.user_id,
            )
        except ValueError as exc:
            await self.store.settle_budget(workflow_id, 0, status="failed")
            raise ReviewApplicationError("invalid_documents", str(exc)) from exc
        except ReviewAgentError as exc:
            await self.store.settle_budget(workflow_id, 0, status="failed")
            raise ReviewApplicationError("agent", str(exc)) from exc
        except Exception:
            await self.store.settle_budget(workflow_id, 0, status="failed")
            raise
        result["review_id"] = review_id
        result["workflow"] = None
        result["review_mode"] = request.review_mode
        await self.store.save_package_review(
            result,
            user_id=principal.user_id,
            project_id=request.project_id,
            question=request.question,
            review_mode=request.review_mode,
            tenant_id=principal.tenant_id,
        )
        actual_tokens = self.actual_tokens(result.get("usage", {}))
        await self.store.settle_budget(workflow_id, actual_tokens, self.estimated_cost(actual_tokens))
        return result

    async def status(self, review_id: str, principal: Principal) -> dict[str, Any]:
        review = await self.store.get_package_review(review_id)
        if review is None:
            raise ReviewApplicationError("not_found", "资料包审查不存在或无访问权限")
        await self.authorization.authorize(principal, review["project_id"])
        if review["tenant_id"] != principal.tenant_id:
            raise ReviewApplicationError("not_found", "资料包审查不存在或无访问权限")
        workflow = None
        if self.settings.TEMPORAL_ENABLED:
            try:
                workflow = await get_workflow_state(f"package-review:{review_id}")
            except Exception as exc:
                workflow = {"status": "unavailable", "error_type": type(exc).__name__}
        return {
            "review_id": review_id,
            "project_id": review["project_id"],
            "status": review["status"],
            "review_mode": review.get("review_mode", "full"),
            "issue_count": len(review.get("issues", [])),
            "conflict_count": len(review.get("conflicts", [])),
            "human_review_required": review.get("human_review_required", False),
            "lock_version": review.get("lock_version", 1),
            "workers": sorted(review.get("worker_results", {}).keys()),
            "workflow": workflow,
        }

    async def report(
        self, review_id: str, principal: Principal, *, public_only: bool = False,
    ) -> dict[str, Any]:
        review = await self.store.get_package_review(review_id)
        if review is None:
            raise ReviewApplicationError("not_found", "资料包审查不存在或无访问权限")
        await self.authorization.authorize(principal, review["project_id"])
        if review["tenant_id"] != principal.tenant_id:
            raise ReviewApplicationError("not_found", "资料包审查不存在或无访问权限")
        if public_only:
            for source in review.get("sources", []):
                if source.get("source_type") != "document":
                    continue
                document_id = str(source.get("source_id", "")).split(":", 1)[0]
                document = await self.store.get_document(document_id)
                if document is None or document["data_classification"] != "public":
                    raise ReviewApplicationError("forbidden", "MCP不能读取包含非public资料的审查报告")
        return {
            "review_id": review["review_id"],
            "project_id": review["project_id"],
            "status": review["status"],
            "review_mode": review["review_mode"],
            "report": review["report"],
            "review_plan": review["review_plan"],
            "worker_results": review["worker_results"],
            "issues": review["issues"],
            "sources": review["sources"],
            "conflicts": review["conflicts"],
            "human_review_required": review["human_review_required"],
            "lock_version": review["lock_version"],
            "created_at": review["created_at"],
        }

    async def cancel(self, review_id: str, principal: Principal) -> dict[str, Any]:
        review = await self.store.get_package_review(review_id)
        if review is None:
            raise ReviewApplicationError("not_found", "资料包审查不存在或无访问权限")
        await self.authorization.authorize(principal, review["project_id"])
        if principal.role != "admin" and review["user_id"] != principal.user_id:
            raise ReviewApplicationError("forbidden", "只能取消自己发起的审查")
        if not self.settings.TEMPORAL_ENABLED:
            raise ReviewApplicationError("workflow", "Temporal未启用")
        try:
            return await cancel_workflow(f"package-review:{review_id}")
        except Exception as exc:
            raise ReviewApplicationError("workflow", f"取消审查失败: {type(exc).__name__}") from exc

    async def decide(
        self,
        review_id: str,
        principal: Principal,
        decision: str,
        *,
        expected_lock_version: int,
        reason: str = "",
    ) -> dict[str, Any]:
        review = await self.store.get_package_review(review_id)
        if review is None:
            raise ReviewApplicationError("not_found", "资料包审查不存在或无访问权限")
        await self.authorization.authorize(principal, review["project_id"], {"reviewer"})
        if int(review.get("lock_version", 1)) != expected_lock_version:
            raise ReviewApplicationError("conflict", "审查报告已更新，请刷新后重试")
        if decision not in {"approved", "rejected"}:
            raise ReviewApplicationError("invalid_decision", "不支持的审查决定")
        if not self.settings.TEMPORAL_ENABLED:
            raise ReviewApplicationError("workflow", "Temporal未启用")
        try:
            state = await signal_workflow(f"package-review:{review_id}", decision, reason)
        except Exception as exc:
            raise ReviewApplicationError("workflow", f"提交审查决定失败: {type(exc).__name__}") from exc
        return {"review_id": review_id, "status": "decision_requested", "decision": decision, "workflow": state}


package_review_application = PackageReviewApplicationService()
