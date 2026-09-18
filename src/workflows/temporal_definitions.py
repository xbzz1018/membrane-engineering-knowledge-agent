from __future__ import annotations

import asyncio
from datetime import timedelta

try:
    from temporalio import workflow
    from temporalio.common import RetryPolicy
    from temporalio.workflow import ParentClosePolicy
except ImportError:  # pragma: no cover
    workflow = None
    RetryPolicy = None
    ParentClosePolicy = None


def _retry_policy():
    return RetryPolicy(
        initial_interval=timedelta(seconds=2),
        backoff_coefficient=2.0,
        maximum_interval=timedelta(seconds=30),
        maximum_attempts=3,
        non_retryable_error_types=["ValueError", "ParserConfigurationError", "ReviewAgentError"],
    )


if workflow:

    @workflow.defn
    class DocumentIngestWorkflow:
        def __init__(self) -> None:
            self._state = {"status": "created", "result": None, "error": None}

        @workflow.query
        def state(self) -> dict:
            return self._state

        @workflow.run
        async def run(self, payload: str | dict) -> dict:
            document_id = payload if isinstance(payload, str) else payload["document_id"]
            parse_queue = "membrane-document-parse" if isinstance(payload, str) else payload.get(
                "parse_task_queue", "membrane-document-parse"
            )
            self._state = {"status": "running", "document_id": document_id, "result": None, "error": None}
            try:
                result = await workflow.execute_activity(
                    "parse_and_index_activity",
                    payload,
                    task_queue=parse_queue,
                    schedule_to_close_timeout=timedelta(minutes=25),
                    start_to_close_timeout=timedelta(minutes=20),
                    heartbeat_timeout=timedelta(seconds=30),
                    retry_policy=_retry_policy(),
                    cancellation_type=workflow.ActivityCancellationType.TRY_CANCEL,
                )
                self._state = {**self._state, "status": "completed", "result": result}
                return self._state
            except asyncio.CancelledError:
                self._state = {**self._state, "status": "cancelled"}
                raise
            except Exception as exc:
                status = "cancelled" if workflow.cancellation_reason() is not None else "failed"
                self._state = {**self._state, "status": status, "error": type(exc).__name__}
                raise


    @workflow.defn
    class BatchDocumentIngestWorkflow:
        def __init__(self) -> None:
            self._state = {
                "status": "created",
                "total": 0,
                "completed_count": 0,
                "failed_count": 0,
                "skipped_count": 0,
                "documents": {},
                "errors": [],
            }

        @workflow.query
        def state(self) -> dict:
            return self._state

        async def _run_child(self, payload: dict, document_id: str) -> tuple[str, dict]:
            try:
                result = await workflow.execute_child_workflow(
                    DocumentIngestWorkflow.run,
                    {**payload, "document_id": document_id},
                    id=f"document-ingest:{document_id}",
                    task_queue=payload.get("workflow_task_queue", "membrane-engineering"),
                    parent_close_policy=ParentClosePolicy.TERMINATE,
                )
                return document_id, result
            except Exception as exc:
                return document_id, {"status": "failed", "error": type(exc).__name__}

        @workflow.run
        async def run(self, payload: dict) -> dict:
            document_ids = list(dict.fromkeys(payload["document_ids"]))
            concurrency = max(1, int(payload.get("concurrency", 5)))
            self._state = {
                **self._state,
                "status": "running",
                "batch_id": payload["batch_id"],
                "total": len(document_ids),
                "documents": {item: "queued" for item in document_ids},
            }
            for start in range(0, len(document_ids), concurrency):
                window = document_ids[start:start + concurrency]
                for document_id in window:
                    self._state["documents"][document_id] = "running"
                results = await asyncio.gather(*(self._run_child(payload, item) for item in window))
                for document_id, result in results:
                    status = result.get("status", "failed")
                    normalized = "completed" if status == "completed" else status
                    self._state["documents"][document_id] = normalized
                    if normalized == "completed":
                        self._state["completed_count"] += 1
                    elif normalized in {"existing", "skipped"}:
                        self._state["skipped_count"] += 1
                    else:
                        self._state["failed_count"] += 1
                        self._state["errors"].append({"document_id": document_id, "error": result.get("error", "")})
                await workflow.execute_activity(
                    "update_batch_activity",
                    {
                        "batch_id": payload["batch_id"],
                        "state": {
                            "status": "running",
                            "completed_count": self._state["completed_count"],
                            "failed_count": self._state["failed_count"],
                            "skipped_count": self._state["skipped_count"],
                            "error_summary": self._state["errors"],
                        },
                    },
                    task_queue=payload.get("maintenance_task_queue", "membrane-maintenance"),
                    start_to_close_timeout=timedelta(minutes=1),
                    retry_policy=_retry_policy(),
                )
            self._state["status"] = "completed" if not self._state["failed_count"] else "partial_failed"
            await workflow.execute_activity(
                "update_batch_activity",
                {
                    "batch_id": payload["batch_id"],
                    "state": {
                        "status": self._state["status"],
                        "completed_count": self._state["completed_count"],
                        "failed_count": self._state["failed_count"],
                        "skipped_count": self._state["skipped_count"],
                        "error_summary": self._state["errors"],
                    },
                },
                task_queue=payload.get("maintenance_task_queue", "membrane-maintenance"),
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=_retry_policy(),
            )
            return self._state


    @workflow.defn
    class PackageReviewWorkflow:
        def __init__(self) -> None:
            self._state = {
                "status": "created",
                "approval": "not_required",
                "supervisor": "queued",
                "review_plan": None,
                "workers": {"design": "queued", "material": "queued", "price": "queued"},
                "result": None,
                "error": None,
            }
            self._decision: str | None = None

        @workflow.query
        def state(self) -> dict:
            return self._state

        @workflow.signal
        async def approve(self) -> None:
            if self._state["status"] == "awaiting_approval" and self._decision is None:
                self._decision = "approved"
                self._state = {**self._state, "approval": "approved"}

        @workflow.signal
        async def reject(self, reason: str = "") -> None:
            if self._state["status"] == "awaiting_approval" and self._decision is None:
                self._decision = "rejected"
                self._state = {**self._state, "approval": "rejected", "rejection_reason": reason[:1000]}

        @workflow.run
        async def run(self, payload: dict) -> dict:
            self._state = {**self._state, "status": "running", "review_id": payload["review_id"]}
            try:
                supervisor = await workflow.execute_activity(
                    "plan_package_review_activity",
                    payload,
                    task_queue=payload.get("review_task_queue", "membrane-agent-review"),
                    schedule_to_close_timeout=timedelta(minutes=10),
                    start_to_close_timeout=timedelta(minutes=5),
                    heartbeat_timeout=timedelta(seconds=30),
                    retry_policy=_retry_policy(),
                    cancellation_type=workflow.ActivityCancellationType.TRY_CANCEL,
                )
                plan = dict(supervisor.get("plan") or {})
                worker_names = [
                    worker for worker in plan.get("workers", [])
                    if worker in {"design", "material", "price"}
                ]
                if not worker_names:
                    raise ValueError("review supervisor returned no valid workers")
                self._state = {
                    **self._state,
                    "supervisor": "completed",
                    "review_plan": plan,
                    "workers": {
                        worker: "queued" if worker in worker_names else "skipped"
                        for worker in ("design", "material", "price")
                    },
                }
                worker_outputs = await asyncio.gather(*(
                    workflow.execute_activity(
                        "review_worker_activity",
                        {**payload, "worker": worker_name},
                        task_queue=payload.get("review_task_queue", "membrane-agent-review"),
                        schedule_to_close_timeout=timedelta(minutes=30),
                        start_to_close_timeout=timedelta(minutes=25),
                        heartbeat_timeout=timedelta(seconds=30),
                        retry_policy=_retry_policy(),
                        cancellation_type=workflow.ActivityCancellationType.TRY_CANCEL,
                    )
                    for worker_name in worker_names
                ))
                for worker_name in worker_names:
                    self._state["workers"][worker_name] = "completed"
                coverage_result = await workflow.execute_activity(
                    "repair_review_coverage_activity",
                    {
                        **payload,
                        "worker_outputs": worker_outputs,
                        "review_plan": plan,
                    },
                    task_queue=payload.get("review_task_queue", "membrane-agent-review"),
                    schedule_to_close_timeout=timedelta(minutes=30),
                    start_to_close_timeout=timedelta(minutes=25),
                    heartbeat_timeout=timedelta(seconds=30),
                    retry_policy=_retry_policy(),
                    cancellation_type=workflow.ActivityCancellationType.TRY_CANCEL,
                )
                worker_outputs = coverage_result["worker_outputs"]
                result = await workflow.execute_activity(
                    "compose_package_review_activity",
                    {
                        **payload,
                        "worker_outputs": worker_outputs,
                        "review_plan": plan,
                        "supervisor_usage": supervisor.get("usage", {}),
                        "coverage": coverage_result.get("coverage", {}),
                    },
                    task_queue=payload.get("review_task_queue", "membrane-agent-review"),
                    start_to_close_timeout=timedelta(minutes=5),
                    retry_policy=_retry_policy(),
                )
                self._state = {**self._state, "result": result}
                if result.get("human_review_required"):
                    self._state = {**self._state, "status": "awaiting_approval", "approval": "pending"}
                    await workflow.wait_condition(lambda: self._decision is not None)
                    final_status = self._decision or "rejected"
                    await workflow.execute_activity(
                        "finalize_package_review_activity",
                        {"review_id": payload["review_id"], "status": final_status},
                        task_queue=payload.get("maintenance_task_queue", "membrane-maintenance"),
                        start_to_close_timeout=timedelta(minutes=2),
                        retry_policy=_retry_policy(),
                    )
                    self._state = {**self._state, "status": final_status, "approval": final_status}
                else:
                    self._state = {**self._state, "status": "completed", "approval": "not_required"}
                return self._state
            except asyncio.CancelledError:
                self._state = {**self._state, "status": "cancelled"}
                try:
                    await asyncio.shield(workflow.execute_activity(
                        "settle_review_budget_activity",
                        {"review_id": payload["review_id"], "status": "cancelled", "actual_tokens": 0},
                        task_queue=payload.get("maintenance_task_queue", "membrane-maintenance"),
                        start_to_close_timeout=timedelta(minutes=1),
                        retry_policy=_retry_policy(),
                    ))
                except Exception:
                    pass
                raise
            except Exception as exc:
                status = "cancelled" if workflow.cancellation_reason() is not None else "failed"
                self._state = {**self._state, "status": status, "error": type(exc).__name__}
                try:
                    await asyncio.shield(workflow.execute_activity(
                        "settle_review_budget_activity",
                        {"review_id": payload["review_id"], "status": status, "actual_tokens": 0},
                        task_queue=payload.get("maintenance_task_queue", "membrane-maintenance"),
                        start_to_close_timeout=timedelta(minutes=1),
                        retry_policy=_retry_policy(),
                    ))
                except Exception:
                    pass
                raise
else:
    DocumentIngestWorkflow = None
    BatchDocumentIngestWorkflow = None
    PackageReviewWorkflow = None
