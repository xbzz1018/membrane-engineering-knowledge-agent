"""Real Temporal server/process crash acceptance, explicitly Local/Fake/TXT."""

from __future__ import annotations

import asyncio
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
        result = await check()
        if result:
            return result
        await asyncio.sleep(0.2)
    raise TimeoutError("acceptance condition not reached")


async def main():
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    output = ROOT / "data/runtime/temporal-local" / run_id
    output.mkdir(parents=True)
    suffix = run_id[-8:]
    os.environ.update(
        RUNTIME_MODE="local", MODEL_MODE="fake", MODEL_PROVIDER="fake", PARSER_MODE="basic",
        AUTH_ENABLED="false", TEMPORAL_ENABLED="true", DATABASE_URL="",
        LOCAL_DB_PATH=str(output / "business.db"), LOCAL_UPLOAD_PATH=str(output / "uploads"),
        TEMPORAL_TASK_QUEUE="accept-workflow-" + suffix, TEMPORAL_PARSE_TASK_QUEUE="accept-parse-" + suffix,
        TEMPORAL_REVIEW_TASK_QUEUE="accept-review-" + suffix, TEMPORAL_MAINTENANCE_TASK_QUEUE="accept-maint-" + suffix,
        API_RATE_LIMIT_PER_MINUTE="10000", PYTHONIOENCODING="utf-8", LONG_TERM_MEMORY_ENABLED="false",
    )
    import httpx
    from temporalio.testing import WorkflowEnvironment
    from temporalio.worker import Replayer

    from scripts.demo_acceptance import SAMPLES
    from scripts.run_business_eval import code_digest
    from src.core.config import get_settings
    from src.infrastructure.database import storage
    from src.main import app
    from src.workflows.temporal_definitions import (
        BatchDocumentIngestWorkflow,
        DocumentIngestWorkflow,
        PackageReviewWorkflow,
    )

    summary = {"run_id": run_id, "started_at": datetime.now(UTC).isoformat(),
               "code_sha256_at_start": code_digest(),
               "mode": "real Temporal dev server / SQLite business storage / Fake Agents / TXT parser",
               "checks": {}, "not_validated": ["PostgreSQL/pgvector", "real LLM quality", "MinerU",
                                                  "production failover", "old production history migration"]}
    worker = None
    logs = []

    async def start_worker(*, delay=0, fault=False, pause_plan=False):
        nonlocal worker
        ready = output / ("ready-" + uuid.uuid4().hex)
        log = (output / (ready.name + ".log")).open("w", encoding="utf-8")
        logs.append(log)
        worker = subprocess.Popen(
            [sys.executable, "scripts/temporal_fault_worker.py", "--ready", str(ready), "--markers", str(output),
             *(["--commit-fault"] if fault else []), *(["--pause-plan"] if pause_plan else [])], cwd=ROOT,
            env={**os.environ, "TEMPORAL_ACTIVITY_TEST_DELAY_SECONDS": str(delay)},
            stdout=log, stderr=subprocess.STDOUT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

        async def is_ready():
            if worker.poll() is not None:
                raise RuntimeError("worker exited; inspect " + log.name)
            return ready.exists()
        await until(is_ready, 40)

    def kill_worker():
        nonlocal worker
        if worker is not None and worker.poll() is None:
            worker.kill()  # Deliberate process loss: no shutdown/finally hooks.
            worker.wait(timeout=10)
        worker = None

    histories = {}
    try:
        bins = ROOT / "data/runtime/temporal-bin"
        bins.mkdir(exist_ok=True)
        server = await WorkflowEnvironment.start_local(
            download_dest_dir=str(bins), dev_server_database_filename=str(output / "temporal.db"),
        )
        os.environ["TEMPORAL_TARGET"] = server.client.service_client.config.target_host
        get_settings().TEMPORAL_TARGET = os.environ["TEMPORAL_TARGET"]
        async with server, app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", timeout=60) as api:
                async def request(method, path, **kwargs):
                    response = await api.request(method, "/api/v1" + path, **kwargs)
                    response.raise_for_status()
                    return response.json()

                project = await request("POST", "/projects", json={"name": "SYNTHETIC Temporal " + suffix})
                pid = project["id"]

                async def upload(name, text):
                    uploaded = await request("POST", "/documents/upload", data={"project_id": pid},
                        files={"file": (name, text.encode(), "text/plain")})
                    indexed = await request("POST", f"/documents/{uploaded['document_id']}/index")
                    return uploaded["document_id"], indexed["workflow_id"]

                async def state(wid, expected):
                    value = await request("GET", "/workflows/" + wid)
                    terminal_ready = "cancelled" not in expected or value.get("temporal_status") == "canceled"
                    if value.get("status") in expected and terminal_ready:
                        return value
                    if value.get("status") == "failed":
                        raise RuntimeError("workflow failed: " + json.dumps(value))
                    return None

                await start_worker(delay=60)
                did, wid = await upload("crash-after-acquire.txt", "SYNTHETIC worker process recovery")

                async def locked():
                    return (await storage.get_document(did))["status"] == "indexing"
                await until(locked)
                kill_worker()
                assert (await storage.get_document(did))["status"] == "indexing"
                await start_worker()
                await until(lambda: state(wid, {"completed"}), 110)
                assert (await storage.get_document(did))["status"] == "indexed"
                assert await storage.count_document_chunks(did) == 1
                histories[wid] = await server.client.get_workflow_handle(wid).fetch_history()
                attempts = [event.activity_task_started_event_attributes.attempt for event in histories[wid].events
                            if event.HasField("activity_task_started_event_attributes")]
                assert max(attempts) >= 2, attempts
                summary["checks"]["process_kill_after_ingest_claim"] = {"passed": True, "attempts": attempts}
                from src.workflows.temporal_app import submit_document_ingest

                duplicate = await submit_document_ingest(did)
                assert duplicate["status"] == "existing" and duplicate["workflow_id"] == wid
                summary["checks"]["duplicate_workflow_submission"] = {"passed": True}

                ids = []
                for name, text in SAMPLES.items():
                    doc, workflow_id = await upload(name, text)
                    await until(lambda wid=workflow_id: state(wid, {"completed"}))
                    ids.append(doc)

                kill_worker()
                await start_worker(fault=True)
                created = await request("POST", "/package-reviews", json={"project_id": pid, "document_ids": ids})
                rid = created["review_id"]
                review_wid = "package-review:" + rid

                async def committed():
                    return (output / "compose-committed").exists()
                await until(committed)
                review = await request("GET", "/package-reviews/" + rid)
                issue = review["issues"][0]
                mutation = await request("PATCH", f"/package-reviews/{rid}/issues/{issue['issue_id']}",
                    json={"status": "resolved", "expected_lock_version": review["lock_version"], "reason": "SYNTHETIC 核验"})
                decision = await request("POST", f"/package-reviews/{rid}/decision",
                    json={"decision": "rejected", "reason": "SYNTHETIC 补充材料",
                          "expected_lock_version": mutation["lock_version"]})
                assert decision["status"] == "decision_pending"
                before = await storage.get_package_review(rid)
                (output / "human-committed").write_text("ready", encoding="ascii")
                await until(lambda: state(review_wid, {"rejected"}))
                after = await storage.get_package_review(rid)
                assert after["status"] == "rejected"
                assert after["issues"] == before["issues"] and after["sources"] == before["sources"]
                assert after["usage"]["human_review_events"] == before["usage"]["human_review_events"]
                histories[review_wid] = await server.client.get_workflow_handle(review_wid).fetch_history()
                retry_attempts = [event.activity_task_started_event_attributes.attempt for event in histories[review_wid].events
                                  if event.HasField("activity_task_started_event_attributes")]
                assert max(retry_attempts) >= 2
                summary["checks"]["report_commit_failure_then_early_human_decision"] = {
                    "passed": True, "activity_attempts": retry_attempts, "review_id": rid,
                    "human_events": len(after["usage"]["human_review_events"]),
                }

                kill_worker()
                await start_worker()
                pending = await request("POST", "/package-reviews", json={"project_id": pid, "document_ids": ids})
                pending_wid = "package-review:" + pending["review_id"]
                await until(lambda: state(pending_wid, {"awaiting_approval"}))
                await server.client.get_workflow_handle(pending_wid).signal("approve")
                await asyncio.sleep(1)
                assert (await request("GET", "/package-reviews/" + pending["review_id"]))["status"] == "awaiting_approval"
                kill_worker()
                await start_worker()
                await until(lambda: state(pending_wid, {"awaiting_approval"}))
                await request("POST", "/workflows/" + pending_wid + "/cancel")
                await until(lambda: state(pending_wid, {"cancelled"}))
                assert (await storage.get_package_review(pending["review_id"]))["status"] == "cancelled"
                histories[pending_wid] = await server.client.get_workflow_handle(pending_wid).fetch_history()
                summary["checks"]["signal_cannot_approve_restart_waiting_then_cancel"] = {"passed": True}

                approving = await request("POST", "/package-reviews", json={"project_id": pid, "document_ids": ids})
                arid = approving["review_id"]
                awid = "package-review:" + arid
                await until(lambda: state(awid, {"awaiting_approval"}))
                # Stop all consumers first; a committed command must survive this outage.
                kill_worker()
                row = await request("GET", "/package-reviews/" + arid)
                for issue in row["issues"]:
                    changed = await request("PATCH", f"/package-reviews/{arid}/issues/{issue['issue_id']}",
                        json={"status": "resolved", "expected_lock_version": row["lock_version"], "reason": "SYNTHETIC 核对"})
                    row["lock_version"] = changed["lock_version"]
                approved = await request("POST", f"/package-reviews/{arid}/decision",
                    json={"decision": "approved", "expected_lock_version": row["lock_version"]})
                assert approved["status"] == "decision_pending"
                await start_worker()
                await until(lambda: state(awid, {"approved"}), 40)
                assert (await storage.get_package_review(arid))["status"] == "approved"
                histories[awid] = await server.client.get_workflow_handle(awid).fetch_history()
                summary["checks"]["approval_committed_while_worker_down"] = {"passed": True}

                kill_worker()
                await start_worker(delay=60, pause_plan=True)
                running = await request("POST", "/package-reviews", json={"project_id": pid, "document_ids": ids})
                rwid = "package-review:" + running["review_id"]

                async def plan_started():
                    return (output / "plan-started").exists()
                await until(plan_started)
                await request("POST", "/workflows/" + rwid + "/cancel")
                await until(lambda: state(rwid, {"cancelled"}))
                assert (await storage.get_package_review(running["review_id"]))["status"] == "cancelled"
                histories[rwid] = await server.client.get_workflow_handle(rwid).fetch_history()
                summary["checks"]["cancel_during_review_activity"] = {"passed": True}

                for index, (workflow_id, history) in enumerate(histories.items()):
                    (output / f"history-{index}.json").write_text(history.to_json(), encoding="utf-8")
                    await Replayer(workflows=[DocumentIngestWorkflow, BatchDocumentIngestWorkflow, PackageReviewWorkflow]
                                   ).replay_workflow(history)
                summary["checks"]["recorded_histories_replay"] = {"passed": True, "n": len(histories)}
                summary["project_id"] = pid
        summary["passed"] = True
    except Exception as exc:
        summary.update(passed=False, error_type=type(exc).__name__, error=str(exc))
        raise
    finally:
        kill_worker()
        for index, (workflow_id, history) in enumerate(histories.items()):
            (output / f"history-{index}.json").write_text(history.to_json(), encoding="utf-8")
        summary["history_files"] = {workflow_id: f"history-{index}.json" for index, workflow_id in enumerate(histories)}
        for handle in logs:
            handle.close()
        summary["finished_at"] = datetime.now(UTC).isoformat()
        summary["code_sha256_at_end"] = code_digest()
        summary["source_changed_during_run"] = summary["code_sha256_at_start"] != summary["code_sha256_at_end"]
        (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
