"""Actual dev-server recovery acceptance; SQLite/Fake, no model quality claims."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


async def until(check, timeout=100):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = await check()
        if value:
            return value
        await asyncio.sleep(0.25)
    raise TimeoutError("proposal acceptance condition not reached")


async def main():
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    output = ROOT / "data/runtime/project-plan-temporal" / run_id
    output.mkdir(parents=True)
    suffix = run_id[-8:]
    os.environ.update(
        RUNTIME_MODE="local", MODEL_MODE="fake", MODEL_PROVIDER="fake", PARSER_MODE="basic",
        TEMPORAL_ENABLED="true", AUTH_ENABLED="false", DATABASE_URL="", LONG_TERM_MEMORY_ENABLED="false",
        LOCAL_DB_PATH=str(output / "business.db"), LOCAL_UPLOAD_PATH=str(output / "uploads"),
        TEMPORAL_TASK_QUEUE="plan-accept-wf-" + suffix, TEMPORAL_REVIEW_TASK_QUEUE="plan-accept-review-" + suffix,
        TEMPORAL_MAINTENANCE_TASK_QUEUE="plan-accept-maint-" + suffix, PYTHONIOENCODING="utf-8",
        TEMPORAL_ACTIVITY_TEST_DELAY_SECONDS="0",
    )
    import httpx
    from sqlalchemy import select
    from temporalio.testing import WorkflowEnvironment
    from temporalio.worker import Replayer

    from scripts.run_business_eval import code_digest
    from src.core.config import get_settings
    from src.infrastructure.database import project_plan_artifacts, project_plan_versions, storage
    from src.main import app
    from src.workflows.project_generation import ProjectExportWorkflow, ProjectGenerationWorkflow

    summary = {"run_id": run_id, "mode": "real Temporal dev server / SQLite / Fake Agents / synthetic sources",
               "code_sha256_at_start": code_digest(), "checks": {},
               "not_validated": ["PostgreSQL/pgvector", "real model quality", "production failover", "Word layout"]}
    worker = None
    logs = []

    def stop_worker():
        nonlocal worker
        if worker and worker.poll() is None:
            worker.kill()
            worker.wait(timeout=10)
        worker = None

    async def start_worker(pause=None):
        nonlocal worker
        ready = output / ("ready-" + uuid.uuid4().hex)
        marker = output / ("marker-" + uuid.uuid4().hex)
        log = (output / (ready.name + ".log")).open("w", encoding="utf-8")
        logs.append(log)
        worker = subprocess.Popen(
            [sys.executable, "scripts/project_plan_fault_worker.py", "--ready", str(ready),
             *(["--pause", pause, "--marker", str(marker)] if pause else [])],
            cwd=ROOT, env=os.environ.copy(), stdout=log, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

        async def ready_check():
            if worker.poll() is not None:
                raise RuntimeError("proposal worker exited; inspect " + log.name)
            return ready.exists()
        await until(ready_check, 120)
        print(json.dumps({"stage": "worker_ready", "pause": pause}), flush=True)
        return marker

    histories = {}
    try:
        server = await WorkflowEnvironment.start_local(
            download_dest_dir=str(ROOT / "data/runtime/temporal-bin"),
            dev_server_database_filename=str(output / "temporal.db"),
        )
        os.environ["TEMPORAL_TARGET"] = server.client.service_client.config.target_host
        get_settings().TEMPORAL_TARGET = os.environ["TEMPORAL_TARGET"]
        async with server, app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", timeout=40) as api:
                async def request(method, path, **kwargs):
                    response = await api.request(method, "/api/v1" + path, **kwargs)
                    response.raise_for_status()
                    return response.json()

                project = await request("POST", "/projects", json={"name": "SYNTHETIC proposal recovery " + suffix})
                project_id = project["id"]
                source = await storage.add_document(
                    "synthetic-plan-recovery.txt", "text/plain", b"synthetic-public-plan-" + suffix.encode(), "basic",
                    project_id=project_id, tenant_id=get_settings().DEFAULT_TENANT_ID,
                )
                await storage.save_chunks(source["id"], [{
                    "chunk_index": 0, "location": "合成资料第1段",
                    "text": "SYNTHETIC 停车棚历史项目案例。膜材 PVDF-PLAN-RECOVERY，适用版次 R1。仅用于恢复测试。",
                }], "basic")
                marker = await start_worker("generation")
                payload = {"request_id": uuid.uuid4().hex, "requirements": {
                    "project_name": "合成停车棚恢复验收", "building_area_m2": 800, "purpose": "停车棚",
                    "location": "合成测试场地", "preferred_membrane": "PVDF-PLAN-RECOVERY", "applicable_revision": "R1",
                }}
                accepted = await request("POST", f"/projects/{project_id}/plans", json=payload)
                plan_id = accepted["plan_id"]
                workflow_id = accepted["workflow_id"]
                duplicate = await request("POST", f"/projects/{project_id}/plans", json=payload)
                assert duplicate["plan_id"] == plan_id and duplicate["workflow_id"] == workflow_id
                summary["checks"]["duplicate_request_same_plan_and_workflow"] = True

                async def marker_exists():
                    return marker.exists()
                await until(marker_exists)
                stop_worker()  # Crash after persisted claim, before generation.
                await start_worker()

                async def awaiting():
                    record = await request("GET", f"/plans/{plan_id}")
                    if record["status"] in {"failed", "needs_revision", "cancelled"}:
                        raise RuntimeError("proposal did not reach approval: " + json.dumps({
                            "status": record["status"], "error_type": record["error_type"],
                            "issues": record["review"]["result"]["issues"] if record["review"] else [],
                        }, ensure_ascii=False))
                    return record if record["status"] == "awaiting_approval" else None
                record = await until(awaiting)
                async with storage.session_factory() as session:
                    version_rows = (await session.execute(select(project_plan_versions).where(
                        project_plan_versions.c.plan_id == plan_id,
                    ))).mappings().all()
                assert len(version_rows) == 1 and record["version"] == 1
                generation_history = await server.client.get_workflow_handle(workflow_id).fetch_history()
                attempts = [event.activity_task_started_event_attributes.attempt for event in generation_history.events
                            if event.HasField("activity_task_started_event_attributes")]
                assert max(attempts) >= 2
                summary["checks"]["worker_killed_after_claim_retries_without_duplicate_version"] = True
                print(json.dumps({"stage": "generation_recovered"}), flush=True)

                stop_worker()
                command = {"command_id": uuid.uuid4().hex, "expected_lock_version": record["lock_version"],
                           "review_id": record["review"]["id"], "content_hash": record["content_hash"],
                           "manifest_hash": record["manifest_hash"], "decision": "approved", "reason": "人工确认合成方案"}
                pending = await request("POST", f"/plans/{plan_id}/versions/1/decision", json=command)
                assert pending["status"] == "decision_pending"
                denied = await api.post(f"/api/v1/plans/{plan_id}/versions/1/exports", json={"formats": ["docx"]})
                assert denied.status_code == 409
                marker = await start_worker("export")

                async def approved():
                    row = await request("GET", f"/plans/{plan_id}")
                    return row if row["status"] == "approved" else None
                await until(approved)
                summary["checks"]["offline_human_decision_persisted_then_consumed"] = True
                print(json.dumps({"stage": "offline_decision_consumed"}), flush=True)

                exported = await request("POST", f"/plans/{plan_id}/versions/1/exports", json={"formats": ["docx"]})
                artifact_id = exported["artifacts"][0]["id"]
                await until(marker_exists)
                stop_worker()  # Object exists, artifact not yet published.
                await start_worker()

                async def published():
                    row = await request("GET", f"/plans/{plan_id}")
                    return next((item for item in row["artifacts"] if item["id"] == artifact_id and item["status"] == "published"), None)
                file = await until(published)
                repeated = await request("POST", f"/plans/{plan_id}/versions/1/exports", json={"formats": ["docx"]})
                assert repeated["artifacts"][0]["id"] == artifact_id
                data = await api.get(file["download_url"])
                assert data.status_code == 200 and hashlib.sha256(data.content).hexdigest() == file["sha256"]
                (output / "approved-plan.docx").write_bytes(data.content)
                async with storage.session_factory() as session:
                    rows = (await session.execute(select(project_plan_artifacts).where(
                        project_plan_artifacts.c.plan_id == plan_id,
                    ))).mappings().all()
                assert len(rows) == 1 and rows[0]["attempt"] >= 2
                summary["checks"]["object_written_worker_killed_single_published_artifact"] = True

                async def workflow_done(workflow_id):
                    state = await server.client.get_workflow_handle(workflow_id).describe()
                    return state if state.status.name == "COMPLETED" else None
                for workflow_type, identity in ((ProjectGenerationWorkflow, workflow_id),
                                                 (ProjectExportWorkflow, "project-export:" + artifact_id)):
                    await until(lambda: workflow_done(identity))
                    history = await server.client.get_workflow_handle(identity).fetch_history()
                    await Replayer(workflows=[workflow_type]).replay_workflow(history)
                    name = workflow_type.__name__ + ".json"
                    (output / name).write_text(history.to_json(), encoding="utf-8")
                    histories[workflow_type.__name__] = name
                summary["checks"]["two_real_histories_replayed"] = True
                summary.update(plan_id=plan_id, artifact_id=artifact_id, histories=histories,
                               docx_sha256=file["sha256"], all_passed=True)
    except Exception as exc:
        summary.update(all_passed=False, error_type=type(exc).__name__, error=str(exc)[:1500])
        raise
    finally:
        stop_worker()
        for log in logs:
            log.close()
        summary["code_sha256_at_end"] = code_digest()
        summary["source_changed_during_run"] = summary["code_sha256_at_start"] != summary["code_sha256_at_end"]
        summary["finished_at"] = datetime.now(UTC).isoformat()
        (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"output": str(output), **summary}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
