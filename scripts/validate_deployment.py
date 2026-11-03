"""Exercise a running Compose stack with public synthetic documents, not quality scores."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def source_sha256() -> str:
    digest = hashlib.sha256()
    for directory in ("src", "scripts", "deploy", "alembic"):
        for path in sorted((ROOT / directory).rglob("*")):
            if path.is_file() and path.suffix in {".py", ".yaml", ".conf"}:
                digest.update(path.relative_to(ROOT).as_posix().encode())
                digest.update(path.read_bytes())
    return digest.hexdigest()


async def wait_status(call, path: str, expected: str, timeout: float = 240) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        record = await call("GET", path)
        if record.get("status") == expected:
            return record
        if record.get("status") in {"failed", "index_failed", "cancelled", "rejected", "approved"}:
            raise AssertionError(f"Unexpected terminal status while waiting for {expected}")
        await asyncio.sleep(3)
    raise TimeoutError(f"Timed out waiting for {expected}")


async def exercise(summary: dict) -> None:
    from minio import Minio
    from sqlalchemy import text

    from deploy.entrypoint import validate_configuration
    from src.core.config import get_settings
    from src.domain.document_search import DocumentSearchFilters
    from src.infrastructure.database import SessionFactory
    from src.infrastructure.full_backends import get_full_backends

    settings = get_settings()
    validate_configuration(settings)
    summary.update({
        "runtime": "full", "model_mode": settings.MODEL_MODE,
        "embedding_model": settings.EMBEDDING_MODEL, "embedding_dimensions": settings.EMBEDDING_DIMENSIONS,
        "semantic_quality_evaluated": False, "reranker_enabled": settings.RERANKER_ENABLED,
        "data_kind": "public_synthetic", "source_sha256": source_sha256(),
    })
    summary["stage"] = "http-auth"
    base = os.environ.get("DEPLOYMENT_API_URL", "http://api:8080")
    async with httpx.AsyncClient(base_url=base, timeout=180, trust_env=False) as client:
        unauthorized = await client.get("/api/v1/projects")
        assert unauthorized.status_code == 401, "Unauthenticated project access must fail"
        login = await client.post("/api/v1/auth/login", json={
            "username": settings.BOOTSTRAP_ADMIN_USERNAME, "password": settings.BOOTSTRAP_ADMIN_PASSWORD,
        })
        login.raise_for_status()
        tenant_id = login.json()["principal"]["tenant_id"]
        client.headers["Authorization"] = "Bearer " + login.json()["access_token"]

        async def call(method, path, **kwargs):
            response = await client.request(method, "/api/v1" + path, **kwargs)
            response.raise_for_status()
            return response.json()

        suffix = uuid.uuid4().hex[:12]
        project = await call("POST", "/projects", json={"name": f"SYNTHETIC deploy acceptance {suffix}"})
        project_id = project["id"]
        summary["project_id"] = project_id
        summary["stage"] = "temporal-ingest"
        docs = []
        for index, (model, revision) in enumerate((("PTFE-502", "R2"), ("PTFE-5020", "R2"), ("PTFE-502", "R1"))):
            filename = f"synthetic-{suffix}-{index}.txt"
            content = (
                f"SYNTHETIC public deployment fixture {suffix}-{index}. No engineering authority.\n"
                f"膜材型号 {model}，适用版次 {revision}，名义厚度 0.8 mm。\n"
                "本资料仅用于部署链路验收，设计、材料、历史价格均需人工核验，不构成正式报价。"
            ).encode()
            document = await call("POST", "/documents/upload", data={
                "project_id": project_id, "data_classification": "public",
            }, files={"file": (filename, content, "text/plain")})
            did = document["document_id"]
            submitted = await call("POST", f"/documents/{did}/index")
            assert submitted["parser"] == "temporal" and submitted["workflow_id"], "Index must be asynchronous"
            await wait_status(call, "/workflows/" + submitted["workflow_id"], "completed")
            current = await call("GET", "/documents/" + did)
            assert current["status"] == "indexed"
            await call("PUT", f"/documents/{did}/business-metadata", json={
                "engineering_model": model, "applicable_revision": revision, "document_type": "material",
                "effective_from": "2026-01-01", "effective_to": "2026-12-31",
                "source_note": "Public synthetic TXT line 2; deployment fixture only",
                "expected_lock_version": current["lock_version"],
            })
            docs.append({"id": did, "filename": filename, "sha256": document["sha256"]})

        summary["stage"] = "postgres-vector-filter-fusion"
        filters = DocumentSearchFilters(engineering_model="PTFE-502", applicable_revision="R2", effective_on="2026-06-01")
        result = await call("POST", "/documents/search", json={
            "project_id": project_id, "query": "名义厚度", "filters": filters.model_dump(mode="json"), "limit": 10,
        })
        assert result["sources"] and {row["title"] for row in result["sources"]} == {docs[0]["filename"]}
        assert all(row["fusion_method"] == "weighted_rrf(k=60)" for row in result["sources"])
        backends = {trace["backend"] for row in result["sources"] for trace in row["retrieval"]}
        assert backends == {"postgresql", "pgvector"}, "REST retrieval must include both actual storage channels"
        vectors = await get_full_backends().search_documents(
            "名义厚度", project_id=project_id, tenant_id=tenant_id, classifications={"public"}, filters=filters,
        )
        assert vectors and {row["document_id"] for row in vectors} == {docs[0]["id"]}
        empty = await call("POST", "/documents/search", json={
            "project_id": project_id, "query": "名义厚度", "filters": {"engineering_model": "NO-SUCH-MODEL"},
        })
        assert not empty["sources"], "Exact conditions must exclude all nonmatching documents"

        async with SessionFactory() as session:
            extension = await session.scalar(text("SELECT extversion FROM pg_extension WHERE extname='vector'"))
            rows = (await session.execute(text(
                "SELECT document_id, vector_dims(embedding) AS dims, embedding_model "
                "FROM document_embeddings WHERE project_id=:project AND tenant_id=:tenant"
            ), {"project": project_id, "tenant": tenant_id})).mappings().all()
            indexes = (await session.execute(text(
                "SELECT indexdef FROM pg_indexes WHERE tablename='document_embeddings'"
            ))).scalars().all()
            claim_count = await session.scalar(text(
                "SELECT count(*) FROM document_ingest_claims c JOIN documents d ON d.id=c.document_id "
                "WHERE d.project_id=:project"
            ), {"project": project_id})
        assert extension and {row["document_id"] for row in rows} == {doc["id"] for doc in docs}
        assert all(row["dims"] == 1024 and row["embedding_model"] == settings.EMBEDDING_MODEL for row in rows)
        assert any("USING hnsw" in definition and "vector_cosine_ops" in definition for definition in indexes)
        assert claim_count == 3
        summary["pgvector"] = {"extension": extension, "vectors": len(rows), "dimensions": 1024,
                               "hnsw_index_exists": True, "query_plan_performance_evaluated": False}
        summary["retrieval"] = {"matching_documents": 1, "near_model_and_revision_excluded": True,
                                "empty_condition_checked": True, "channels": sorted(backends), "fusion": "rrf"}
        minio = Minio(settings.MINIO_ENDPOINT, access_key=settings.MINIO_ACCESS_KEY,
                      secret_key=settings.MINIO_SECRET_KEY, secure=settings.MINIO_SECURE)
        object_stat = await asyncio.to_thread(
            minio.stat_object, settings.MINIO_BUCKET,
            f"documents/{docs[0]['sha256']}/v1/{docs[0]['filename']}",
        )
        assert object_stat.size > 0
        summary["minio_original_size"] = object_stat.size

        summary["stage"] = "three-domain-review-and-durable-rejection"
        review = await call("POST", "/package-reviews", json={
            "project_id": project_id, "document_ids": [docs[0]["id"]], "review_mode": "full",
            "question": "仅用于合成部署验收，核查资料覆盖并输出需人工复核的缺失项。",
        })
        assert review["status"] == "queued" and review["workflow"]["enabled"]
        rid = review["review_id"]
        await wait_status(call, "/workflows/package-review:" + rid, "awaiting_approval", timeout=600)
        report = await call("GET", "/package-reviews/" + rid)
        assert set(report["worker_results"]) == {"design", "material", "price"}
        decision = await call("POST", f"/package-reviews/{rid}/decision", json={
            "decision": "rejected", "expected_lock_version": report["lock_version"],
            "reason": "SYNTHETIC automated deployment test; incomplete fixture intentionally returned for revision",
        })
        assert decision["status"] in {"decision_pending", "rejected"}
        await wait_status(call, "/workflows/package-review:" + rid, "rejected")
        final = await call("GET", "/package-reviews/" + rid)
        assert final["status"] == "rejected"
        summary["review"] = {"review_id": rid, "domain_results": sorted(report["worker_results"]),
                             "decision_submission_status": decision["status"], "final_status": final["status"]}

        summary["stage"] = "dependency-and-web-health"
        health = await client.get("/health/deps")
        health.raise_for_status()
        checks = health.json()["checks"]
        for name in ("database", "redis", "minio", "pgvector", "temporal", "model"):
            assert checks[name]["healthy"] is True, f"Dependency check failed: {name}"
        summary["dependencies"] = checks
        summary["pdf_ocr_available"] = checks["mineru"]["healthy"] is True
        async with httpx.AsyncClient(base_url="http://web:8080", timeout=10, trust_env=False) as web:
            assert (await web.get("/healthz")).status_code == 200
            page = await web.get("/documents")
            assert page.status_code == 200 and "<html" in page.text.lower()
            assert (await web.get("/api/v1/projects")).status_code == 401
        summary["same_origin_web"] = True


async def main() -> None:
    directory = Path(os.environ.get("DEPLOYMENT_RESULT_DIR", "/app/data/runtime/deployment"))
    directory.mkdir(parents=True, exist_ok=True)
    summary = {"run_id": datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8],
               "started_at": datetime.now(UTC).isoformat(), "status": "running"}
    try:
        await exercise(summary)
    except Exception as exc:
        summary.update({"status": "failed", "error_type": type(exc).__name__})
        raise
    else:
        summary.update({"status": "passed", "stage": "complete"})
    finally:
        summary["finished_at"] = datetime.now(UTC).isoformat()
        encoded = json.dumps(summary, indent=2, ensure_ascii=False)
        (directory / (summary["run_id"] + ".json")).write_text(encoded, encoding="utf-8")
        (directory / "latest.json").write_text(encoded, encoding="utf-8")
        print(encoded, flush=True)


if __name__ == "__main__":
    asyncio.run(main())
