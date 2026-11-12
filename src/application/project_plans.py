"""The proposal use cases shared by HTTP, chat and Temporal Activities."""

from __future__ import annotations

import asyncio
import hashlib
import json

from sqlalchemy import select

from src.agents.conversation_supervisor import ConversationSupervisor
from src.agents.knowledge_agent import AgentProtocolError, KnowledgeAgent
from src.agents.project_plan_agents import ProjectPlanWriter, ProjectReviewAdapter
from src.agents.review_agents import PackageReviewService
from src.application.authorization import ProjectAccessError, ProjectAuthorizationService
from src.core.config import get_settings
from src.core.security import Principal
from src.domain.chat_routing import ChatRoutingDecision
from src.domain.project_plan import PlanContent, PlanRequirements, digest, material_matches, plan_gate
from src.infrastructure.database import (
    document_business_metadata,
    document_chunks,
    documents,
    specs,
    storage,
)
from src.infrastructure.model_provider import get_role_model_provider
from src.infrastructure.project_plan_repository import PlanConflict, ProjectPlanRepository

WRITE_ROLES = {"admin", "design_engineer", "material_procurement"}
REVIEW_ROLES = {"admin", "reviewer"}


def plain(value):
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


class ProjectPlanService:
    def __init__(self, store=storage, supervisor=None, writer=None, reviewer=None):
        self.store = store
        self.repo = ProjectPlanRepository(store)
        self.authorization = ProjectAuthorizationService(store)
        self.supervisor = supervisor
        self.writer = writer
        self.reviewer = reviewer

    def _agents(self):
        if self.supervisor is None:
            self.supervisor = ConversationSupervisor(KnowledgeAgent(self.store))
        if self.writer is None:
            self.writer = ProjectPlanWriter(get_role_model_provider("supervisor"))
        if self.reviewer is None:
            self.reviewer = ProjectReviewAdapter(PackageReviewService(self.store))

    async def authorize_plan(self, principal, plan_id, version=None, roles=None):
        record = await self.repo.get(plan_id, version)
        if record["tenant_id"] != principal.tenant_id:
            raise LookupError("方案不存在")
        await self.authorization.authorize(principal, record["project_id"], roles)
        return record

    async def _actor(self, plan_id, version):
        record = await self.repo.get(plan_id, version)
        user = await self.store.get_user(record["created_by"])
        if not user or not user["is_active"] or user["tenant_id"] != record["tenant_id"]:
            raise ProjectAccessError("forbidden", "方案执行身份已不可用")
        principal = Principal(user["id"], user["username"], user["tenant_id"], user["role"])
        await self.authorization.authorize(principal, record["project_id"], WRITE_ROLES)
        return principal, record

    async def create(self, principal, project_id, request):
        await self.authorization.authorize(principal, project_id, WRITE_ROLES)
        plan_id = await self.repo.create(principal, project_id, request)
        return await self.start(principal, plan_id, 1)

    async def start(self, principal, plan_id, version):
        record = await self.authorize_plan(principal, plan_id, version, WRITE_ROLES)
        if get_settings().TEMPORAL_ENABLED:
            from src.workflows.project_generation import submit_project_workflow

            workflow = await submit_project_workflow(plan_id, version)
        else:
            # Deliberately synchronous Local adapter. This is not a background
            # task or a claim that Temporal was used.
            if record["status"] not in {"approved", "rejected", "awaiting_approval", "needs_revision", "cancelled", "decision_pending"}:
                await self.generate(plan_id, version, (f"local-generate:{plan_id}:{version}", record["attempt"] + 1))
                latest = await self.repo.get(plan_id, version)
                await self.review(plan_id, version, (f"local-review:{plan_id}:{version}", latest["attempt"] + 1))
            workflow = {"enabled": False, "status": "local_inline", "workflow_id": record["workflow_id"]}
        return {**self.public(await self.repo.get(plan_id, version)), "workflow": workflow}

    async def _source(self, record, evidence_id):
        """Rehydrate authoritative original data, not the query agent's prose."""
        if evidence_id.startswith("spec:"):
            spec_id = evidence_id.removeprefix("spec:")
            async with self.store.session_factory() as session:
                row = (await session.execute(select(specs).where(
                    specs.c.id == spec_id, specs.c.tenant_id == record["tenant_id"],
                ))).mappings().first()
            if not row or row["status"] != "active" or row["visibility"] != "public":
                raise PlanConflict("材料来源已失效或不可访问")
            payload = json.loads(row["payload"])
            text = json.dumps(payload, ensure_ascii=False)
            fingerprint = digest({"payload": payload, "lock_version": row["lock_version"], "visibility": row["visibility"]})
            return {"evidence_id": evidence_id, "source_type": "material_spec", "text": text[:2000],
                    "content_sha256": hashlib.sha256(text.encode()).hexdigest(), "source_fingerprint": fingerprint,
                    "filename": row["material"] or spec_id, "location": "材料台账 " + spec_id,
                    "version": row["source_version"], "document_id": "", "document_sha256": ""}
        async with self.store.session_factory() as session:
            chunk = (await session.execute(select(document_chunks).where(document_chunks.c.id == evidence_id))).mappings().first()
            if chunk is None:
                raise PlanConflict("原始片段已不可访问")
            document = (await session.execute(select(documents).where(documents.c.id == chunk["document_id"]))).mappings().first()
            business = (await session.execute(select(document_business_metadata).where(
                document_business_metadata.c.document_id == chunk["document_id"],
            ))).mappings().first()
        if (not document or document["tenant_id"] != record["tenant_id"] or document["project_id"] != record["project_id"]
                or document["status"] != "indexed" or document["data_classification"] != "public"
                or chunk["status"] != "processed"):
            raise PlanConflict("来源已失效、分级变化或不属于当前项目")
        text_sha = hashlib.sha256(chunk["text"].encode()).hexdigest()
        fingerprint = digest({"document_sha": document["sha256"], "version": document["version"],
                              "text_sha": text_sha, "business_metadata": plain(dict(business)) if business else None})
        return {"evidence_id": evidence_id, "source_type": "document", "text": chunk["text"][:2000],
                "content_sha256": text_sha, "document_sha256": document["sha256"], "source_fingerprint": fingerprint,
                "document_id": document["id"], "filename": document["filename"],
                "location": chunk["location"] or f"第{chunk['page_number']}页", "version": str(document["version"]),
                "business_metadata": plain(dict(business)) if business else None}

    async def validate_sources(self, record):
        manifest = record["manifest"]
        if not manifest or digest(manifest) != record["manifest_hash"]:
            raise PlanConflict("来源快照完整性校验失败")
        if record["content"] and digest({"content": record["content"], "manifest_hash": record["manifest_hash"]}) != record["content_hash"]:
            raise PlanConflict("方案内容完整性校验失败")
        # Access checks run again at each model call, approval, publication and
        # download. Frozen content is never silently replaced by newer data.
        for frozen in manifest.get("evidence", []):
            current = await self._source(record, frozen["evidence_id"])
            if current["source_fingerprint"] != frozen["source_fingerprint"]:
                raise PlanConflict("来源在冻结后发生变化，需要重新取证生成方案")

    async def _collect(self, principal, record, requirements):
        decision = ChatRoutingDecision(
            intent="combined_query", retrieval_query=requirements.purpose + " 历史项目案例",
            material_query=requirements.preferred_membrane or "膜材规格",
        )
        tools = self.supervisor._query_tools(principal, record["project_id"], decision, [])

        async def query(role):
            result = await asyncio.wait_for(tools[role].ainvoke({}), get_settings().CHAT_QUERY_TIMEOUT_SECONDS)
            if result.get("outcome") not in {"ok", "no_results"}:
                raise AgentProtocolError("方案取证未成功，不能把错误作为没有资料")
            return result

        retrieval, material = await asyncio.gather(query("retrieval"), query("material"))
        roles, sources = {}, {}
        for role, result in (("history", retrieval), ("material", material)):
            roles[role] = []
            for item in result.get("_tool_evidence", [])[:6]:
                evidence_id = item["evidence_id"]
                source = await self._source(record, evidence_id)
                if role == "material" and requirements.preferred_membrane:
                    if not material_matches(requirements.preferred_membrane, source["text"]):
                        continue
                sources[evidence_id] = source
                roles[role].append(evidence_id)
        return {"format_version": 1, "evidence": list(sources.values()), "role_evidence_ids": roles,
                "query_outcomes": {"retrieval": retrieval["outcome"], "material": material["outcome"]},
                "query_usage": {"retrieval": retrieval.get("usage", {}), "material": material.get("usage", {})},
                "excerpt_limit": 2000}

    async def generate(self, plan_id, version, claim):
        if not await self.repo.acquire(plan_id, version, "generating", claim):
            return
        try:
            self._agents()
            principal, record = await self._actor(plan_id, version)
            if (self.writer.provider.metadata.get("mode") == "api"
                    and await self.store.project_has_nonpublic_documents(record["project_id"])):
                raise AgentProtocolError("当前方案项目包含非公开资料，禁止发送到云端模型")
            requirements = PlanRequirements.model_validate(record["requirements"])
            manifest = record["manifest"] or await self._collect(principal, record, requirements)
            manifest = await self.repo.freeze(plan_id, version, manifest, claim)
            record = await self.repo.get(plan_id, version)
            await self.validate_sources(record)
            content, usage = await self.writer.generate(requirements, manifest)
            if content.requirements != requirements:
                raise AgentProtocolError("生成器改写用户需求")
            await self._actor(plan_id, version)
            await self.validate_sources(record)
            await self.repo.save_generated(plan_id, version, content.model_dump(mode="json"), usage, claim)
        except BaseException as exc:
            await asyncio.shield(self.repo.fail(plan_id, version, claim, type(exc).__name__, isinstance(exc, asyncio.CancelledError)))
            raise

    async def review(self, plan_id, version, claim):
        if not await self.repo.acquire(plan_id, version, "reviewing", claim):
            return
        try:
            self._agents()
            _, record = await self._actor(plan_id, version)
            await self.validate_sources(record)
            content = PlanContent.model_validate(record["content"])
            result = await self.reviewer.review(content, record["manifest"])
            # Always merge authoritative gates, even for an injected reviewer.
            for issue in plan_gate(content, record["manifest"]):
                if issue not in result["issues"]:
                    result["issues"].append(issue)
            preference = content.requirements.preferred_membrane
            for index, quote in enumerate(content.source_quotes):
                if quote.purpose == "material" and not material_matches(preference, quote.quote):
                    result["issues"].append({"target_path": f"source_quotes.{index}", "blocking": True,
                                             "message": "材料依据未包含用户声明的材料偏好，需人工完善引用"})
            await self._actor(plan_id, version)
            await self.validate_sources(record)
            await self.repo.save_review(plan_id, version, result, claim)
        except BaseException as exc:
            await asyncio.shield(self.repo.fail(plan_id, version, claim, type(exc).__name__, isinstance(exc, asyncio.CancelledError)))
            raise

    async def revise(self, principal, plan_id, request):
        record = await self.authorize_plan(principal, plan_id, roles=WRITE_ROLES)
        await self.validate_sources(record)
        version = await self.repo.revise(plan_id, principal, request)
        return await self.start(principal, plan_id, version)

    async def decide(self, principal, plan_id, version, request):
        record = await self.authorize_plan(principal, plan_id, version, REVIEW_ROLES)
        await self.validate_sources(record)
        await self.repo.decide(plan_id, version, principal, request, get_settings().TEMPORAL_ENABLED)
        # Polling the durable decision makes a lost wakeup harmless.
        return self.public(await self.repo.get(plan_id, version))

    async def export(self, principal, plan_id, version, request):
        record = await self.authorize_plan(principal, plan_id, version)
        await self.validate_sources(record)
        results = []
        for format in dict.fromkeys(request.formats):
            item = await self.repo.reserve_artifact(plan_id, version, format)
            if item["status"] != "published":
                if get_settings().TEMPORAL_ENABLED:
                    from src.workflows.project_generation import submit_export_workflow

                    await submit_export_workflow(item["id"])
                else:
                    await self.render(item["id"], ("local-export:" + item["id"], item["attempt"] + 1))
            results.append(self.public_artifact(await self.repo.get_artifact(item["id"])))
        return {"plan_id": plan_id, "version": version, "artifacts": results}

    async def render(self, artifact_id, claim):
        from src.documents.project_export import ProjectDocumentService

        if not await self.repo.claim_artifact(artifact_id, claim):
            return
        try:
            item = await self.repo.get_artifact(artifact_id)
            _, record = await self._actor(item["plan_id"], item["version"])
            await self.validate_sources(record)
            renderer = ProjectDocumentService(self.store)
            from src.infrastructure.project_plan_repository import RENDERER_VERSION, TEMPLATE_VERSION

            if item["renderer_version"] != RENDERER_VERSION or item["template_version"] != TEMPLATE_VERSION:
                raise PlanConflict("旧渲染器任务不能使用新模板发布；请从当前批准版本重新申请导出")
            data = await asyncio.to_thread(renderer.render, record, item["format"])
            key, sha = await renderer.store(item, data)
            await self._actor(item["plan_id"], item["version"])
            await self.validate_sources(record)
            await self.repo.publish_artifact(artifact_id, claim, key, sha, len(data))
        except BaseException as exc:
            await asyncio.shield(self.repo.fail_artifact(artifact_id, claim, type(exc).__name__))
            raise

    async def download(self, principal, artifact_id):
        from src.documents.project_export import ProjectDocumentService

        item = await self.repo.get_artifact(artifact_id)
        record = await self.authorize_plan(principal, item["plan_id"], item["version"])
        await self.validate_sources(record)
        item = await self.repo.assert_download(artifact_id)
        data = await ProjectDocumentService(self.store).read(item)
        # Recheck current version after object storage I/O.
        await self.repo.assert_download(artifact_id)
        await self.authorization.authorize(principal, record["project_id"])
        await self.validate_sources(record)
        return data, item

    async def cancel(self, principal, plan_id, version, expected_lock):
        record = await self.authorize_plan(principal, plan_id, version, WRITE_ROLES)
        await self.repo.cancel(plan_id, version, expected_lock)
        if get_settings().TEMPORAL_ENABLED:
            from src.workflows.temporal_app import cancel_workflow

            try:
                await cancel_workflow(record["workflow_id"])
            except Exception:
                # The business fence is committed. A delayed Activity is denied
                # even when the Temporal cancellation request cannot be sent.
                pass
        return self.public(await self.repo.get(plan_id, version))

    @staticmethod
    def public_artifact(item):
        return {key: plain(item[key]) for key in (
            "id", "plan_id", "version", "format", "status", "content_hash", "manifest_hash",
            "template_version", "renderer_version", "sha256", "byte_size", "error_type",
        )} | {"download_url": f"/api/v1/plan-artifacts/{item['id']}/download"}

    @classmethod
    def public(cls, record):
        result = {key: plain(record[key]) for key in (
            "plan_id", "project_id", "current_version", "version", "parent_version", "lock_version", "status",
            "requirements", "content", "content_hash", "manifest_hash", "workflow_id", "error_type", "reason",
            "review", "decision", "updated_at",
        )}
        # Source bodies are business data, but execution identities/object keys
        # are implementation details. The evidence manifest remains inspectable.
        result["source_manifest"] = record["manifest"]
        result["artifacts"] = [cls.public_artifact(item) for item in record["artifacts"]]
        return result


def get_project_plan_service():
    return ProjectPlanService()
