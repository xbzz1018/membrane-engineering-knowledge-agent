"""Transactional version/decision/publication fences for preliminary project plans."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import insert, select, update
from sqlalchemy.exc import IntegrityError

from src.domain.project_plan import canonical, digest
from src.infrastructure.database import (
    project_plan_artifacts as artifacts,
)
from src.infrastructure.database import (
    project_plan_decisions as decisions,
)
from src.infrastructure.database import (
    project_plan_reviews as reviews,
)
from src.infrastructure.database import (
    project_plan_versions as versions,
)
from src.infrastructure.database import (
    project_plans as plans,
)

TEMPLATE_VERSION = "preliminary-v1"
RENDERER_VERSION = "docx-v2"
FINAL = {"needs_revision", "awaiting_approval", "decision_pending", "approved", "rejected", "cancelled"}


class PlanConflict(ValueError):
    pass


class PlanOwnershipLost(PlanConflict):
    pass


def now():
    return datetime.now(UTC)


def stable_id(value):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "membrane:proposal:" + value))


class ProjectPlanRepository:
    def __init__(self, store):
        self.store = store

    async def _locked(self, session, plan_id):
        row = (await session.execute(select(plans).where(plans.c.id == plan_id).with_for_update())).mappings().first()
        if row is None:
            raise LookupError("方案不存在")
        return dict(row)

    async def _bump(self, session, row, **values):
        result = await session.execute(update(plans).where(
            plans.c.id == row["id"], plans.c.lock_version == row["lock_version"],
        ).values(lock_version=row["lock_version"] + 1, **values))
        if not result.rowcount:
            raise PlanConflict("方案已被其他操作修改，请刷新")

    @staticmethod
    def _where(plan_id, version):
        return (versions.c.plan_id == plan_id, versions.c.version == version)

    async def _version(self, session, plan_id, version):
        row = (await session.execute(select(versions).where(*self._where(plan_id, version)))).mappings().first()
        if row is None:
            raise LookupError("方案版本不存在")
        return dict(row)

    async def list(self, tenant_id, project_id):
        async with self.store.session_factory() as session:
            rows = (await session.execute(select(plans).where(
                plans.c.tenant_id == tenant_id, plans.c.project_id == project_id,
            ).order_by(plans.c.created_at.desc()).limit(100))).mappings().all()
        return [dict(row) for row in rows]

    async def get(self, plan_id, version=None):
        async with self.store.session_factory() as session:
            plan = await self._locked(session, plan_id)
            body = await self._version(session, plan_id, version or plan["current_version"])
            review = (await session.execute(select(reviews).where(
                reviews.c.plan_id == plan_id, reviews.c.version == body["version"],
            ))).mappings().first()
            decision = (await session.execute(select(decisions).where(
                decisions.c.plan_id == plan_id, decisions.c.version == body["version"],
            ))).mappings().first()
            files = (await session.execute(select(artifacts).where(
                artifacts.c.plan_id == plan_id, artifacts.c.version == body["version"],
            ))).mappings().all()
        for key in ("requirements", "content", "manifest", "usage"):
            body[key] = json.loads(body[key]) if body[key] else None
        return {**plan, "plan_id": plan["id"], **body,
                "review": {**dict(review), "result": json.loads(review["result"])} if review else None,
                "decision": dict(decision) if decision else None, "artifacts": [dict(row) for row in files]}

    async def create(self, principal, project_id, request):
        request_hash = digest(request.requirements.model_dump(mode="json"))
        key = (plans.c.tenant_id == principal.tenant_id, plans.c.project_id == project_id,
               plans.c.created_by == principal.user_id, plans.c.request_id == request.request_id)
        async with self.store.session_factory() as session:
            existing = (await session.execute(select(plans).where(*key))).mappings().first()
            if existing:
                if existing["request_hash"] != request_hash:
                    raise PlanConflict("同一请求ID已绑定不同需求")
                return existing["id"]
            plan_id = str(uuid.uuid4())
            try:
                await session.execute(insert(plans).values(
                    id=plan_id, tenant_id=principal.tenant_id, project_id=project_id, created_by=principal.user_id,
                    request_id=request.request_id, request_hash=request_hash,
                    current_version=1, lock_version=1, created_at=now(),
                ))
                await session.execute(insert(versions).values(
                    plan_id=plan_id, version=1, parent_version=None, request_id=request.request_id,
                    request_hash=request_hash, status="queued", requirements=canonical(request.requirements.model_dump()),
                    content=None, content_hash="", manifest=None, manifest_hash="", usage="{}",
                    workflow_id=f"project-plan:{plan_id}:v1", execution_id="", attempt=0, error_type="",
                    reason="初始生成", created_by=principal.user_id, updated_at=now(),
                ))
                await session.commit()
            except IntegrityError:
                await session.rollback()
                # A concurrent identical request won; validate its hash on the next read.
                return await self.create(principal, project_id, request)
        return plan_id

    async def acquire(self, plan_id, version, stage, claim):
        """A retry may take over only the same Activity identity with a larger attempt."""
        async with self.store.session_factory() as session:
            plan = await self._locked(session, plan_id)
            row = await self._version(session, plan_id, version)
            if row["status"] in FINAL or (stage == "generating" and row["content"]):
                return False
            if plan["current_version"] != version:
                raise PlanOwnershipLost("旧方案版本不能继续执行")
            if row["status"] == stage:
                if row["execution_id"] != claim[0] or row["attempt"] >= claim[1]:
                    raise PlanOwnershipLost("方案步骤已被其他执行或更新尝试认领")
            elif row["status"] not in {"queued", "generated", "failed"}:
                raise PlanOwnershipLost("方案步骤状态不允许认领")
            if stage == "reviewing" and not row["content"]:
                raise PlanConflict("尚无待审方案")
            await self._bump(session, plan)
            await session.execute(update(versions).where(*self._where(plan_id, version)).values(
                status=stage, execution_id=claim[0], attempt=claim[1], error_type="", updated_at=now(),
            ))
            await session.commit()
            return True

    @staticmethod
    def _owns(row, claim, status):
        if (row["execution_id"], row["attempt"], row["status"]) != (*claim, status):
            raise PlanOwnershipLost("执行已过期，拒绝迟到结果")

    async def freeze(self, plan_id, version, manifest, claim):
        async with self.store.session_factory() as session:
            plan = await self._locked(session, plan_id)
            row = await self._version(session, plan_id, version)
            self._owns(row, claim, "generating")
            if row["manifest"]:
                return json.loads(row["manifest"])
            if plan["current_version"] != version:
                raise PlanOwnershipLost("方案已改版")
            await self._bump(session, plan)
            await session.execute(update(versions).where(*self._where(plan_id, version)).values(
                manifest=canonical(manifest), manifest_hash=digest(manifest), updated_at=now(),
            ))
            await session.commit()
        return manifest

    async def save_generated(self, plan_id, version, content, usage, claim):
        async with self.store.session_factory() as session:
            plan = await self._locked(session, plan_id)
            row = await self._version(session, plan_id, version)
            self._owns(row, claim, "generating")
            if plan["current_version"] != version or row["content"] or not row["manifest"]:
                raise PlanOwnershipLost("方案内容不可覆盖或依据未冻结")
            await self._bump(session, plan)
            content_hash = digest({"content": content, "manifest_hash": row["manifest_hash"]})
            await session.execute(update(versions).where(*self._where(plan_id, version)).values(
                status="generated", content=canonical(content), content_hash=content_hash,
                usage=canonical(usage), updated_at=now(),
            ))
            await session.commit()

    async def save_review(self, plan_id, version, result, claim):
        async with self.store.session_factory() as session:
            plan = await self._locked(session, plan_id)
            row = await self._version(session, plan_id, version)
            self._owns(row, claim, "reviewing")
            if plan["current_version"] != version:
                raise PlanOwnershipLost("旧版本审查不能发布")
            review_id = stable_id(f"review:{plan_id}:{version}:{row['content_hash']}:{row['manifest_hash']}")
            passed = not any(issue.get("blocking") for issue in result["issues"])
            await self._bump(session, plan)
            await session.execute(insert(reviews).values(
                id=review_id, plan_id=plan_id, version=version, content_hash=row["content_hash"],
                manifest_hash=row["manifest_hash"], passed=int(passed), result=canonical(result), created_at=now(),
            ))
            await session.execute(update(versions).where(*self._where(plan_id, version)).values(
                status="awaiting_approval" if passed else "needs_revision", updated_at=now(),
            ))
            await session.commit()

    async def fail(self, plan_id, version, claim, error_type, cancelled=False):
        async with self.store.session_factory() as session:
            plan = await self._locked(session, plan_id)
            row = await self._version(session, plan_id, version)
            if row["status"] in FINAL or (row["execution_id"], row["attempt"]) != claim:
                return
            await self._bump(session, plan)
            await session.execute(update(versions).where(*self._where(plan_id, version)).values(
                status="cancelled" if cancelled else "failed", error_type=error_type[:128], updated_at=now(),
            ))
            await session.commit()

    async def revise(self, plan_id, principal, request):
        request_hash = digest({**request.model_dump(mode="json"), "actor": principal.user_id})
        async with self.store.session_factory() as session:
            plan = await self._locked(session, plan_id)
            existing = (await session.execute(select(versions).where(
                versions.c.plan_id == plan_id, versions.c.request_id == request.request_id,
            ))).mappings().first()
            if existing:
                if existing["request_hash"] != request_hash:
                    raise PlanConflict("修订请求ID已绑定不同修改")
                return existing["version"]
            base = await self._version(session, plan_id, request.base_version)
            if (plan["current_version"] != request.base_version or plan["lock_version"] != request.expected_lock_version
                    or base["status"] not in {"needs_revision", "awaiting_approval", "approved", "rejected"}):
                raise PlanConflict("父版本、锁版本或方案状态已变化")
            content = request.content.model_dump(mode="json")
            version = request.base_version + 1
            await self._bump(session, plan, current_version=version)
            await session.execute(insert(versions).values(
                plan_id=plan_id, version=version, parent_version=request.base_version,
                request_id=request.request_id, request_hash=request_hash, status="generated",
                requirements=canonical(content["requirements"]), content=canonical(content),
                content_hash=digest({"content": content, "manifest_hash": base["manifest_hash"]}),
                manifest=base["manifest"], manifest_hash=base["manifest_hash"], usage="{}",
                workflow_id=f"project-plan:{plan_id}:v{version}", execution_id="", attempt=0, error_type="",
                reason=request.reason, created_by=principal.user_id, updated_at=now(),
            ))
            await session.commit()
        return version

    async def decide(self, plan_id, version, principal, request, deferred):
        request_hash = digest({**request.model_dump(), "plan_id": plan_id, "version": version, "actor": principal.user_id})
        async with self.store.session_factory() as session:
            plan = await self._locked(session, plan_id)
            existing = (await session.execute(select(decisions).where(
                decisions.c.command_id == request.command_id,
            ))).mappings().first()
            if existing:
                if existing["request_hash"] != request_hash:
                    raise PlanConflict("决定命令ID已用于其他操作")
                return
            row = await self._version(session, plan_id, version)
            review = (await session.execute(select(reviews).where(reviews.c.id == request.review_id))).mappings().first()
            if (plan["current_version"] != version or plan["lock_version"] != request.expected_lock_version
                    or row["status"] not in {"awaiting_approval", "needs_revision"}):
                raise PlanConflict("当前版本、锁版本或审批状态已变化")
            if (not review or review["plan_id"] != plan_id or review["version"] != version
                    or row["content_hash"] != review["content_hash"] or row["content_hash"] != request.content_hash
                    or row["manifest_hash"] != review["manifest_hash"] or row["manifest_hash"] != request.manifest_hash):
                raise PlanConflict("决定必须绑定同一方案版本、内容、来源和审查")
            if request.decision == "approved" and (not review["passed"] or row["status"] != "awaiting_approval"):
                raise PlanConflict("方案仍有阻断问题，不能批准")
            # A failed gate ends the workflow without approval polling; a rejection
            # for such a version can therefore be committed directly.
            pending = deferred and row["status"] == "awaiting_approval"
            await self._bump(session, plan)
            await session.execute(insert(decisions).values(
                command_id=request.command_id, plan_id=plan_id, version=version, review_id=request.review_id,
                content_hash=row["content_hash"], manifest_hash=row["manifest_hash"], actor=principal.user_id,
                decision=request.decision, reason=request.reason, request_hash=request_hash,
                consumed=int(not pending), created_at=now(),
            ))
            await session.execute(update(versions).where(*self._where(plan_id, version)).values(
                status="decision_pending" if pending else request.decision, updated_at=now(),
            ))
            await session.commit()

    async def consume_decision(self, plan_id, version):
        async with self.store.session_factory() as session:
            plan = await self._locked(session, plan_id)
            row = await self._version(session, plan_id, version)
            command = (await session.execute(select(decisions).where(
                decisions.c.plan_id == plan_id, decisions.c.version == version,
            ))).mappings().first()
            if plan["current_version"] != version:
                return {"status": "superseded"}
            if not command:
                return None
            if command["consumed"]:
                return {"status": command["decision"], "command_id": command["command_id"]}
            if row["status"] != "decision_pending":
                raise PlanConflict("决定状态不一致")
            await self._bump(session, plan)
            await session.execute(update(decisions).where(decisions.c.command_id == command["command_id"]).values(consumed=1))
            await session.execute(update(versions).where(*self._where(plan_id, version)).values(
                status=command["decision"], updated_at=now(),
            ))
            await session.commit()
            return {"status": command["decision"], "command_id": command["command_id"]}

    async def settle(self, plan_id, version, status):
        receipt = await self.consume_decision(plan_id, version)
        if receipt:
            return receipt
        async with self.store.session_factory() as session:
            plan = await self._locked(session, plan_id)
            row = await self._version(session, plan_id, version)
            if row["status"] in {"approved", "rejected", "decision_pending", "needs_revision"}:
                return {"status": row["status"]}
            await self._bump(session, plan)
            await session.execute(update(versions).where(*self._where(plan_id, version)).values(
                status=status, error_type="WorkflowTerminated" if status == "failed" else "", updated_at=now(),
            ))
            await session.commit()
        return {"status": status}

    async def cancel(self, plan_id, version, expected_lock):
        async with self.store.session_factory() as session:
            plan = await self._locked(session, plan_id)
            row = await self._version(session, plan_id, version)
            if plan["lock_version"] != expected_lock or plan["current_version"] != version:
                raise PlanConflict("取消时版本已变化")
            if row["status"] in {"approved", "rejected", "decision_pending"}:
                raise PlanConflict("已提交决定的方案不能取消")
            await self._bump(session, plan)
            await session.execute(update(versions).where(*self._where(plan_id, version)).values(status="cancelled", updated_at=now()))
            await session.commit()

    async def _approved(self, session, plan_id, version):
        plan = await self._locked(session, plan_id)
        row = await self._version(session, plan_id, version)
        decision = (await session.execute(select(decisions).where(
            decisions.c.plan_id == plan_id, decisions.c.version == version,
        ))).mappings().first()
        if (plan["current_version"] != version or row["status"] != "approved" or not decision
                or not decision["consumed"] or decision["decision"] != "approved"
                or decision["content_hash"] != row["content_hash"] or decision["manifest_hash"] != row["manifest_hash"]):
            raise PlanConflict("只有当前版本经同版审查与人工批准后才能导出/下载")
        review = (await session.execute(select(reviews).where(reviews.c.id == decision["review_id"]))).mappings().first()
        if (not review or not review["passed"] or review["plan_id"] != plan_id or review["version"] != version
                or review["content_hash"] != row["content_hash"] or review["manifest_hash"] != row["manifest_hash"]):
            raise PlanConflict("批准绑定的审查已不一致")
        return plan, row

    async def reserve_artifact(self, plan_id, version, format):
        identity = f"{plan_id}:{version}:{format}:{TEMPLATE_VERSION}:{RENDERER_VERSION}"
        artifact_id = stable_id(identity)
        async with self.store.session_factory() as session:
            plan, row = await self._approved(session, plan_id, version)
            existing = (await session.execute(select(artifacts).where(artifacts.c.id == artifact_id))).mappings().first()
            if existing:
                return dict(existing)
            await self._bump(session, plan)
            value = dict(id=artifact_id, plan_id=plan_id, version=version,
                         content_hash=row["content_hash"], manifest_hash=row["manifest_hash"], format=format,
                         template_version=TEMPLATE_VERSION, renderer_version=RENDERER_VERSION, status="queued",
                         execution_id="", attempt=0, object_key="", sha256="", byte_size=0, error_type="", created_at=now())
            await session.execute(insert(artifacts).values(**value))
            await session.commit()
            return value

    async def get_artifact(self, artifact_id):
        async with self.store.session_factory() as session:
            row = (await session.execute(select(artifacts).where(artifacts.c.id == artifact_id))).mappings().first()
        if row is None:
            raise LookupError("文件不存在")
        return dict(row)

    async def claim_artifact(self, artifact_id, claim):
        async with self.store.session_factory() as session:
            item = await self.get_artifact(artifact_id)
            plan, row = await self._approved(session, item["plan_id"], item["version"])
            item = dict((await session.execute(select(artifacts).where(artifacts.c.id == artifact_id))).mappings().one())
            if item["status"] == "published":
                return False
            if item["status"] == "rendering" and (item["execution_id"] != claim[0] or item["attempt"] >= claim[1]):
                raise PlanOwnershipLost("导出已被其他执行认领")
            if item["content_hash"] != row["content_hash"] or item["manifest_hash"] != row["manifest_hash"]:
                raise PlanConflict("导出绑定内容不一致")
            await self._bump(session, plan)
            await session.execute(update(artifacts).where(artifacts.c.id == artifact_id).values(
                status="rendering", execution_id=claim[0], attempt=claim[1], error_type="",
            ))
            await session.commit()
            return True

    async def publish_artifact(self, artifact_id, claim, object_key, sha256, byte_size):
        async with self.store.session_factory() as session:
            item = await self.get_artifact(artifact_id)
            plan, _row = await self._approved(session, item["plan_id"], item["version"])
            await self._bump(session, plan)
            result = await session.execute(update(artifacts).where(
                artifacts.c.id == artifact_id, artifacts.c.status == "rendering",
                artifacts.c.execution_id == claim[0], artifacts.c.attempt == claim[1],
            ).values(status="published", object_key=object_key, sha256=sha256, byte_size=byte_size))
            if not result.rowcount:
                raise PlanOwnershipLost("拒绝过期导出发布")
            await session.commit()

    async def fail_artifact(self, artifact_id, claim, error_type):
        async with self.store.session_factory() as session:
            await session.execute(update(artifacts).where(
                artifacts.c.id == artifact_id, artifacts.c.execution_id == claim[0],
                artifacts.c.attempt == claim[1], artifacts.c.status == "rendering",
            ).values(status="failed", error_type=error_type[:128]))
            await session.commit()

    async def assert_download(self, artifact_id):
        async with self.store.session_factory() as session:
            item = await self.get_artifact(artifact_id)
            await self._approved(session, item["plan_id"], item["version"])
            if item["status"] != "published":
                raise PlanConflict("文件尚未完成")
            return item
