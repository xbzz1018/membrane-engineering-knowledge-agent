from __future__ import annotations

import asyncio
import json
import re
import uuid
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    and_,
    case,
    delete,
    func,
    insert,
    or_,
    select,
    update,
)
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from src.core.config import get_settings
from src.domain.document_search import DocumentSearchFilters
from src.infrastructure.document_filters import apply_document_filters
from src.infrastructure.project_plan_tables import define_plan_tables

settings = get_settings()
metadata = MetaData()
project_plans, project_plan_versions, project_plan_reviews, project_plan_decisions, project_plan_artifacts = (
    define_plan_tables(metadata)
)

document_business_metadata = Table(
    "document_business_metadata", metadata,
    Column("document_id", String(64), primary_key=True),
    Column("engineering_model", String(128), nullable=False),
    Column("applicable_revision", String(128), nullable=False),
    Column("document_type", String(16), nullable=False),
    Column("effective_from", Date, nullable=True),
    Column("effective_to", Date, nullable=True),
    Column("source_note", String(1000), nullable=False),
    Column("declared_by", String(64), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Index("ix_doc_business_identity", "engineering_model", "applicable_revision", "document_type"),
    Index("ix_doc_business_effective", "effective_from", "effective_to"),
)

review_manifests = Table(
    "review_manifests", metadata,
    Column("review_id", String(64), primary_key=True),
    Column("tenant_id", String(64), nullable=False),
    Column("project_id", String(128), nullable=False),
    Column("sha256", String(64), nullable=False),
    Column("payload", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

document_ingest_claims = Table(
    "document_ingest_claims", metadata,
    Column("document_id", String(64), primary_key=True),
    Column("execution_id", String(256), nullable=False),
    Column("attempt", Integer, nullable=False),
)

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
    Column("embedding_model", String(128), nullable=False, default=""),
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
    Column("tenant_id", String(64), nullable=False, default="membrane-company", index=True),
    Column("visibility", String(16), nullable=False, default="public"),
    Column("status", String(16), nullable=False, default="active"),
    Column("lock_version", Integer, nullable=False, default=1),
    Column("created_by", String(64), nullable=False, default="seed"),
    Column("created_at", DateTime(timezone=True), nullable=True),
    Column("updated_at", DateTime(timezone=True), nullable=True),
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
    Column("tenant_id", String(64), nullable=False, default="membrane-company", index=True),
    Column("project_id", String(128), nullable=False, default="", index=True),
    Column("visibility", String(16), nullable=False, default="public"),
    Column("status", String(16), nullable=False, default="active"),
    Column("lock_version", Integer, nullable=False, default=1),
    Column("created_by", String(64), nullable=False, default="seed"),
    Column("created_at", DateTime(timezone=True), nullable=True),
    Column("updated_at", DateTime(timezone=True), nullable=True),
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
    Column("review_mode", String(16), nullable=False, default="full"),
    Column("status", String(32), nullable=False),
    Column("engine", String(32), nullable=False),
    Column("report", Text, nullable=False),
    Column("conflicts", Text, nullable=False),
    Column("worker_results", Text, nullable=False, default="{}"),
    Column("issues", Text, nullable=False, default="[]"),
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
    Column("business_id", String(128), nullable=False, default="", index=True),
    Column("run_type", String(32), nullable=False),
    Column("status", String(32), nullable=False),
    Column("model", String(128), nullable=False, default=""),
    Column("provider", String(64), nullable=False, default=""),
    Column("prompt_name", String(64), nullable=False, default=""),
    Column("prompt_version", String(32), nullable=False, default=""),
    Column("prompt_sha256", String(64), nullable=False, default=""),
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

mcp_tool_calls = Table(
    "mcp_tool_calls", metadata,
    Column("id", String(128), primary_key=True),
    Column("tenant_id", String(64), nullable=False, index=True),
    Column("user_id", String(64), nullable=False, index=True),
    Column("client_id", String(128), nullable=False, default=""),
    Column("project_id", String(128), nullable=False, default="", index=True),
    Column("tool_name", String(128), nullable=False),
    Column("status", String(32), nullable=False),
    Column("duration_ms", Float, nullable=False, default=0),
    Column("result_count", Integer, nullable=False, default=0),
    Column("result_ref", String(256), nullable=False, default=""),
    Column("error_type", String(128), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

mcp_idempotency = Table(
    "mcp_idempotency", metadata,
    Column("id", String(128), primary_key=True),
    Column("tenant_id", String(64), nullable=False),
    Column("user_id", String(64), nullable=False),
    Column("tool_name", String(128), nullable=False),
    Column("idempotency_key", String(128), nullable=False),
    Column("request_hash", String(64), nullable=False),
    Column("status", String(32), nullable=False),
    Column("result_ref", String(256), nullable=False, default=""),
    Column("result_payload", Text, nullable=False, default="{}"),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint(
        "tenant_id", "user_id", "tool_name", "idempotency_key",
        name="uq_mcp_idempotency_scope",
    ),
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
            "tenant_id": str(row.get("tenant_id", settings.DEFAULT_TENANT_ID)),
            "visibility": str(row.get("visibility", "public")),
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
            "tenant_id": str(row.get("tenant_id", settings.DEFAULT_TENANT_ID)),
            "project_id": str(row.get("project_id", "")),
            "visibility": str(row.get("visibility", "public")),
        })
    return value


def _catalog_payload(table: Table, row: dict[str, Any]) -> dict[str, Any]:
    payload = json.loads(row["payload"])
    identifier = "spec_id" if table is specs else "price_id"
    payload.update({
        identifier: row["id"],
        "tenant_id": row["tenant_id"],
        "visibility": row["visibility"],
        "status": row["status"],
        "lock_version": int(row["lock_version"]),
        "created_by": row["created_by"],
        "created_at": row["created_at"].isoformat() if row.get("created_at") else "",
        "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else "",
    })
    if table is prices:
        payload["project_id"] = row["project_id"]
        payload["synthetic"] = bool(row["synthetic"])
        payload["disclaimer"] = payload.get("disclaimer") or "历史参考数据，不构成正式报价。"
    return payload


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
        self._local_budget_locks: dict[str, asyncio.Lock] = {}

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
                levels = {"public": 0, "internal": 1, "restricted": 2}
                current_level = levels.get(str(existing_row["data_classification"]), 0)
                requested_level = levels.get(data_classification, 0)
                if requested_level > current_level:
                    await session.execute(
                        documents.update()
                        .where(documents.c.id == existing_row["id"])
                        .values(
                            data_classification=data_classification,
                            updated_at=_now(),
                            lock_version=documents.c.lock_version + 1,
                        )
                    )
                    await session.commit()
                    existing_row = {**dict(existing_row), "data_classification": data_classification}
                return dict(existing_row)
        if settings.RUNTIME_MODE.lower() == "full":
            from src.infrastructure.full_backends import get_full_backends

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

    async def acquire_document_ingest(
        self, document_id: str, *, refresh_embedding: bool = False,
        claim: tuple[str, int] | None = None,
    ) -> bool:
        if claim is not None:
            from src.infrastructure.ingest_claim import acquire_claim

            return await acquire_claim(self, document_id, claim, refresh_embedding=refresh_embedding)
        async with self.session_factory() as session:
            statuses = ["uploaded", "failed", "index_failed"]
            condition = documents.c.status.in_(statuses)
            if refresh_embedding:
                condition = condition | (documents.c.status == "indexed")
            result = await session.execute(
                documents.update()
                .where(and_(documents.c.id == document_id, condition))
                .values(status="indexing", error_type=None, updated_at=_now(), lock_version=documents.c.lock_version + 1)
            )
            await session.commit()
            return bool(result.rowcount)

    async def fail_document(
        self, document_id: str, error_type: str, *, claim: tuple[str, int] | None = None,
    ) -> None:
        async with self.session_factory() as session:
            if claim is not None:
                from src.infrastructure.ingest_claim import guard_claim

                await guard_claim(session, document_id, claim)
            await session.execute(
                documents.update().where(documents.c.id == document_id).values(
                    status="failed", error_type=error_type[:128], updated_at=_now(),
                )
            )
            await session.commit()

    async def resolve_document_path(self, row: dict[str, Any]) -> Path:
        if settings.RUNTIME_MODE.lower() == "full":
            from src.infrastructure.full_backends import get_full_backends

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

    async def save_chunks(
        self, document_id: str, chunks: list[dict[str, Any]], parser: str,
        *, claim: tuple[str, int] | None = None,
    ) -> int:
        if not chunks or not any(str(item.get("text", "")).strip() for item in chunks):
            raise ValueError("cannot index a document without evidence chunks")
        if settings.RUNTIME_MODE.lower() == "full":
            document = await self.get_document(document_id)
            if document is None:
                raise RuntimeError(f"Document disappeared before indexing: {document_id}")
            from src.infrastructure.full_backends import get_full_backends

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
            if claim is not None:
                from src.infrastructure.ingest_claim import guard_claim

                await guard_claim(session, document_id, claim)
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
            from src.infrastructure.full_backends import get_full_backends

            document = await self.get_document(document_id)
            if document is None:
                raise RuntimeError(f"Document disappeared after indexing: {document_id}")
            try:
                if claim is not None:
                    document = {**document, "_ingest_claim": claim}
                await get_full_backends().index_document(document, chunks)
            except Exception as exc:
                async with self.session_factory() as session:
                    if claim is not None:
                        from src.infrastructure.ingest_claim import guard_claim

                        await guard_claim(session, document_id, claim)
                    await session.execute(documents.update().where(documents.c.id == document_id).values(
                        status="index_failed", error_type=type(exc).__name__, updated_at=_now(),
                    ))
                    await session.commit()
                raise
        async with self.session_factory() as session:
            if claim is not None:
                from src.infrastructure.ingest_claim import guard_claim

                await guard_claim(session, document_id, claim)
            embedding_model = ""
            if settings.RUNTIME_MODE.lower() == "full":
                from src.documents.representations import document_index_model
                from src.infrastructure.model_provider import get_model_provider

                embedding_model = document_index_model(get_model_provider(), settings)
            await session.execute(documents.update().where(documents.c.id == document_id).values(
                status="indexed", embedding_model=embedding_model, error_type=None, updated_at=_now(),
            ))
            await session.commit()
        return len(values)

    async def search_chunks(
        self,
        query: str,
        limit: int = 30,
        project_id: str = "",
        *,
        tenant_id: str = "",
        classifications: set[str] | None = None,
        filters: DocumentSearchFilters | None = None,
        lexical_only: bool = False,
    ) -> list[dict[str, Any]]:
        filters = filters or DocumentSearchFilters()
        async with self.session_factory() as session:
            statement = select(
                document_chunks,
                documents.c.filename,
                documents.c.version,
                documents.c.created_at,
            ).select_from(document_chunks.join(documents, document_chunks.c.document_id == documents.c.id))
            statement = statement.where(documents.c.status == "indexed")
            if project_id:
                statement = statement.where(documents.c.project_id == project_id)
            if tenant_id:
                statement = statement.where(documents.c.tenant_id == tenant_id)
            if classifications:
                statement = statement.where(documents.c.data_classification.in_(sorted(classifications)))
            statement = apply_document_filters(statement, documents, document_business_metadata, filters)
            # Parameterized substring scoring in SQL. This is deliberately not called BM25.
            # Keep candidate rows and their sort in the database, rather than loading
            # every authorized chunk into Python memory.
            terms = list(dict.fromkeys(re.findall(r"[\w-]+", query.lower())))[:32]
            lexical_score = sum((
                case((func.lower(documents.c.filename).contains(term, autoescape=True), 4), else_=0)
                + case((func.lower(document_chunks.c.text).contains(term, autoescape=True), 1), else_=0)
                for term in terms
            ), 0)
            if settings.CONTEXTUAL_RETRIEVAL_ENABLED:
                lexical_score += sum((
                    case((func.lower(document_chunks.c.heading_path).contains(term, autoescape=True), 2), else_=0)
                    + case((func.lower(document_chunks.c.sheet_name).contains(term, autoescape=True), 2), else_=0)
                    + case((func.lower(document_chunks.c.location).contains(term, autoescape=True), 1), else_=0)
                    for term in terms
                ), 0)
            if terms:
                statement = statement.add_columns(lexical_score.label("raw_score")).where(lexical_score > 0)
                statement = statement.order_by(lexical_score.desc(), document_chunks.c.id)
            elif filters.model_dump(exclude_none=True):
                statement = statement.order_by(document_chunks.c.id)
            else:
                return []
            result = await session.execute(statement.limit(limit))
            rows = [dict(row) for row in result.mappings().all()]
        lexical = rows
        for rank, row in enumerate(lexical, 1):
            row.setdefault("raw_score", 0)
            row["retrieval"] = [{
                "backend": "postgresql" if settings.RUNTIME_MODE.lower() == "full" else "sqlite",
                "rank": rank,
                "score": row["raw_score"],
            }]
        if settings.RUNTIME_MODE.lower() != "full" or not query.strip() or lexical_only:
            return lexical
        from src.infrastructure.full_backends import get_full_backends

        vector = await get_full_backends().search_documents(
            query,
            limit=limit,
            project_id=project_id,
            tenant_id=tenant_id,
            classifications=classifications,
            filters=filters,
        ) if query.strip() else []
        return _fuse_ranked(
            [("postgresql", 1.0, lexical), ("pgvector", 1.3, vector)],
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
        conditions: list[Any] | None = None,
    ) -> list[dict[str, Any]]:
        async with self.session_factory() as session:
            statement = select(table)
            if conditions:
                statement = statement.where(and_(*conditions))
            result = await session.execute(statement)
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

    async def search_specs(
        self,
        query: str,
        limit: int = 8,
        *,
        tenant_id: str = "",
        visibility: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        conditions = [specs.c.status == "active"]
        if tenant_id:
            conditions.append(specs.c.tenant_id == tenant_id)
        if visibility:
            conditions.append(specs.c.visibility.in_(sorted(visibility)))
        return await self._search_payload_table(specs, query, limit, {
            "product_reference": 8, "material": 6, "manufacturer": 5, "specification": 4,
            "source_version": 5,
        }, conditions)

    async def search_prices(
        self,
        query: str,
        limit: int = 8,
        *,
        tenant_id: str = "",
        project_id: str = "",
        visibility: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        conditions = [prices.c.status == "active"]
        if tenant_id:
            conditions.append(prices.c.tenant_id == tenant_id)
        if project_id:
            conditions.append(or_(prices.c.project_id == "", prices.c.project_id == project_id))
        if visibility:
            conditions.append(prices.c.visibility.in_(sorted(visibility)))
        return await self._search_payload_table(prices, query, limit, {
            "material": 6, "specification": 5, "effective_date": 7, "region": 4, "currency": 5, "unit": 5,
        }, conditions)

    async def list_material_specs(
        self,
        *,
        tenant_id: str,
        query: str = "",
        status: str = "active",
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        conditions = [specs.c.tenant_id == tenant_id]
        if status:
            conditions.append(specs.c.status == status)
        if query:
            conditions.append(specs.c.search_text.ilike(f"%{query}%"))
        async with self.session_factory() as session:
            total = await session.scalar(select(func.count()).select_from(specs).where(and_(*conditions)))
            result = await session.execute(
                select(specs)
                .where(and_(*conditions))
                .order_by(specs.c.manufacturer, specs.c.product_reference, specs.c.id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            items = [_catalog_payload(specs, dict(row)) for row in result.mappings().all()]
        return {"items": items, "total": int(total or 0), "page": page, "page_size": page_size}

    async def get_material_spec(self, spec_id: str, tenant_id: str) -> dict[str, Any] | None:
        async with self.session_factory() as session:
            result = await session.execute(select(specs).where(and_(
                specs.c.id == spec_id,
                specs.c.tenant_id == tenant_id,
            )))
            row = result.mappings().first()
            return _catalog_payload(specs, dict(row)) if row else None

    async def create_material_spec(
        self, spec_id: str, payload: dict[str, Any], *, tenant_id: str, user_id: str,
    ) -> dict[str, Any]:
        now = _now()
        row = {**payload, "spec_id": spec_id, "tenant_id": tenant_id}
        values = {
            "id": spec_id,
            "payload": json.dumps(row, ensure_ascii=False),
            **_normalized_payload_values(specs, row),
            "status": "active",
            "lock_version": 1,
            "created_by": user_id,
            "created_at": now,
            "updated_at": now,
        }
        async with self.session_factory() as session:
            if (await session.execute(select(specs.c.id).where(specs.c.id == spec_id))).first():
                raise ValueError("膜材规格ID已存在")
            await session.execute(insert(specs).values(**values))
            await session.commit()
        created = await self.get_material_spec(spec_id, tenant_id)
        if created is None:  # pragma: no cover
            raise RuntimeError("膜材规格创建后不可见")
        return created

    async def update_material_spec(
        self,
        spec_id: str,
        patch: dict[str, Any],
        *,
        tenant_id: str,
        expected_lock_version: int,
    ) -> dict[str, Any] | None:
        current = await self.get_material_spec(spec_id, tenant_id)
        if current is None:
            return None
        if int(current["lock_version"]) != expected_lock_version:
            raise ValueError("膜材规格已被其他用户更新")
        merged = {**current, **patch, "spec_id": spec_id, "tenant_id": tenant_id}
        values = {
            "payload": json.dumps(merged, ensure_ascii=False),
            **_normalized_payload_values(specs, merged),
            "status": str(merged.get("status", "active")),
            "updated_at": _now(),
            "lock_version": specs.c.lock_version + 1,
        }
        async with self.session_factory() as session:
            result = await session.execute(specs.update().where(and_(
                specs.c.id == spec_id,
                specs.c.tenant_id == tenant_id,
                specs.c.lock_version == expected_lock_version,
            )).values(**values))
            await session.commit()
            if not result.rowcount:
                raise ValueError("膜材规格已被其他用户更新")
        return await self.get_material_spec(spec_id, tenant_id)

    async def archive_material_spec(
        self, spec_id: str, *, tenant_id: str, expected_lock_version: int,
    ) -> dict[str, Any] | None:
        return await self.update_material_spec(
            spec_id, {"status": "archived"}, tenant_id=tenant_id,
            expected_lock_version=expected_lock_version,
        )

    async def list_price_records(
        self,
        *,
        tenant_id: str,
        project_id: str,
        query: str = "",
        status: str = "active",
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        conditions = [
            prices.c.tenant_id == tenant_id,
            or_(prices.c.project_id == "", prices.c.project_id == project_id),
        ]
        if status:
            conditions.append(prices.c.status == status)
        if query:
            conditions.append(prices.c.search_text.ilike(f"%{query}%"))
        async with self.session_factory() as session:
            total = await session.scalar(select(func.count()).select_from(prices).where(and_(*conditions)))
            result = await session.execute(
                select(prices)
                .where(and_(*conditions))
                .order_by(prices.c.effective_date.desc(), prices.c.material, prices.c.id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            items = [_catalog_payload(prices, dict(row)) for row in result.mappings().all()]
        return {"items": items, "total": int(total or 0), "page": page, "page_size": page_size}

    async def get_price_record(
        self, price_id: str, *, tenant_id: str, project_id: str,
    ) -> dict[str, Any] | None:
        async with self.session_factory() as session:
            result = await session.execute(select(prices).where(and_(
                prices.c.id == price_id,
                prices.c.tenant_id == tenant_id,
                or_(prices.c.project_id == "", prices.c.project_id == project_id),
            )))
            row = result.mappings().first()
            return _catalog_payload(prices, dict(row)) if row else None

    async def create_price_record(
        self, price_id: str, payload: dict[str, Any], *, tenant_id: str, user_id: str,
    ) -> dict[str, Any]:
        now = _now()
        row = {**payload, "price_id": price_id, "tenant_id": tenant_id}
        values = {
            "id": price_id,
            "payload": json.dumps(row, ensure_ascii=False),
            **_normalized_payload_values(prices, row),
            "status": "active",
            "lock_version": 1,
            "created_by": user_id,
            "created_at": now,
            "updated_at": now,
        }
        async with self.session_factory() as session:
            if (await session.execute(select(prices.c.id).where(prices.c.id == price_id))).first():
                raise ValueError("历史价格ID已存在")
            await session.execute(insert(prices).values(**values))
            await session.commit()
        created = await self.get_price_record(
            price_id, tenant_id=tenant_id, project_id=str(row.get("project_id", "")),
        )
        if created is None:  # pragma: no cover
            raise RuntimeError("历史价格创建后不可见")
        return created

    async def update_price_record(
        self,
        price_id: str,
        patch: dict[str, Any],
        *,
        tenant_id: str,
        project_id: str,
        expected_lock_version: int,
    ) -> dict[str, Any] | None:
        current = await self.get_price_record(price_id, tenant_id=tenant_id, project_id=project_id)
        if current is None:
            return None
        if int(current["lock_version"]) != expected_lock_version:
            raise ValueError("历史价格已被其他用户更新")
        merged = {**current, **patch, "price_id": price_id, "tenant_id": tenant_id}
        values = {
            "payload": json.dumps(merged, ensure_ascii=False),
            **_normalized_payload_values(prices, merged),
            "status": str(merged.get("status", "active")),
            "updated_at": _now(),
            "lock_version": prices.c.lock_version + 1,
        }
        async with self.session_factory() as session:
            result = await session.execute(prices.update().where(and_(
                prices.c.id == price_id,
                prices.c.tenant_id == tenant_id,
                prices.c.lock_version == expected_lock_version,
            )).values(**values))
            await session.commit()
            if not result.rowcount:
                raise ValueError("历史价格已被其他用户更新")
        return await self.get_price_record(
            price_id, tenant_id=tenant_id, project_id=str(merged.get("project_id", "")),
        )

    async def archive_price_record(
        self,
        price_id: str,
        *,
        tenant_id: str,
        project_id: str,
        expected_lock_version: int,
    ) -> dict[str, Any] | None:
        return await self.update_price_record(
            price_id, {"status": "archived"}, tenant_id=tenant_id, project_id=project_id,
            expected_lock_version=expected_lock_version,
        )

    async def seed_payloads(
        self,
        table: Table,
        rows: list[dict[str, Any]],
        key: str,
        *,
        update_existing: bool = False,
    ) -> int:
        if not rows:
            return 0
        async with self.session_factory() as session:
            existing = await session.execute(select(table.c.id))
            existing_ids = {row[0] for row in existing.all()}
            values = []
            updated = 0
            for row in rows:
                row_id = str(row.get(key) or "")
                if not row_id:
                    continue
                value: dict[str, Any] = {
                    "id": row_id,
                    "payload": json.dumps(row, ensure_ascii=False),
                    **_normalized_payload_values(table, row),
                }
                if row_id in existing_ids:
                    # A failed remote detail fetch must not erase a previously enriched row.
                    if update_existing and row.get("detail_status") != "failed":
                        await session.execute(
                            update(table).where(table.c.id == row_id).values(**value)
                        )
                        updated += 1
                    continue
                values.append(value)
            if values:
                await session.execute(insert(table), values)
                await session.commit()
            elif updated:
                await session.commit()
            return len(values) + updated

    async def append_message(self, user_id: str, session_id: str, role: str, content: str) -> None:
        async with self.session_factory() as session:
            await session.execute(insert(conversations).values(
                id=uuid.uuid4().hex, user_id=user_id, session_id=session_id,
                role=role, content=content[:8000], created_at=_now(),
            ))
            await session.commit()

    async def conversation_messages(self, user_id: str, scoped_session_id: str, limit: int = 6) -> list[dict]:
        """Caller derives session hash from tenant/user/project/session after authorization."""
        async with self.session_factory() as session:
            rows = (await session.execute(
                select(conversations.c.role, conversations.c.content)
                .where(conversations.c.user_id == user_id, conversations.c.session_id == scoped_session_id)
                .order_by(conversations.c.created_at.desc(), conversations.c.id.desc())
                .limit(max(1, min(limit, 12)))
            )).mappings().all()
            return [dict(row) for row in reversed(rows)]

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
            from src.infrastructure.full_backends import get_full_backends

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
            from src.infrastructure.full_backends import get_full_backends

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
            from src.infrastructure.full_backends import get_full_backends

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
            from src.infrastructure.full_backends import get_full_backends

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

    async def list_batch_imports(
        self,
        *,
        tenant_id: str,
        project_id: str,
        status: str = "",
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        conditions = [
            batch_imports.c.tenant_id == tenant_id,
            batch_imports.c.project_id == project_id,
        ]
        if status:
            conditions.append(batch_imports.c.status == status)
        async with self.session_factory() as session:
            total = await session.scalar(
                select(func.count()).select_from(batch_imports).where(and_(*conditions))
            )
            result = await session.execute(
                select(batch_imports)
                .where(and_(*conditions))
                .order_by(batch_imports.c.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            items = []
            for item in result.mappings().all():
                row = dict(item)
                row["batch_id"] = row.pop("id")
                row["error_summary"] = json.loads(row.get("error_summary") or "[]")
                items.append(row)
        return {"items": items, "total": int(total or 0), "page": page, "page_size": page_size}

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
        review_mode: str = "full",
        tenant_id: str | None = None,
    ) -> None:
        from src.infrastructure.review_lifecycle import publish_review_once

        await publish_review_once(
            self, result, user_id=user_id, project_id=project_id, question=question,
            review_mode=review_mode, tenant_id=tenant_id,
        )

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
                "review_mode": row["review_mode"],
                "status": row["status"],
                "engine": row["engine"],
                "report": row["report"],
                "sources": sources,
                "conflicts": json.loads(row["conflicts"]),
                "worker_results": json.loads(row["worker_results"]),
                "issues": json.loads(row["issues"] or "[]"),
                "agents_used": [
                    "ReviewSupervisorAgent",
                    *[
                        f"{worker.title()}ReviewAgent"
                        for worker in json.loads(row["worker_results"]).keys()
                        if worker in {"design", "material", "price"}
                    ],
                ],
                "orchestrator": "ReviewSupervisorAgent",
                "review_plan": json.loads(row["usage"]).get("supervisor", {}),
                "usage": json.loads(row["usage"]),
                "human_review_required": bool(row["human_review_required"]),
                "lock_version": row["lock_version"],
                "created_at": row["created_at"].isoformat(),
            }

    async def update_package_review_status(self, review_id: str, status: str) -> bool:
        # Approval must pass the transactional human gate, never a bare status update.
        if status in {"approved", "rejected"}:
            review = await self.get_package_review(review_id)
            return bool(review and review["status"] == status)
        from src.infrastructure.review_lifecycle import set_review_terminal

        return await set_review_terminal(self, review_id, status)

    async def update_review_issue_status(
        self,
        review_id: str,
        issue_id: str,
        status: str,
        expected_lock_version: int,
    ) -> tuple[dict[str, Any], int] | None:
        """Update one issue under the review's optimistic lock."""
        async with self.session_factory() as session:
            result = await session.execute(
                select(package_reviews)
                .where(package_reviews.c.id == review_id)
                .with_for_update()
            )
            row = result.mappings().first()
            if not row:
                return None
            if int(row["lock_version"]) != expected_lock_version:
                raise ValueError("review lock version mismatch")
            issues = json.loads(row["issues"] or "[]")
            issue = next((item for item in issues if item.get("issue_id") == issue_id), None)
            if issue is None:
                raise LookupError("review issue not found")
            issue["status"] = status
            if status == "pending_human":
                issue["requires_human"] = True
            updated = await session.execute(
                package_reviews.update()
                .where(and_(
                    package_reviews.c.id == review_id,
                    package_reviews.c.lock_version == expected_lock_version,
                ))
                .values(
                    issues=json.dumps(issues, ensure_ascii=False),
                    lock_version=package_reviews.c.lock_version + 1,
                    updated_at=_now(),
                )
            )
            if not updated.rowcount:
                raise ValueError("review lock version mismatch")
            await session.commit()
            return issue, expected_lock_version + 1

    async def reserve_budget(
        self,
        project_id: str,
        workflow_id: str,
        requested_tokens: int,
        estimated_cost_micros: int = 0,
    ) -> dict[str, Any]:
        if settings.RUNTIME_MODE.lower() == "local":
            lock = self._local_budget_locks.setdefault(project_id, asyncio.Lock())
            async with lock:
                return await self._reserve_budget(
                    project_id,
                    workflow_id,
                    requested_tokens,
                    estimated_cost_micros,
                )
        return await self._reserve_budget(
            project_id,
            workflow_id,
            requested_tokens,
            estimated_cost_micros,
        )

    async def _reserve_budget(
        self,
        project_id: str,
        workflow_id: str,
        requested_tokens: int,
        estimated_cost_micros: int,
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
        business_id: str = "",
        prompt_name: str = "",
        prompt_version: str = "",
        prompt_sha256: str = "",
    ) -> str:
        run_id = uuid.uuid4().hex
        now = _now()
        async with self.session_factory() as session:
            await session.execute(insert(agent_runs).values(
                id=run_id,
                tenant_id=tenant_id,
                project_id=project_id,
                user_id=user_id,
                business_id=business_id,
                run_type=run_type,
                status="running",
                model=model,
                provider=provider,
                prompt_name=prompt_name,
                prompt_version=prompt_version,
                prompt_sha256=prompt_sha256,
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

    async def list_users(self, tenant_id: str) -> list[dict[str, Any]]:
        async with self.session_factory() as session:
            result = await session.execute(
                select(
                    users.c.id,
                    users.c.username,
                    users.c.role,
                    users.c.is_active,
                    users.c.created_at,
                )
                .where(users.c.tenant_id == tenant_id)
                .order_by(users.c.created_at.desc())
            )
            return [dict(row) for row in result.mappings().all()]

    async def get_project(self, project_id: str, tenant_id: str) -> dict[str, Any] | None:
        async with self.session_factory() as session:
            result = await session.execute(select(projects).where(and_(
                projects.c.id == project_id,
                projects.c.tenant_id == tenant_id,
            )))
            row = result.mappings().first()
            return dict(row) if row else None

    async def list_project_members(self, project_id: str) -> list[dict[str, Any]]:
        async with self.session_factory() as session:
            result = await session.execute(
                select(
                    project_members.c.user_id,
                    users.c.username,
                    users.c.role.label("global_role"),
                    project_members.c.role.label("project_role"),
                    users.c.is_active,
                    project_members.c.created_at,
                )
                .select_from(project_members.join(users, project_members.c.user_id == users.c.id))
                .where(project_members.c.project_id == project_id)
                .order_by(project_members.c.created_at)
            )
            return [dict(row) for row in result.mappings().all()]

    async def get_project_budget(self, project_id: str, tenant_id: str) -> dict[str, Any] | None:
        project = await self.get_project(project_id, tenant_id)
        if not project:
            return None
        async with self.session_factory() as session:
            result = await session.execute(
                select(budget_reservations)
                .where(budget_reservations.c.project_id == project_id)
                .order_by(budget_reservations.c.created_at.desc())
                .limit(20)
            )
            reservations = [dict(row) for row in result.mappings().all()]
        return {
            "project_id": project_id,
            "daily_token_limit": project["daily_token_limit"],
            "used_tokens": project["used_tokens"],
            "reserved_tokens": project["reserved_tokens"],
            "token_usage_date": project["token_usage_date"],
            "monthly_cost_limit_micros": project["monthly_cost_limit_micros"],
            "used_cost_micros": project["used_cost_micros"],
            "reserved_cost_micros": project["reserved_cost_micros"],
            "cost_usage_month": project["cost_usage_month"],
            "max_concurrent_reviews": project["max_concurrent_reviews"],
            "lock_version": project["lock_version"],
            "recent_reservations": reservations,
        }

    async def update_project_budget(
        self,
        project_id: str,
        tenant_id: str,
        *,
        daily_token_limit: int,
        monthly_cost_limit_micros: int,
        max_concurrent_reviews: int,
        expected_lock_version: int,
    ) -> dict[str, Any] | None:
        async with self.session_factory() as session:
            selected = await session.execute(select(projects).where(and_(
                projects.c.id == project_id,
                projects.c.tenant_id == tenant_id,
            )))
            current = selected.mappings().first()
            if current is None:
                return None
            if int(current["lock_version"]) != expected_lock_version:
                raise ValueError("项目预算已被其他管理员更新")
            minimum_tokens = int(current["used_tokens"]) + int(current["reserved_tokens"])
            minimum_cost = int(current["used_cost_micros"]) + int(current["reserved_cost_micros"])
            if daily_token_limit < minimum_tokens:
                raise ValueError("每日Token上限不能低于当前已用和已预留额度")
            if monthly_cost_limit_micros < minimum_cost:
                raise ValueError("月度成本上限不能低于当前已用和已预留额度")
            result = await session.execute(projects.update().where(and_(
                projects.c.id == project_id,
                projects.c.tenant_id == tenant_id,
                projects.c.lock_version == expected_lock_version,
            )).values(
                daily_token_limit=daily_token_limit,
                monthly_cost_limit_micros=monthly_cost_limit_micros,
                max_concurrent_reviews=max_concurrent_reviews,
                lock_version=projects.c.lock_version + 1,
            ))
            await session.commit()
            if not result.rowcount:
                raise ValueError("项目预算已被其他管理员更新")
        return await self.get_project_budget(project_id, tenant_id)

    async def project_dashboard(self, project_id: str, tenant_id: str) -> dict[str, Any] | None:
        project = await self.get_project(project_id, tenant_id)
        if project is None:
            return None
        async with self.session_factory() as session:
            document_rows = await session.execute(
                select(documents.c.status, func.count())
                .where(and_(documents.c.project_id == project_id, documents.c.tenant_id == tenant_id))
                .group_by(documents.c.status)
            )
            review_rows = await session.execute(select(package_reviews).where(and_(
                package_reviews.c.project_id == project_id,
                package_reviews.c.tenant_id == tenant_id,
            )).order_by(package_reviews.c.created_at.desc()).limit(50))
            recent_batches = await session.execute(select(batch_imports).where(and_(
                batch_imports.c.project_id == project_id,
                batch_imports.c.tenant_id == tenant_id,
            )).order_by(batch_imports.c.created_at.desc()).limit(5))
        document_counts = [(str(row[0]), int(row[1])) for row in document_rows.all()]
        reviews = [dict(row) for row in review_rows.mappings().all()]
        review_statuses: dict[str, int] = {}
        issue_severity = {"info": 0, "warning": 0, "conflict": 0}
        open_issues = 0
        for review in reviews:
            status = str(review["status"])
            review_statuses[status] = review_statuses.get(status, 0) + 1
            for issue in json.loads(review.get("issues") or "[]"):
                if issue.get("status") in {"open", "pending_human"}:
                    open_issues += 1
                    severity = str(issue.get("severity", "info"))
                    issue_severity[severity] = issue_severity.get(severity, 0) + 1
        batches = []
        for item in recent_batches.mappings().all():
            row = dict(item)
            row["batch_id"] = row.pop("id")
            row["error_summary"] = json.loads(row.get("error_summary") or "[]")
            batches.append(row)
        return {
            "project": {
                "id": project["id"],
                "name": project["name"],
                "status": project["status"],
                "lock_version": project["lock_version"],
            },
            "documents": {
                "total": sum(count for _, count in document_counts),
                "by_status": dict(document_counts),
            },
            "reviews": {"total": len(reviews), "by_status": review_statuses},
            "issues": {"open": open_issues, "by_severity": issue_severity},
            "recent_reviews": [
                {
                    "review_id": row["id"],
                    "question": row["question"],
                    "status": row["status"],
                    "review_mode": row["review_mode"],
                    "created_at": row["created_at"].isoformat(),
                }
                for row in reviews[:5]
            ],
            "recent_batches": batches,
            "budget": await self.get_project_budget(project_id, tenant_id),
        }

    async def list_package_reviews(
        self,
        *,
        tenant_id: str,
        project_id: str,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        conditions = [
            package_reviews.c.tenant_id == tenant_id,
            package_reviews.c.project_id == project_id,
        ]
        if status:
            conditions.append(package_reviews.c.status == status)
        async with self.session_factory() as session:
            result = await session.execute(
                select(package_reviews)
                .where(and_(*conditions))
                .order_by(package_reviews.c.created_at.desc())
                .limit(limit)
            )
            rows = []
            for item in result.mappings().all():
                row = dict(item)
                rows.append({
                    "review_id": row["id"],
                    "project_id": row["project_id"],
                    "user_id": row["user_id"],
                    "status": row["status"],
                    "engine": row["engine"],
                    "question": row["question"],
                    "conflict_count": len(json.loads(row["conflicts"])),
                    "issue_count": len(json.loads(row["issues"] or "[]")),
                    "human_review_required": bool(row["human_review_required"]),
                    "lock_version": row["lock_version"],
                    "created_at": row["created_at"].isoformat(),
                    "updated_at": row["updated_at"].isoformat(),
                })
            return rows

    async def list_agent_runs(
        self,
        *,
        tenant_id: str,
        project_id: str,
        business_id: str = "",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        conditions = [
            agent_runs.c.tenant_id == tenant_id,
            agent_runs.c.project_id == project_id,
        ]
        if business_id:
            conditions.append(agent_runs.c.business_id == business_id)
        async with self.session_factory() as session:
            result = await session.execute(
                select(agent_runs)
                .where(and_(*conditions))
                .order_by(agent_runs.c.created_at.desc())
                .limit(limit)
            )
            return [dict(row) for row in result.mappings().all()]

    async def get_agent_run(self, run_id: str, tenant_id: str) -> dict[str, Any] | None:
        async with self.session_factory() as session:
            result = await session.execute(select(agent_runs).where(and_(
                agent_runs.c.id == run_id,
                agent_runs.c.tenant_id == tenant_id,
            )))
            row = result.mappings().first()
            if not row:
                return None
            steps = await session.execute(
                select(agent_steps)
                .where(agent_steps.c.run_id == run_id)
                .order_by(agent_steps.c.created_at)
            )
            return {**dict(row), "steps": [dict(item) for item in steps.mappings().all()]}

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

    async def start_mcp_tool_call(
        self,
        *,
        tenant_id: str,
        user_id: str,
        client_id: str,
        project_id: str,
        tool_name: str,
    ) -> str:
        call_id = uuid.uuid4().hex
        now = _now()
        async with self.session_factory() as session:
            await session.execute(insert(mcp_tool_calls).values(
                id=call_id,
                tenant_id=tenant_id,
                user_id=user_id,
                client_id=client_id[:128],
                project_id=project_id[:128],
                tool_name=tool_name[:128],
                status="running",
                duration_ms=0,
                result_count=0,
                result_ref="",
                error_type=None,
                created_at=now,
                updated_at=now,
            ))
            await session.commit()
        return call_id

    async def finish_mcp_tool_call(
        self,
        call_id: str,
        *,
        status: str,
        duration_ms: float,
        result_count: int = 0,
        result_ref: str = "",
        error_type: str | None = None,
    ) -> None:
        async with self.session_factory() as session:
            await session.execute(mcp_tool_calls.update().where(mcp_tool_calls.c.id == call_id).values(
                status=status[:32],
                duration_ms=max(0, duration_ms),
                result_count=max(0, result_count),
                result_ref=result_ref[:256],
                error_type=error_type[:128] if error_type else None,
                updated_at=_now(),
            ))
            await session.commit()

    async def get_mcp_idempotency(
        self,
        *,
        tenant_id: str,
        user_id: str,
        tool_name: str,
        idempotency_key: str,
    ) -> dict[str, Any] | None:
        async with self.session_factory() as session:
            result = await session.execute(select(mcp_idempotency).where(and_(
                mcp_idempotency.c.tenant_id == tenant_id,
                mcp_idempotency.c.user_id == user_id,
                mcp_idempotency.c.tool_name == tool_name,
                mcp_idempotency.c.idempotency_key == idempotency_key,
            )))
            row = result.mappings().first()
            if not row:
                return None
            payload = dict(row)
            payload["result_payload"] = json.loads(payload["result_payload"] or "{}")
            return payload

    async def save_mcp_idempotency(
        self,
        *,
        tenant_id: str,
        user_id: str,
        tool_name: str,
        idempotency_key: str,
        request_hash: str,
        status: str,
        result_ref: str,
        result_payload: dict[str, Any],
    ) -> None:
        now = _now()
        async with self.session_factory() as session:
            existing = await session.execute(select(mcp_idempotency.c.id).where(and_(
                mcp_idempotency.c.tenant_id == tenant_id,
                mcp_idempotency.c.user_id == user_id,
                mcp_idempotency.c.tool_name == tool_name,
                mcp_idempotency.c.idempotency_key == idempotency_key,
            )))
            values = {
                "request_hash": request_hash,
                "status": status,
                "result_ref": result_ref[:256],
                "result_payload": json.dumps(result_payload, ensure_ascii=False),
                "updated_at": now,
            }
            row_id = existing.scalar_one_or_none()
            if row_id:
                await session.execute(mcp_idempotency.update().where(mcp_idempotency.c.id == row_id).values(**values))
            else:
                await session.execute(insert(mcp_idempotency).values(
                    id=uuid.uuid4().hex,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    tool_name=tool_name,
                    idempotency_key=idempotency_key,
                    created_at=now,
                    **values,
                ))
            await session.commit()


storage = EngineeringStorage()
