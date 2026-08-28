from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    and_,
    delete,
    insert,
    select,
)
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from src.core.config import get_settings

settings = get_settings()
metadata = MetaData()

tenants = Table(
    "tenants", metadata,
    Column("id", String(64), primary_key=True),
    Column("name", String(256), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

users = Table(
    "users", metadata,
    Column("id", String(64), primary_key=True),
    Column("tenant_id", String(64), nullable=False, index=True),
    Column("username", String(128), nullable=False, unique=True),
    Column("password_hash", Text, nullable=False),
    Column("role", String(32), nullable=False),
    Column("is_active", Integer, nullable=False, default=1),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

projects = Table(
    "projects", metadata,
    Column("id", String(128), primary_key=True),
    Column("tenant_id", String(64), nullable=False, index=True),
    Column("name", String(256), nullable=False),
    Column("status", String(32), nullable=False, default="active"),
    Column("daily_token_limit", Integer, nullable=False),
    Column("monthly_cost_limit_micros", Integer, nullable=False),
    Column("max_concurrent_reviews", Integer, nullable=False),
    Column("reserved_tokens", Integer, nullable=False, default=0),
    Column("used_tokens", Integer, nullable=False, default=0),
    Column("reserved_cost_micros", Integer, nullable=False, default=0),
    Column("used_cost_micros", Integer, nullable=False, default=0),
    Column("token_usage_date", String(10), nullable=False, default=""),
    Column("cost_usage_month", String(7), nullable=False, default=""),
    Column("lock_version", Integer, nullable=False, default=1),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

project_members = Table(
    "project_members", metadata,
    Column("project_id", String(128), primary_key=True),
    Column("user_id", String(64), primary_key=True),
    Column("role", String(32), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

documents = Table(
    "documents", metadata,
    Column("id", String(64), primary_key=True),
    Column("filename", String(512), nullable=False),
    Column("content_type", String(128), nullable=False),
    Column("stored_path", Text, nullable=False),
    Column("tenant_id", String(64), nullable=False, default="membrane-company"),
    Column("project_id", String(128), nullable=False, default="demo-project", index=True),
    Column("sha256", String(64), nullable=False, default=""),
    Column("data_classification", String(16), nullable=False, default="public"),
    Column("parse_method", String(16), nullable=False, default="auto"),
    Column("version", Integer, nullable=False, default=1),
    Column("parser", String(32), nullable=False, default="basic"),
    Column("parser_version", String(64), nullable=False, default=""),
    Column("status", String(32), nullable=False, default="uploaded"),
    Column("lock_version", Integer, nullable=False, default=1),
    Column("error_type", String(128), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("project_id", "sha256", "version", name="uq_document_project_sha_version"),
)

document_chunks = Table(
    "document_chunks", metadata,
    Column("id", String(64), primary_key=True),
    Column("document_id", String(64), nullable=False),
    Column("page_number", Integer, nullable=False, default=1),
    Column("chunk_index", Integer, nullable=False),
    Column("text", Text, nullable=False),
    Column("location", String(512), nullable=False, default=""),
    Column("heading_path", String(1000), nullable=False, default=""),
    Column("sheet_name", String(256), nullable=False, default=""),
    Column("anchor", String(128), nullable=False, default=""),
    Column("source_kind", String(32), nullable=False, default="text"),
    Column("ocr_used", Integer, nullable=False, default=0),
    Column("status", String(32), nullable=False, default="processed"),
    Column("token_count", Integer, nullable=False, default=0),
    Column("sha256", String(64), nullable=False, default=""),
    Column("asset_sha256", String(64), nullable=False, default=""),
)

cases = Table(
    "engineering_cases", metadata,
    Column("id", String(128), primary_key=True),
    Column("payload", Text, nullable=False),
    Column("title", String(512), nullable=False, default=""),
    Column("structure_type", String(256), nullable=False, default=""),
    Column("membrane_material", String(256), nullable=False, default=""),
    Column("application", String(512), nullable=False, default=""),
    Column("year", Integer, nullable=True),
    Column("source_url", Text, nullable=False, default=""),
    Column("source_version", String(128), nullable=False, default=""),
    Column("synthetic", Integer, nullable=False, default=0),
    Column("search_text", Text, nullable=False, default=""),
)

specs = Table(
    "material_specs", metadata,
    Column("id", String(128), primary_key=True),
    Column("payload", Text, nullable=False),
    Column("manufacturer", String(256), nullable=False, default=""),
    Column("material", String(256), nullable=False, default=""),
    Column("product_reference", String(128), nullable=False, default=""),
    Column("specification", Text, nullable=False, default=""),
    Column("application", Text, nullable=False, default=""),
    Column("source_url", Text, nullable=False, default=""),
    Column("source_version", String(128), nullable=False, default=""),
    Column("synthetic", Integer, nullable=False, default=0),
    Column("search_text", Text, nullable=False, default=""),
)

prices = Table(
    "price_records", metadata,
    Column("id", String(128), primary_key=True),
    Column("payload", Text, nullable=False),
    Column("material", String(256), nullable=False, default=""),
    Column("specification", Text, nullable=False, default=""),
    Column("unit", String(64), nullable=False, default=""),
    Column("min_price", Float, nullable=True),
    Column("max_price", Float, nullable=True),
    Column("region", String(128), nullable=False, default=""),
    Column("effective_date", String(32), nullable=False, default=""),
    Column("currency", String(16), nullable=False, default=""),
    Column("source_url", Text, nullable=False, default=""),
    Column("source_version", String(128), nullable=False, default=""),
    Column("synthetic", Integer, nullable=False, default=1),
    Column("search_text", Text, nullable=False, default=""),
)

conversations = Table(
    "conversations", metadata,
    Column("id", String(128), primary_key=True),
    Column("user_id", String(64), nullable=False),
    Column("session_id", String(128), nullable=False),
    Column("role", String(16), nullable=False),
    Column("content", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

memory_items = Table(
    "memory_items", metadata,
    Column("id", String(128), primary_key=True),
    Column("user_id", String(64), nullable=False),
    Column("tenant_id", String(64), nullable=False, default="membrane-company"),
    Column("project_id", String(128), nullable=True),
    Column("scope", String(16), nullable=False, default="user"),
    Column("kind", String(32), nullable=False),
    Column("content", Text, nullable=False),
    Column("source", String(32), nullable=False, default="agent_candidate"),
    Column("source_id", String(128), nullable=False, default=""),
    Column("status", String(16), nullable=False, default="pending"),
    Column("version", Integer, nullable=False, default=1),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("confirmed_at", DateTime(timezone=True), nullable=True),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

batch_imports = Table(
    "batch_imports", metadata,
    Column("id", String(128), primary_key=True),
    Column("status", String(32), nullable=False),
    Column("tenant_id", String(64), nullable=False, default="membrane-company"),
    Column("project_id", String(128), nullable=False, default="demo-project"),
    Column("workflow_id", String(256), nullable=False, default=""),
    Column("document_count", Integer, nullable=False),
    Column("completed_count", Integer, nullable=False, default=0),
    Column("failed_count", Integer, nullable=False, default=0),
    Column("skipped_count", Integer, nullable=False, default=0),
    Column("error_summary", Text, nullable=False, default="[]"),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

package_reviews = Table(
    "package_reviews", metadata,
    Column("id", String(128), primary_key=True),
    Column("user_id", String(64), nullable=False),
    Column("tenant_id", String(64), nullable=False, default="membrane-company"),
    Column("project_id", String(128), nullable=False),
    Column("question", Text, nullable=False),
    Column("status", String(32), nullable=False),
    Column("engine", String(32), nullable=False),
    Column("report", Text, nullable=False),
    Column("conflicts", Text, nullable=False),
    Column("worker_results", Text, nullable=False, default="{}"),
    Column("usage", Text, nullable=False, default="{}"),
    Column("human_review_required", Integer, nullable=False, default=0),
    Column("lock_version", Integer, nullable=False, default=1),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

agent_runs = Table(
    "agent_runs", metadata,
    Column("id", String(128), primary_key=True),
    Column("tenant_id", String(64), nullable=False),
    Column("project_id", String(128), nullable=False),
    Column("user_id", String(64), nullable=False),
    Column("run_type", String(32), nullable=False),
    Column("status", String(32), nullable=False),
    Column("model", String(128), nullable=False, default=""),
    Column("provider", String(64), nullable=False, default=""),
    Column("input_tokens", Integer, nullable=False, default=0),
    Column("output_tokens", Integer, nullable=False, default=0),
    Column("latency_ms", Float, nullable=False, default=0),
    Column("finish_reason", String(32), nullable=False, default=""),
    Column("error_type", String(128), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

agent_steps = Table(
    "agent_steps", metadata,
    Column("id", String(128), primary_key=True),
    Column("run_id", String(128), nullable=False, index=True),
    Column("step_name", String(128), nullable=False),
    Column("operation", String(64), nullable=False),
    Column("status", String(32), nullable=False),
    Column("input_tokens", Integer, nullable=False, default=0),
    Column("output_tokens", Integer, nullable=False, default=0),
    Column("latency_ms", Float, nullable=False, default=0),
    Column("error_type", String(128), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

budget_reservations = Table(
    "budget_reservations", metadata,
    Column("id", String(128), primary_key=True),
    Column("project_id", String(128), nullable=False, index=True),
    Column("workflow_id", String(256), nullable=False, unique=True),
    Column("reserved_tokens", Integer, nullable=False),
    Column("actual_tokens", Integer, nullable=False, default=0),
    Column("estimated_cost_micros", Integer, nullable=False, default=0),
    Column("actual_cost_micros", Integer, nullable=False, default=0),
    Column("status", String(32), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

package_review_evidence = Table(
    "package_review_evidence", metadata,
    Column("id", String(128), primary_key=True),
    Column("review_id", String(128), nullable=False),
    Column("source_id", String(256), nullable=False),
    Column("payload", Text, nullable=False),
)


def _build_engine() -> AsyncEngine:
    url = settings.resolved_database_url
    kwargs: dict[str, Any] = {"echo": False, "pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_async_engine(url, **kwargs)


engine = _build_engine()
SessionFactory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def _now() -> datetime:
    return datetime.now(UTC)


def _terms(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]{2,}", text.lower())


def _score(query: str, value: str) -> int:
    terms = _terms(query)
    haystack = value.lower()
    return sum(haystack.count(term) for term in terms)


def _normalized_payload_values(table: Table, row: dict[str, Any]) -> dict[str, Any]:
    value: dict[str, Any] = {"search_text": json.dumps(row, ensure_ascii=False)}
    if table is cases:
        value.update({
            "title": str(row.get("title", "")),
            "structure_type": str(row.get("structure_type", "")),
            "membrane_material": str(row.get("membrane_material", "")),
            "application": str(row.get("application", "")),
            "year": row.get("year"),
            "source_url": str(row.get("source_url", "")),
            "source_version": str(row.get("source_version", "")),
            "synthetic": int(bool(row.get("synthetic"))),
        })
    elif table is specs:
        value.update({
            "manufacturer": str(row.get("manufacturer", "")),
            "material": str(row.get("material", "")),
            "product_reference": str(row.get("product_reference", "")),
            "specification": str(row.get("specification", "")),
            "application": str(row.get("application", "")),
            "source_url": str(row.get("source_url", "")),
            "source_version": str(row.get("source_version", "")),
            "synthetic": int(bool(row.get("synthetic"))),
        })
    elif table is prices:
        value.update({
            "material": str(row.get("material", "")),
            "specification": str(row.get("specification", "")),
            "unit": str(row.get("unit", "")),
            "min_price": row.get("min_price"),
            "max_price": row.get("max_price"),
            "region": str(row.get("region", "")),
            "effective_date": str(row.get("effective_date", "")),
            "currency": str(row.get("currency", "")),
            "source_url": str(row.get("source_url", "")),
            "source_version": str(row.get("source_version", "")),
            "synthetic": int(bool(row.get("synthetic", True))),
        })
    return value


def _fuse_ranked(
    groups: list[tuple[str, float, list[dict[str, Any]]]],
    key_field: str,
    limit: int,
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    scores: dict[str, float] = {}
    for backend, weight, rows in groups:
        for rank, row in enumerate(rows, 1):
            key = str(row.get(key_field, ""))
            if not key:
                continue
            item = merged.setdefault(key, dict(row))
            retrieval = item.setdefault("retrieval", [])
            existing = row.get("retrieval") or [{"backend": backend, "rank": rank, "score": row.get("raw_score", 0)}]
            for detail in existing:
                if detail not in retrieval:
                    retrieval.append(detail)
            scores[key] = scores.get(key, 0.0) + weight / (60 + rank)
    for key, item in merged.items():
        item["fusion_score"] = round(scores[key], 8)
        item["fusion_method"] = "weighted_rrf(k=60)"
    return sorted(merged.values(), key=lambda row: row["fusion_score"], reverse=True)[:limit]


class EngineeringStorage:
    def __init__(self, session_factory=SessionFactory):
        self.session_factory = session_factory
        self.settings = settings

    async def init(self) -> None:
        if settings.RUNTIME_MODE.lower() == "local":
            (settings.data_path / "../runtime").resolve().mkdir(parents=True, exist_ok=True)
            settings.upload_path.mkdir(parents=True, exist_ok=True)
        async with engine.begin() as conn:
            await conn.run_sync(metadata.create_all)
        await self.ensure_enterprise_bootstrap()
        await self.backfill_normalized_payloads()

    async def backfill_normalized_payloads(self) -> None:
        async with self.session_factory() as session:
            for table in (cases, specs, prices):
                result = await session.execute(select(table.c.id, table.c.payload))
                for row_id, payload in result.all():
                    decoded = json.loads(payload)
                    await session.execute(
                        table.update().where(table.c.id == row_id).values(**_normalized_payload_values(table, decoded))
                    )
            await session.commit()

    async def ensure_enterprise_bootstrap(self) -> None:
        from src.core.security import hash_password

        now = _now()
        async with self.session_factory() as session:
            if not await session.scalar(select(tenants.c.id).where(tenants.c.id == settings.DEFAULT_TENANT_ID)):
                await session.execute(insert(tenants).values(
                    id=settings.DEFAULT_TENANT_ID,
                    name="膜结构工程企业",
                    created_at=now,
                ))
            user_id = await session.scalar(
                select(users.c.id).where(users.c.username == settings.BOOTSTRAP_ADMIN_USERNAME)
            )
            if not user_id:
                user_id = uuid.uuid4().hex
                await session.execute(insert(users).values(
                    id=user_id,
                    tenant_id=settings.DEFAULT_TENANT_ID,
                    username=settings.BOOTSTRAP_ADMIN_USERNAME,
                    password_hash=hash_password(settings.BOOTSTRAP_ADMIN_PASSWORD),
                    role="admin",
                    is_active=1,
                    created_at=now,
                ))
            if not await session.scalar(select(projects.c.id).where(projects.c.id == settings.DEFAULT_PROJECT_ID)):
                await session.execute(insert(projects).values(
                    id=settings.DEFAULT_PROJECT_ID,
                    tenant_id=settings.DEFAULT_TENANT_ID,
                    name="膜结构演示项目",
                    status="active",
                    daily_token_limit=settings.DEFAULT_DAILY_TOKEN_LIMIT,
                    monthly_cost_limit_micros=settings.DEFAULT_MONTHLY_COST_LIMIT_MICROS,
                    max_concurrent_reviews=settings.DEFAULT_MAX_CONCURRENT_REVIEWS,
                    reserved_tokens=0,
                    used_tokens=0,
                    reserved_cost_micros=0,
                    used_cost_micros=0,
                    token_usage_date=now.date().isoformat(),
                    cost_usage_month=now.strftime("%Y-%m"),
                    lock_version=1,
                    created_at=now,
                ))
            existing_member = await session.execute(select(project_members).where(and_(
                project_members.c.project_id == settings.DEFAULT_PROJECT_ID,
                project_members.c.user_id == user_id,
            )))
            if not existing_member.first():
                await session.execute(insert(project_members).values(
                    project_id=settings.DEFAULT_PROJECT_ID,
                    user_id=user_id,
                    role="admin",
                    created_at=now,
                ))
            await session.commit()

    async def close(self) -> None:
        await engine.dispose()

    async def get_user_by_username(self, username: str) -> dict[str, Any] | None:
        async with self.session_factory() as session:
            result = await session.execute(select(users).where(users.c.username == username))
            row = result.mappings().first()
            return dict(row) if row else None

    async def get_user(self, user_id: str) -> dict[str, Any] | None:
        async with self.session_factory() as session:
            result = await session.execute(select(users).where(users.c.id == user_id))
            row = result.mappings().first()
            return dict(row) if row else None

    async def create_user(self, username: str, password_hash: str, role: str) -> dict[str, Any]:
        row = {
            "id": uuid.uuid4().hex,
            "tenant_id": settings.DEFAULT_TENANT_ID,
            "username": username,
            "password_hash": password_hash,
            "role": role,
            "is_active": 1,
            "created_at": _now(),
        }
        async with self.session_factory() as session:
            await session.execute(insert(users).values(**row))
            await session.commit()
        return row

    async def create_project(self, name: str, tenant_id: str) -> dict[str, Any]:
        row = {
            "id": uuid.uuid4().hex,
            "tenant_id": tenant_id,
            "name": name,
            "status": "active",
            "daily_token_limit": settings.DEFAULT_DAILY_TOKEN_LIMIT,
            "monthly_cost_limit_micros": settings.DEFAULT_MONTHLY_COST_LIMIT_MICROS,
            "max_concurrent_reviews": settings.DEFAULT_MAX_CONCURRENT_REVIEWS,
            "reserved_tokens": 0,
            "used_tokens": 0,
            "reserved_cost_micros": 0,
            "used_cost_micros": 0,
            "token_usage_date": _now().date().isoformat(),
            "cost_usage_month": _now().strftime("%Y-%m"),
            "lock_version": 1,
            "created_at": _now(),
        }
        async with self.session_factory() as session:
            await session.execute(insert(projects).values(**row))
            await session.commit()
        return row

    async def add_project_member(self, project_id: str, user_id: str, role: str) -> None:
        async with self.session_factory() as session:
            existing = await session.execute(select(project_members).where(and_(
                project_members.c.project_id == project_id,
                project_members.c.user_id == user_id,
            )))
            if existing.first():
                await session.execute(
                    project_members.update().where(and_(
                        project_members.c.project_id == project_id,
                        project_members.c.user_id == user_id,
                    )).values(role=role)
                )
            else:
                await session.execute(insert(project_members).values(
                    project_id=project_id, user_id=user_id, role=role, created_at=_now(),
                ))
            await session.commit()

    async def project_access(self, project_id: str, user_id: str, tenant_id: str, global_role: str) -> str | None:
        async with self.session_factory() as session:
            project = await session.execute(select(projects).where(and_(
                projects.c.id == project_id,
                projects.c.tenant_id == tenant_id,
                projects.c.status == "active",
            )))
            if not project.first():
                return None
            if global_role == "admin":
                return "admin"
            member = await session.execute(select(project_members.c.role).where(and_(
                project_members.c.project_id == project_id,
                project_members.c.user_id == user_id,
            )))
            return member.scalar_one_or_none()

    async def list_projects_for_user(self, user_id: str, tenant_id: str, global_role: str) -> list[dict[str, Any]]:
        async with self.session_factory() as session:
            if global_role == "admin":
                query = select(projects).where(projects.c.tenant_id == tenant_id)
            else:
                query = (
                    select(projects)
                    .select_from(projects.join(project_members, projects.c.id == project_members.c.project_id))
                    .where(and_(projects.c.tenant_id == tenant_id, project_members.c.user_id == user_id))
                )
            result = await session.execute(query)
            return [dict(row) for row in result.mappings().all()]

    async def add_document(
        self,
        filename: str,
        content_type: str,
        content: bytes,
        parser: str,
        *,
        tenant_id: str | None = None,
        project_id: str | None = None,
        data_classification: str = "public",
        parse_method: str = "auto",
        version: int = 1,
    ) -> dict[str, Any]:
        document_id = uuid.uuid4().hex
        tenant_id = tenant_id or settings.DEFAULT_TENANT_ID
        project_id = project_id or settings.DEFAULT_PROJECT_ID
        content_sha = sha256(content).hexdigest()
        async with self.session_factory() as session:
            existing = await session.execute(select(documents).where(and_(
                documents.c.project_id == project_id,
                documents.c.sha256 == content_sha,
                documents.c.version == version,
            )))
            existing_row = existing.mappings().first()
            if existing_row:
                return dict(existing_row)
        if settings.RUNTIME_MODE.lower() == "full":
            from src.engineering.full_backends import get_full_backends

            stored_path = await get_full_backends().store_document(
                document_id, filename, content_type, content, content_sha=content_sha, version=version,
            )
        else:
            path = settings.upload_path / f"{document_id}_{Path(filename).name}"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            stored_path = str(path)
        row = {
            "id": document_id,
            "filename": filename,
            "content_type": content_type or "application/octet-stream",
            "stored_path": stored_path,
            "tenant_id": tenant_id,
            "project_id": project_id,
            "sha256": content_sha,
            "data_classification": data_classification,
            "parse_method": parse_method,
            "version": version,
            "parser": parser,
            "parser_version": "",
            "status": "uploaded",
            "lock_version": 1,
            "error_type": None,
            "created_at": _now(),
            "updated_at": _now(),
        }
        async with self.session_factory() as session:
            await session.execute(insert(documents).values(**row))
            await session.commit()
        return row

    async def acquire_document_ingest(self, document_id: str) -> bool:
        async with self.session_factory() as session:
            result = await session.execute(
                documents.update()
                .where(and_(documents.c.id == document_id, documents.c.status.in_(["uploaded", "failed", "index_failed"])))
                .values(status="indexing", error_type=None, updated_at=_now(), lock_version=documents.c.lock_version + 1)
            )
            await session.commit()
            return bool(result.rowcount)

    async def fail_document(self, document_id: str, error_type: str) -> None:
        async with self.session_factory() as session:
            await session.execute(
                documents.update().where(documents.c.id == document_id).values(
                    status="failed", error_type=error_type[:128], updated_at=_now(),
                )
            )
            await session.commit()

    async def resolve_document_path(self, row: dict[str, Any]) -> Path:
        if settings.RUNTIME_MODE.lower() == "full":
            from src.engineering.full_backends import get_full_backends

            return await get_full_backends().materialize_document(
                row["stored_path"], row["id"], row["filename"],
            )
        return Path(row["stored_path"])

    async def get_document(self, document_id: str) -> dict[str, Any] | None:
        async with self.session_factory() as session:
            result = await session.execute(select(documents).where(documents.c.id == document_id))
            row = result.mappings().first()
            return dict(row) if row else None

    async def project_has_nonpublic_documents(self, project_id: str) -> bool:
        async with self.session_factory() as session:
            result = await session.execute(select(documents.c.id).where(and_(
                documents.c.project_id == project_id,
                documents.c.data_classification.in_(["internal", "restricted"]),
            )).limit(1))
            return result.first() is not None

    async def list_documents(
        self,
        document_ids: list[str] | None = None,
        *,
        project_id: str | None = None,
        tenant_id: str | None = None,
    ) -> list[dict[str, Any]]:
        async with self.session_factory() as session:
            query = select(documents)
            if document_ids:
                query = query.where(documents.c.id.in_(document_ids))
            if project_id:
                query = query.where(documents.c.project_id == project_id)
            if tenant_id:
                query = query.where(documents.c.tenant_id == tenant_id)
            result = await session.execute(query)
            return [dict(row) for row in result.mappings().all()]

    async def save_chunks(self, document_id: str, chunks: list[dict[str, Any]], parser: str) -> int:
        if settings.RUNTIME_MODE.lower() == "full":
            document = await self.get_document(document_id)
            if document is None:
                raise RuntimeError(f"Document disappeared before indexing: {document_id}")
            from src.engineering.full_backends import get_full_backends

            assets: dict[str, dict[str, Any]] = {}
            for item in chunks:
                if item.get("asset_bytes") and item.get("asset_sha256"):
                    assets[str(item["asset_sha256"])] = item
            for asset in assets.values():
                await get_full_backends().store_derived_asset(
                    document["sha256"],
                    str(asset["asset_sha256"]),
                    str(asset.get("asset_suffix", ".png")),
                    bytes(asset["asset_bytes"]),
                )
        async with self.session_factory() as session:
            await session.execute(delete(document_chunks).where(document_chunks.c.document_id == document_id))
            values = [
                {
                    "id": f"{document_id}:{item['chunk_index']}",
                    "document_id": document_id,
                    "page_number": int(item.get("page_number", 1)),
                    "chunk_index": int(item["chunk_index"]),
                    "text": item["text"],
                    "location": str(item.get("location", "")),
                    "heading_path": str(item.get("heading_path", "")),
                    "sheet_name": str(item.get("sheet_name", "")),
                    "anchor": str(item.get("anchor", "")),
                    "source_kind": str(item.get("source_kind", "text")),
                    "ocr_used": int(bool(item.get("ocr_used", False))),
                    "status": str(item.get("status", "processed")),
                    "token_count": int(item.get("token_count", max(1, len(item["text"]) // 3))),
                    "sha256": str(item.get("sha256") or sha256(item["text"].encode("utf-8")).hexdigest()),
                    "asset_sha256": str(item.get("asset_sha256", "")),
                }
                for item in chunks
            ]
            if values:
                await session.execute(insert(document_chunks), values)
            await session.execute(
                documents.update().where(documents.c.id == document_id).values(
                    status="indexing", parser=parser, parser_version="1", error_type=None,
                    updated_at=_now(), lock_version=documents.c.lock_version + 1,
                )
            )
            await session.commit()
        if settings.RUNTIME_MODE.lower() == "full":
            from src.engineering.full_backends import get_full_backends

            document = await self.get_document(document_id)
            if document is None:
                raise RuntimeError(f"Document disappeared after indexing: {document_id}")
            try:
                await get_full_backends().index_document(document, chunks)
            except Exception as exc:
                async with self.session_factory() as session:
                    await session.execute(documents.update().where(documents.c.id == document_id).values(
                        status="index_failed", error_type=type(exc).__name__, updated_at=_now(),
                    ))
                    await session.commit()
                raise
        async with self.session_factory() as session:
            await session.execute(documents.update().where(documents.c.id == document_id).values(
                status="indexed", error_type=None, updated_at=_now(),
            ))
            await session.commit()
        return len(values)

    async def search_chunks(self, query: str, limit: int = 30, project_id: str = "") -> list[dict[str, Any]]:
        async with self.session_factory() as session:
            statement = select(
                document_chunks,
                documents.c.filename,
                documents.c.version,
                documents.c.created_at,
            ).select_from(document_chunks.join(documents, document_chunks.c.document_id == documents.c.id))
            if project_id:
                statement = statement.where(documents.c.project_id == project_id)
            result = await session.execute(statement)
            rows = [dict(row) for row in result.mappings().all()]
        def score(row: dict[str, Any]) -> int:
            return (_score(query, row["filename"]) * 4) + _score(query, row["text"])

        ranked = sorted(rows, key=score, reverse=True)
        lexical = [row for row in ranked if score(row) > 0][:limit]
        for rank, row in enumerate(lexical, 1):
            row["raw_score"] = score(row)
            row["retrieval"] = [{
                "backend": "postgresql" if settings.RUNTIME_MODE.lower() == "full" else "sqlite",
                "rank": rank,
                "score": score(row),
            }]
        if settings.RUNTIME_MODE.lower() != "full":
            return lexical
        from src.engineering.full_backends import get_full_backends

        vector = await get_full_backends().search_documents(query, limit=limit, project_id=project_id)
        return _fuse_ranked(
            [("postgresql", 1.0, lexical), ("milvus", 1.3, vector)],
            "id",
            limit,
        )

    async def list_document_chunks(self, document_id: str, limit: int = 100) -> list[dict[str, Any]]:
        async with self.session_factory() as session:
            result = await session.execute(
                select(
                    document_chunks,
                    documents.c.filename,
                    documents.c.version,
                    documents.c.created_at,
                )
                .select_from(document_chunks.join(documents, document_chunks.c.document_id == documents.c.id))
                .where(document_chunks.c.document_id == document_id)
                .order_by(document_chunks.c.chunk_index)
                .limit(limit)
            )
            return [dict(row) for row in result.mappings().all()]

    async def count_document_chunks(self, document_id: str) -> int:
        async with self.session_factory() as session:
            result = await session.execute(
                select(document_chunks.c.id).where(document_chunks.c.document_id == document_id)
            )
            return len(result.all())

    async def check_connection(self) -> None:
        async with self.session_factory() as session:
            await session.execute(select(1))

    async def _search_payload_table(
        self,
        table: Table,
        query: str,
        limit: int,
        weighted_fields: dict[str, int],
    ) -> list[dict[str, Any]]:
        async with self.session_factory() as session:
            result = await session.execute(select(table))
            records = [dict(row) for row in result.mappings().all()]

        def score(row: dict[str, Any]) -> int:
            base = _score(query, str(row.get("search_text", "")))
            return base + sum(
                _score(query, str(row.get(field, ""))) * weight
                for field, weight in weighted_fields.items()
            )

        ranked = sorted(records, key=score, reverse=True)
        matched_records = [row for row in ranked if score(row) > 0][:limit]
        backend = "postgresql" if settings.RUNTIME_MODE.lower() == "full" else "sqlite"
        matched = []
        for rank, record in enumerate(matched_records, 1):
            row = json.loads(record["payload"])
            row["raw_score"] = score(record)
            row["retrieval"] = [{
                "backend": backend,
                "rank": rank,
                "score": score(record),
                "match": "normalized_exact_fields+lexical",
            }]
            matched.append(row)
        return matched

    async def search_cases(self, query: str, limit: int = 6) -> list[dict[str, Any]]:
        return await self._search_payload_table(cases, query, limit, {
            "title": 6, "structure_type": 4, "membrane_material": 5, "application": 3, "year": 5,
        })

    async def search_specs(self, query: str, limit: int = 8) -> list[dict[str, Any]]:
        return await self._search_payload_table(specs, query, limit, {
            "product_reference": 8, "material": 6, "manufacturer": 5, "specification": 4,
            "source_version": 5,
        })

    async def search_prices(self, query: str, limit: int = 8) -> list[dict[str, Any]]:
        return await self._search_payload_table(prices, query, limit, {
            "material": 6, "specification": 5, "effective_date": 7, "region": 4, "currency": 5, "unit": 5,
        })

    async def seed_payloads(self, table: Table, rows: list[dict[str, Any]], key: str) -> int:
        if not rows:
            return 0
        async with self.session_factory() as session:
            existing = await session.execute(select(table.c.id))
            existing_ids = {row[0] for row in existing.all()}
            values = []
            for row in rows:
                row_id = str(row.get(key) or "")
                if not row_id or row_id in existing_ids:
                    continue
                value: dict[str, Any] = {
                    "id": row_id,
                    "payload": json.dumps(row, ensure_ascii=False),
                    **_normalized_payload_values(table, row),
                }
                values.append(value)
            if values:
                await session.execute(insert(table), values)
                await session.commit()
            return len(values)

    async def append_message(self, user_id: str, session_id: str, role: str, content: str) -> None:
        async with self.session_factory() as session:
            await session.execute(insert(conversations).values(
                id=uuid.uuid4().hex, user_id=user_id, session_id=session_id,
                role=role, content=content[:8000], created_at=_now(),
            ))
            await session.commit()

    async def create_memory_candidate(
        self,
        *,
        tenant_id: str,
        user_id: str,
        project_id: str | None,
        scope: str,
        kind: str,
        content: str,
        source_id: str = "",
    ) -> dict[str, Any]:
        now = _now()
        row = {
            "id": uuid.uuid4().hex,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "project_id": project_id if scope == "project" else None,
            "scope": scope,
            "kind": kind,
            "content": content[:4000],
            "source": "agent_candidate",
            "source_id": source_id,
            "status": "pending",
            "version": 1,
            "created_at": now,
            "confirmed_at": None,
            "updated_at": now,
        }
        async with self.session_factory() as session:
            await session.execute(insert(memory_items).values(**row))
            await session.commit()
        return row

    async def set_memory_status(self, memory_id: str, user_id: str, status: str) -> dict[str, Any] | None:
        now = _now()
        async with self.session_factory() as session:
            changed = await session.execute(
                memory_items.update().where(and_(
                    memory_items.c.id == memory_id,
                    memory_items.c.user_id == user_id,
                    memory_items.c.status == "pending",
                )).values(
                    status=status,
                    confirmed_at=now if status == "confirmed" else None,
                    updated_at=now,
                )
            )
            await session.commit()
            if not changed.rowcount:
                return None
            result = await session.execute(select(memory_items).where(memory_items.c.id == memory_id))
            row = result.mappings().first()
        if row and status == "confirmed" and settings.RUNTIME_MODE.lower() == "full":
            from src.engineering.full_backends import get_full_backends

            await get_full_backends().index_memory(
                row["id"], row["user_id"], row["kind"], row["content"], now.isoformat(),
                tenant_id=row["tenant_id"], project_id=row["project_id"] or "", scope=row["scope"],
            )
        return dict(row) if row else None

    async def search_memory(
        self,
        user_id: str,
        query: str,
        limit: int = 5,
        *,
        tenant_id: str = "",
        project_id: str = "",
    ) -> list[str]:
        if settings.RUNTIME_MODE.lower() == "full":
            from src.engineering.full_backends import get_full_backends

            return await get_full_backends().search_memories(
                user_id, query, limit, tenant_id=tenant_id, project_id=project_id,
            )
        async with self.session_factory() as session:
            conditions = [memory_items.c.user_id == user_id, memory_items.c.status == "confirmed"]
            if tenant_id:
                conditions.append(memory_items.c.tenant_id == tenant_id)
            if project_id:
                conditions.append((memory_items.c.scope == "user") | (memory_items.c.project_id == project_id))
            result = await session.execute(select(memory_items).where(and_(*conditions)))
            rows = [dict(row) for row in result.mappings().all()]
        ranked = sorted(rows, key=lambda row: _score(query, row["content"]), reverse=True)
        matched = [row["content"] for row in ranked if _score(query, row["content"]) > 0]
        return (matched or [row["content"] for row in ranked])[:limit]

    async def list_memories(
        self,
        user_id: str,
        *,
        project_id: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        async with self.session_factory() as session:
            conditions = [memory_items.c.user_id == user_id]
            if project_id:
                conditions.append((memory_items.c.scope == "user") | (memory_items.c.project_id == project_id))
            if status:
                conditions.append(memory_items.c.status == status)
            result = await session.execute(
                select(memory_items).where(and_(*conditions)).order_by(memory_items.c.created_at.desc())
            )
            return [dict(row) for row in result.mappings().all()]

    async def delete_memory(self, user_id: str, memory_id: str) -> bool:
        async with self.session_factory() as session:
            result = await session.execute(delete(memory_items).where(and_(
                memory_items.c.id == memory_id,
                memory_items.c.user_id == user_id,
            )))
            await session.commit()
            deleted = bool(result.rowcount)
        if deleted and settings.RUNTIME_MODE.lower() == "full":
            from src.engineering.full_backends import get_full_backends

            await get_full_backends().delete_memory(memory_id)
        return deleted

    async def update_memory(self, user_id: str, memory_id: str, content: str) -> dict[str, Any] | None:
        async with self.session_factory() as session:
            current = await session.execute(select(memory_items).where(and_(
                memory_items.c.id == memory_id,
                memory_items.c.user_id == user_id,
            )))
            row = current.mappings().first()
            if not row:
                return None
            was_confirmed = row["status"] == "confirmed"
            await session.execute(memory_items.update().where(memory_items.c.id == memory_id).values(
                content=content[:4000],
                status="pending",
                version=memory_items.c.version + 1,
                confirmed_at=None,
                updated_at=_now(),
            ))
            await session.commit()
            updated = await session.execute(select(memory_items).where(memory_items.c.id == memory_id))
            updated_row = updated.mappings().first()
        if was_confirmed and settings.RUNTIME_MODE.lower() == "full":
            from src.engineering.full_backends import get_full_backends

            await get_full_backends().delete_memory(memory_id)
        return dict(updated_row) if updated_row else None

    async def create_batch_import(
        self,
        document_ids: list[str],
        *,
        tenant_id: str,
        project_id: str,
        workflow_id: str,
        batch_id: str | None = None,
    ) -> dict[str, Any]:
        batch_id = batch_id or uuid.uuid4().hex
        now = _now()
        async with self.session_factory() as session:
            known = await session.execute(select(documents.c.id).where(and_(
                documents.c.id.in_(document_ids),
                documents.c.project_id == project_id,
                documents.c.tenant_id == tenant_id,
            )))
            known_ids = {row[0] for row in known.all()}
            missing = sorted(set(document_ids) - known_ids)
            if missing:
                raise ValueError(f"Documents not found or unauthorized: {', '.join(missing)}")
            await session.execute(insert(batch_imports).values(
                id=batch_id,
                tenant_id=tenant_id,
                project_id=project_id,
                workflow_id=workflow_id,
                status="queued",
                document_count=len(document_ids),
                completed_count=0,
                failed_count=0,
                skipped_count=0,
                error_summary="[]",
                created_at=now,
                updated_at=now,
            ))
            await session.commit()
        return {"batch_id": batch_id, "workflow_id": workflow_id, "status": "queued", "total": len(document_ids)}

    async def get_batch_import(self, batch_id: str, tenant_id: str) -> dict[str, Any] | None:
        async with self.session_factory() as session:
            result = await session.execute(select(batch_imports).where(and_(
                batch_imports.c.id == batch_id,
                batch_imports.c.tenant_id == tenant_id,
            )))
            row = result.mappings().first()
            return dict(row) if row else None

    async def update_batch_import(self, batch_id: str, state: dict[str, Any]) -> None:
        allowed = {"status", "completed_count", "failed_count", "skipped_count", "error_summary"}
        values = {key: value for key, value in state.items() if key in allowed}
        if isinstance(values.get("error_summary"), list):
            values["error_summary"] = json.dumps(values["error_summary"], ensure_ascii=False)
        values["updated_at"] = _now()
        async with self.session_factory() as session:
            await session.execute(batch_imports.update().where(batch_imports.c.id == batch_id).values(**values))
            await session.commit()

    async def save_package_review(
        self,
        result: dict[str, Any],
        *,
        user_id: str,
        project_id: str,
        question: str,
        tenant_id: str | None = None,
    ) -> None:
        now = _now()
        review_id = result["review_id"]
        async with self.session_factory() as session:
            await session.execute(delete(package_review_evidence).where(
                package_review_evidence.c.review_id == review_id
            ))
            values = {
                "tenant_id": tenant_id or settings.DEFAULT_TENANT_ID,
                "user_id": user_id,
                "project_id": project_id,
                "question": question,
                "status": result["status"],
                "engine": result["engine"],
                "report": result.get("report", ""),
                "conflicts": json.dumps(result.get("conflicts", []), ensure_ascii=False),
                "worker_results": json.dumps(result.get("worker_results", {}), ensure_ascii=False),
                "usage": json.dumps(result.get("usage", {}), ensure_ascii=False),
                "human_review_required": int(bool(result.get("human_review_required"))),
                "updated_at": now,
            }
            existing = await session.execute(select(package_reviews.c.id).where(package_reviews.c.id == review_id))
            if existing.first():
                await session.execute(package_reviews.update().where(package_reviews.c.id == review_id).values(
                    **values,
                    lock_version=package_reviews.c.lock_version + 1,
                ))
            else:
                await session.execute(insert(package_reviews).values(
                    id=review_id,
                    **values,
                    lock_version=1,
                    created_at=now,
                ))
            evidence = [
                {
                    "id": f"{review_id}:{index}",
                    "review_id": review_id,
                    "source_id": str(source.get("source_id", index)),
                    "payload": json.dumps(source, ensure_ascii=False),
                }
                for index, source in enumerate(result.get("sources", []))
            ]
            if evidence:
                await session.execute(insert(package_review_evidence), evidence)
            await session.commit()

    async def get_package_review(self, review_id: str) -> dict[str, Any] | None:
        async with self.session_factory() as session:
            review_result = await session.execute(
                select(package_reviews).where(package_reviews.c.id == review_id)
            )
            row = review_result.mappings().first()
            if not row:
                return None
            evidence_result = await session.execute(
                select(package_review_evidence)
                .where(package_review_evidence.c.review_id == review_id)
                .order_by(package_review_evidence.c.id)
            )
            sources = [json.loads(item["payload"]) for item in evidence_result.mappings().all()]
            return {
                "review_id": row["id"],
                "tenant_id": row["tenant_id"],
                "project_id": row["project_id"],
                "user_id": row["user_id"],
                "status": row["status"],
                "engine": row["engine"],
                "report": row["report"],
                "sources": sources,
                "conflicts": json.loads(row["conflicts"]),
                "worker_results": json.loads(row["worker_results"]),
                "usage": json.loads(row["usage"]),
                "human_review_required": bool(row["human_review_required"]),
                "lock_version": row["lock_version"],
                "created_at": row["created_at"].isoformat(),
            }

    async def update_package_review_status(self, review_id: str, status: str) -> bool:
        async with self.session_factory() as session:
            result = await session.execute(
                package_reviews.update()
                .where(and_(
                    package_reviews.c.id == review_id,
                    package_reviews.c.status == "awaiting_approval",
                ))
                .values(
                    status=status,
                    updated_at=_now(),
                    lock_version=package_reviews.c.lock_version + 1,
                )
            )
            await session.commit()
            return bool(result.rowcount)

    async def reserve_budget(
        self,
        project_id: str,
        workflow_id: str,
        requested_tokens: int,
        estimated_cost_micros: int = 0,
    ) -> dict[str, Any]:
        if requested_tokens <= 0:
            raise ValueError("requested_tokens must be positive")
        now = _now()
        async with self.session_factory() as session:
            existing = await session.execute(
                select(budget_reservations).where(budget_reservations.c.workflow_id == workflow_id)
            )
            existing_row = existing.mappings().first()
            if existing_row:
                return dict(existing_row)
            project_result = await session.execute(
                select(projects).where(projects.c.id == project_id).with_for_update()
            )
            project = project_result.mappings().first()
            if not project:
                raise ValueError("project not found")
            today = now.date().isoformat()
            month = now.strftime("%Y-%m")
            used_tokens = int(project["used_tokens"]) if project["token_usage_date"] == today else 0
            used_cost = int(project["used_cost_micros"]) if project["cost_usage_month"] == month else 0
            if project["token_usage_date"] != today or project["cost_usage_month"] != month:
                await session.execute(projects.update().where(projects.c.id == project_id).values(
                    used_tokens=used_tokens,
                    used_cost_micros=used_cost,
                    token_usage_date=today,
                    cost_usage_month=month,
                ))
            active = await session.execute(select(budget_reservations.c.id).where(and_(
                budget_reservations.c.project_id == project_id,
                budget_reservations.c.status == "reserved",
            )))
            if len(active.all()) >= int(project["max_concurrent_reviews"]):
                raise ValueError("project concurrent review quota exceeded")
            available = int(project["daily_token_limit"]) - used_tokens - int(project["reserved_tokens"])
            if requested_tokens > available:
                raise ValueError("project token budget is insufficient")
            available_cost = (
                int(project["monthly_cost_limit_micros"])
                - used_cost
                - int(project["reserved_cost_micros"])
            )
            if estimated_cost_micros > available_cost:
                raise ValueError("project monthly cost budget is insufficient")
            row = {
                "id": uuid.uuid4().hex,
                "project_id": project_id,
                "workflow_id": workflow_id,
                "reserved_tokens": requested_tokens,
                "actual_tokens": 0,
                "estimated_cost_micros": max(0, estimated_cost_micros),
                "actual_cost_micros": 0,
                "status": "reserved",
                "created_at": now,
                "updated_at": now,
            }
            await session.execute(insert(budget_reservations).values(**row))
            await session.execute(projects.update().where(projects.c.id == project_id).values(
                reserved_tokens=projects.c.reserved_tokens + requested_tokens,
                reserved_cost_micros=projects.c.reserved_cost_micros + max(0, estimated_cost_micros),
                lock_version=projects.c.lock_version + 1,
            ))
            await session.commit()
            return row

    async def settle_budget(
        self,
        workflow_id: str,
        actual_tokens: int,
        actual_cost_micros: int = 0,
        *,
        status: str = "settled",
    ) -> bool:
        actual_tokens = max(0, actual_tokens)
        async with self.session_factory() as session:
            result = await session.execute(
                select(budget_reservations).where(
                    budget_reservations.c.workflow_id == workflow_id
                ).with_for_update()
            )
            row = result.mappings().first()
            if not row or row["status"] != "reserved":
                return False
            await session.execute(projects.update().where(projects.c.id == row["project_id"]).values(
                reserved_tokens=projects.c.reserved_tokens - int(row["reserved_tokens"]),
                used_tokens=projects.c.used_tokens + actual_tokens,
                reserved_cost_micros=(
                    projects.c.reserved_cost_micros - int(row["estimated_cost_micros"])
                ),
                used_cost_micros=projects.c.used_cost_micros + max(0, actual_cost_micros),
                lock_version=projects.c.lock_version + 1,
            ))
            await session.execute(budget_reservations.update().where(
                budget_reservations.c.id == row["id"]
            ).values(
                actual_tokens=actual_tokens,
                actual_cost_micros=max(0, actual_cost_micros),
                status=status,
                updated_at=_now(),
            ))
            await session.commit()
            return True

    async def start_agent_run(
        self,
        *,
        tenant_id: str,
        project_id: str,
        user_id: str,
        run_type: str,
        provider: str,
        model: str,
    ) -> str:
        run_id = uuid.uuid4().hex
        now = _now()
        async with self.session_factory() as session:
            await session.execute(insert(agent_runs).values(
                id=run_id,
                tenant_id=tenant_id,
                project_id=project_id,
                user_id=user_id,
                run_type=run_type,
                status="running",
                model=model,
                provider=provider,
                input_tokens=0,
                output_tokens=0,
                latency_ms=0,
                finish_reason="",
                error_type=None,
                created_at=now,
                updated_at=now,
            ))
            await session.commit()
        return run_id

    async def finish_agent_run(
        self,
        run_id: str,
        *,
        status: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        latency_ms: float = 0,
        finish_reason: str = "",
        error_type: str | None = None,
    ) -> None:
        async with self.session_factory() as session:
            await session.execute(agent_runs.update().where(agent_runs.c.id == run_id).values(
                status=status,
                input_tokens=max(0, input_tokens),
                output_tokens=max(0, output_tokens),
                latency_ms=max(0, latency_ms),
                finish_reason=finish_reason[:32],
                error_type=error_type[:128] if error_type else None,
                updated_at=_now(),
            ))
            await session.commit()

    async def add_agent_step(
        self,
        run_id: str,
        step_name: str,
        operation: str,
        status: str,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        latency_ms: float = 0,
        error_type: str | None = None,
    ) -> None:
        async with self.session_factory() as session:
            await session.execute(insert(agent_steps).values(
                id=uuid.uuid4().hex,
                run_id=run_id,
                step_name=step_name[:128],
                operation=operation[:64],
                status=status[:32],
                input_tokens=max(0, input_tokens),
                output_tokens=max(0, output_tokens),
                latency_ms=max(0, latency_ms),
                error_type=error_type[:128] if error_type else None,
                created_at=_now(),
            ))
            await session.commit()


storage = EngineeringStorage()
