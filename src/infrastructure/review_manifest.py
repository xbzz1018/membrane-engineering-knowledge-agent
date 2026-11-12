"""Freeze authorized Evidence once; each retry reads the same body and provenance."""

import hashlib
import json
from datetime import UTC, datetime

from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError

from src.infrastructure.database import review_manifests


def encode_manifest(documents, evidence, sources) -> tuple[str, str]:
    payload = json.dumps({
        "format_version": 1,
        "documents": [{key: row.get(key, "") for key in (
            "id", "filename", "version", "sha256", "parser", "parser_version", "data_classification",
        )} for row in documents],
        "evidence": evidence, "sources": sources,
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return payload, hashlib.sha256(payload.encode()).hexdigest()


async def freeze_review_manifest(store, review_id, tenant_id, project_id, documents, evidence, sources) -> str:
    payload, digest = encode_manifest(documents, evidence, sources)
    async with store.session_factory() as session:
        existing = (await session.execute(select(review_manifests).where(
            review_manifests.c.review_id == review_id,
        ))).mappings().first()
        if existing:
            if existing["tenant_id"] != tenant_id or existing["project_id"] != project_id or existing["sha256"] != digest:
                raise ValueError("审查ID已绑定不同证据快照")
            return digest
        try:
            await session.execute(insert(review_manifests).values(
                review_id=review_id, tenant_id=tenant_id, project_id=project_id,
                payload=payload, sha256=digest, created_at=datetime.now(UTC),
            ))
            await session.commit()
        except IntegrityError:
            await session.rollback()
            # Retry must establish that the winner stored exactly this snapshot.
            return await freeze_review_manifest(store, review_id, tenant_id, project_id, documents, evidence, sources)
    return digest


async def read_review_manifest(store, review_id, tenant_id, project_id):
    async with store.session_factory() as session:
        row = (await session.execute(select(review_manifests).where(
            review_manifests.c.review_id == review_id,
            review_manifests.c.tenant_id == tenant_id,
            review_manifests.c.project_id == project_id,
        ))).mappings().first()
    if row is None:
        raise ValueError("审查证据快照不存在或不属于当前项目")
    if hashlib.sha256(row["payload"].encode()).hexdigest() != row["sha256"]:
        raise ValueError("审查快照完整性校验失败")
    return json.loads(row["payload"]), row["sha256"]
