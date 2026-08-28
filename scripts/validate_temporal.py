"""Validate Temporal workflows, signals, cancellation, idempotency and worker restart recovery."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx
from temporalio.client import Client

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core.config import get_settings
from src.engineering.storage import storage
from src.main import app


def start_worker(delay_seconds: int = 0) -> subprocess.Popen:
    environment = os.environ.copy()
    environment["TEMPORAL_ACTIVITY_TEST_DELAY_SECONDS"] = str(delay_seconds)
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.Popen(
        [sys.executable, "scripts/run_temporal_worker.py"],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creation_flags,
    )


def stop_worker(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


def assert_worker_running(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        raise RuntimeError(f"Temporal worker exited during startup with code {process.returncode}")


async def wait_temporal(settings) -> None:
    deadline = time.monotonic() + 90
    while True:
        try:
            await Client.connect(settings.TEMPORAL_TARGET, namespace=settings.TEMPORAL_NAMESPACE)
            return
        except Exception:
            if time.monotonic() >= deadline:
                raise
            await asyncio.sleep(2)


async def wait_state(
    client: httpx.AsyncClient,
    workflow_id: str,
    expected: set[str],
    timeout: float = 300,
) -> dict:
    deadline = time.monotonic() + timeout
    last: dict = {}
    while time.monotonic() < deadline:
        response = await client.get(f"/api/v1/workflows/{workflow_id}")
        if response.status_code == 200:
            last = response.json()
            cancellation_expected = bool(expected & {"cancelled", "canceled"})
            if cancellation_expected:
                if last.get("status") == "cancelled" and last.get("temporal_status") == "canceled":
                    return last
            elif last.get("status") in expected or last.get("temporal_status") in expected:
                return last
            if not cancellation_expected and (
                last.get("status") in {"failed", "cancelled"}
                or last.get("temporal_status") in {"failed", "canceled", "terminated", "timed_out"}
            ):
                raise RuntimeError(f"Workflow {workflow_id} reached unexpected terminal state: {last}")
        await asyncio.sleep(1)
    raise TimeoutError(f"Workflow {workflow_id} did not reach {expected}; last={last}")


async def upload_and_start_ingest(client: httpx.AsyncClient, filename: str, content: str) -> tuple[str, str]:
    uploaded = await client.post(
        "/api/v1/documents/upload",
        data={"project_id": get_settings().DEFAULT_PROJECT_ID},
        files={"file": (filename, content.encode("utf-8"), "text/plain")},
    )
    uploaded.raise_for_status()
    document_id = uploaded.json()["document_id"]
    indexed = await client.post(f"/api/v1/documents/{document_id}/index")
    indexed.raise_for_status()
    workflow_id = indexed.json()["workflow_id"]
    if not workflow_id:
        raise AssertionError("Temporal index response omitted workflow_id")
    return document_id, workflow_id


async def main() -> None:
    settings = get_settings()
    if not settings.TEMPORAL_ENABLED or settings.RUNTIME_MODE.lower() != "full":
        raise RuntimeError("validate_temporal.py requires Full mode and TEMPORAL_ENABLED=true")
    await wait_temporal(settings)
    worker = start_worker(delay_seconds=0)
    summary: dict[str, object] = {}
    try:
        await asyncio.sleep(3)
        assert_worker_running(worker)
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=600) as client:
                if settings.AUTH_ENABLED:
                    login = await client.post("/api/v1/auth/login", json={
                        "username": settings.BOOTSTRAP_ADMIN_USERNAME,
                        "password": settings.BOOTSTRAP_ADMIN_PASSWORD,
                    })
                    login.raise_for_status()
                    client.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
                suffix = uuid.uuid4().hex[:10]

                document_id, ingest_id = await upload_and_start_ingest(
                    client,
                    f"temporal-ingest-{suffix}.txt",
                    f"PTFE temporal document version 1 {suffix}",
                )
                ingest_state = await wait_state(client, ingest_id, {"completed"}, timeout=180)
                duplicate = await client.post(f"/api/v1/documents/{document_id}/index")
                duplicate.raise_for_status()
                if duplicate.json()["workflow_id"] != ingest_id or duplicate.json()["status"] != "existing":
                    raise AssertionError("Document workflow idempotent start did not reuse the workflow")
                summary["document_ingest"] = ingest_state["status"]

                async def submit_batch(size: int, label: str, document_ids: list[str] | None = None) -> tuple[dict, list[str]]:
                    batch_ids = list(document_ids or [])
                    for number in range(len(batch_ids), size):
                        uploaded = await client.post(
                            "/api/v1/documents/upload",
                            data={"project_id": settings.DEFAULT_PROJECT_ID},
                            files={
                                "file": (
                                    f"temporal-batch-{suffix}-{label}-{number}.txt",
                                    f"Batch evidence {suffix} {label} {number}".encode(),
                                    "text/plain",
                                )
                            },
                        )
                        uploaded.raise_for_status()
                        batch_ids.append(uploaded.json()["document_id"])
                    batch = await client.post("/api/v1/batch-imports", json={
                        "project_id": settings.DEFAULT_PROJECT_ID,
                        "document_ids": batch_ids,
                    })
                    batch.raise_for_status()
                    state = await wait_state(
                        client,
                        batch.json()["workflow_id"],
                        {"completed"},
                        timeout=600,
                    )
                    if state.get("completed_count") != size:
                        raise AssertionError(f"Batch ingest count mismatch: {state}")
                    return state, batch_ids

                batch_20, batch_20_ids = await submit_batch(20, "twenty")
                first_chunk_count = await storage.count_document_chunks(batch_20_ids[0])
                duplicate_batch, _ = await submit_batch(20, "duplicate", batch_20_ids)
                if await storage.count_document_chunks(batch_20_ids[0]) != first_chunk_count:
                    raise AssertionError("Duplicate batch changed indexed chunk count")
                batch_50, _ = await submit_batch(50, "fifty")
                summary["batch_20"] = batch_20["status"]
                summary["batch_20_duplicate"] = duplicate_batch["status"]
                summary["batch_50"] = batch_50["status"]

                package_document_ids = []
                for number, text in (
                    (1, f"设计资料 厚度 0.7 mm，版本 1，日期 2025-01，批次 {suffix}。"),
                    (2, f"膜材和价格资料 厚度 0.8 mm，版本 2，日期 2025-02，synthetic 价格，批次 {suffix}。"),
                ):
                    document_id, workflow_id = await upload_and_start_ingest(
                        client,
                        f"temporal-package-{suffix}-{number}.txt",
                        text,
                    )
                    await wait_state(client, workflow_id, {"completed"}, timeout=180)
                    package_document_ids.append(document_id)

                async def submit_review(action: str) -> dict:
                    response = await client.post(
                        "/api/v1/package-reviews",
                        json={
                            "project_id": settings.DEFAULT_PROJECT_ID,
                            "document_ids": package_document_ids,
                            "question": "审查设计、膜材和价格并识别厚度冲突。",
                        },
                    )
                    response.raise_for_status()
                    payload = response.json()
                    workflow_id = payload["workflow"]["workflow_id"]
                    await wait_state(client, workflow_id, {"awaiting_approval"}, timeout=420)
                    if action == "approved":
                        signal = await client.post(f"/api/v1/workflows/{workflow_id}/approve")
                    else:
                        signal = await client.post(
                            f"/api/v1/workflows/{workflow_id}/reject",
                            json={"reason": "版本冲突需退回"},
                        )
                    signal.raise_for_status()
                    final = await wait_state(client, workflow_id, {action}, timeout=120)
                    stored = await client.get(f"/api/v1/package-reviews/{payload['review_id']}")
                    stored.raise_for_status()
                    if stored.json()["status"] != action:
                        raise AssertionError(f"Persisted review did not reach {action}")
                    return final

                summary["approved_review"] = (await submit_review("approved"))["status"]
                summary["rejected_review"] = (await submit_review("rejected"))["status"]

                stop_worker(worker)
                worker = start_worker(delay_seconds=60)
                await asyncio.sleep(3)
                assert_worker_running(worker)
                _, restart_workflow = await upload_and_start_ingest(
                    client,
                    f"temporal-restart-{suffix}.txt",
                    f"Worker restart recovery document {suffix}",
                )
                await asyncio.sleep(2)
                stop_worker(worker)
                worker = start_worker(delay_seconds=0)
                await asyncio.sleep(3)
                assert_worker_running(worker)
                recovered = await wait_state(client, restart_workflow, {"completed"}, timeout=180)
                summary["worker_restart"] = recovered["status"]

                stop_worker(worker)
                worker = start_worker(delay_seconds=8)
                await asyncio.sleep(3)
                assert_worker_running(worker)
                _, cancel_id = await upload_and_start_ingest(
                    client,
                    f"temporal-cancel-{suffix}.txt",
                    f"Cancellation test document {suffix}",
                )
                await wait_state(client, cancel_id, {"running"}, timeout=30)
                cancelled = await client.post(f"/api/v1/workflows/{cancel_id}/cancel")
                cancelled.raise_for_status()
                final_cancel = await wait_state(client, cancel_id, {"cancelled", "canceled"}, timeout=60)
                if final_cancel.get("status") != "cancelled" or final_cancel.get("temporal_status") != "canceled":
                    raise AssertionError(f"Cancellation state mismatch: {final_cancel}")
                summary["cancellation"] = final_cancel["status"]

        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    finally:
        stop_worker(worker)


if __name__ == "__main__":
    asyncio.run(main())
