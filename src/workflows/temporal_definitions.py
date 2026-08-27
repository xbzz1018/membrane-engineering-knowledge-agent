from __future__ import annotations

import asyncio
from datetime import timedelta

try:
    from temporalio import workflow
    from temporalio.common import RetryPolicy
except ImportError:  # pragma: no cover - optional profile
    workflow = None
    RetryPolicy = None


def _retry_policy():
    return RetryPolicy(
        initial_interval=timedelta(seconds=2),
        backoff_coefficient=2.0,
        maximum_interval=timedelta(seconds=30),
        maximum_attempts=3,
        non_retryable_error_types=["ValueError"],
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
        async def run(self, document_id: str) -> dict:
            self._state = {"status": "running", "document_id": document_id, "result": None, "error": None}
            try:
                result = await workflow.execute_activity(
                    "parse_and_index_activity",
                    document_id,
                    schedule_to_close_timeout=timedelta(minutes=20),
                    start_to_close_timeout=timedelta(minutes=15),
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
    class PackageReviewWorkflow:
        def __init__(self) -> None:
            self._state = {
                "status": "created",
                "approval": "not_required",
                "rejection_reason": "",
                "result": None,
                "error": None,
            }
            self._decision: str | None = None

        @workflow.query
        def state(self) -> dict:
            return self._state

        @workflow.signal
        async def approve(self) -> None:
            if self._state["status"] == "awaiting_approval":
                self._decision = "approved"
                self._state = {**self._state, "approval": "approved"}

        @workflow.signal
        async def reject(self, reason: str = "") -> None:
            if self._state["status"] == "awaiting_approval":
                self._decision = "rejected"
                self._state = {
                    **self._state,
                    "approval": "rejected",
                    "rejection_reason": reason[:1000],
                }

        @workflow.run
        async def run(self, payload: dict) -> dict:
            self._state = {
                **self._state,
                "status": "running",
                "review_id": payload["review_id"],
            }
            try:
                result = await workflow.execute_activity(
                    "package_review_activity",
                    payload,
                    schedule_to_close_timeout=timedelta(minutes=25),
                    start_to_close_timeout=timedelta(minutes=20),
                    heartbeat_timeout=timedelta(seconds=30),
                    retry_policy=_retry_policy(),
                    cancellation_type=workflow.ActivityCancellationType.TRY_CANCEL,
                )
                self._state = {**self._state, "result": result}
                if result.get("conflicts"):
                    self._state = {**self._state, "status": "awaiting_approval", "approval": "pending"}
                    await workflow.wait_condition(lambda: self._decision is not None)
                    final_status = self._decision or "rejected"
                    await workflow.execute_activity(
                        "finalize_package_review_activity",
                        {"review_id": payload["review_id"], "status": final_status},
                        start_to_close_timeout=timedelta(minutes=2),
                        retry_policy=_retry_policy(),
                    )
                    self._state = {**self._state, "status": final_status, "approval": final_status}
                else:
                    self._state = {**self._state, "status": "completed", "approval": "not_required"}
                return self._state
            except asyncio.CancelledError:
                self._state = {**self._state, "status": "cancelled"}
                raise
            except Exception as exc:
                status = "cancelled" if workflow.cancellation_reason() is not None else "failed"
                self._state = {**self._state, "status": status, "error": type(exc).__name__}
                raise
else:
    DocumentIngestWorkflow = None
    PackageReviewWorkflow = None
