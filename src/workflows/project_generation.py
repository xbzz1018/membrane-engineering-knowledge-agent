"""New workflow types: never change the command sequence of existing review histories."""

from __future__ import annotations

import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy


def retry_policy():
    return RetryPolicy(
        initial_interval=timedelta(seconds=1), maximum_interval=timedelta(seconds=10), maximum_attempts=3,
        non_retryable_error_types=["PlanOwnershipLost", "PlanConflict", "ProjectAccessError", "AgentProtocolError",
                                   "ProviderConfigurationError", "ValueError"],
    )


@workflow.defn
class ProjectGenerationWorkflow:
    def __init__(self):
        self._state = {"status": "queued"}

    @workflow.query
    def state(self) -> dict:
        return self._state

    @workflow.run
    async def run(self, payload: dict) -> dict:
        options = dict(task_queue=payload["activity_queue"], start_to_close_timeout=timedelta(minutes=20),
                       schedule_to_close_timeout=timedelta(minutes=40), heartbeat_timeout=timedelta(seconds=15),
                       retry_policy=retry_policy())
        self._state = {"status": "generating", "plan_id": payload["plan_id"], "version": payload["version"]}
        try:
            await workflow.execute_activity("generate_project_plan_activity", payload, **options)
            self._state["status"] = "reviewing"
            result = await workflow.execute_activity("review_project_plan_activity", payload, **options)
            self._state["status"] = result["status"]
            if result["status"] != "awaiting_approval":
                return self._state
            # Persisted commands are authoritative; no Signal can approve a plan.
            while True:
                receipt = await workflow.execute_activity(
                    "consume_project_plan_decision_activity", payload,
                    task_queue=payload["maintenance_queue"], start_to_close_timeout=timedelta(minutes=1),
                    heartbeat_timeout=timedelta(seconds=15), retry_policy=retry_policy(),
                )
                if receipt:
                    self._state.update(receipt)
                    return self._state
                await workflow.sleep(timedelta(seconds=5))
        except BaseException as exc:
            self._state["status"] = "cancelled" if isinstance(exc, asyncio.CancelledError) else "failed"
            try:
                settled = await asyncio.shield(workflow.execute_activity(
                    "settle_project_plan_activity", {**payload, "status": self._state["status"]},
                    task_queue=payload["maintenance_queue"], start_to_close_timeout=timedelta(minutes=1),
                    retry_policy=retry_policy(),
                ))
                if settled.get("status") in {"approved", "rejected"}:
                    self._state.update(settled)
                    return self._state
            except Exception:
                self._state["terminal_sync_error"] = "business_state_not_settled"
            raise


@workflow.defn
class ProjectExportWorkflow:
    def __init__(self):
        self._state = {"status": "queued"}

    @workflow.query
    def state(self) -> dict:
        return self._state

    @workflow.run
    async def run(self, payload: dict) -> dict:
        self._state = {"status": "rendering", "artifact_id": payload["artifact_id"]}
        try:
            item = await workflow.execute_activity(
                "export_project_plan_activity", payload, task_queue=payload["activity_queue"],
                start_to_close_timeout=timedelta(minutes=5), schedule_to_close_timeout=timedelta(minutes=20),
                heartbeat_timeout=timedelta(seconds=15), retry_policy=retry_policy(),
            )
            self._state["status"] = item["status"]
            return self._state
        except BaseException as exc:
            self._state["status"] = "cancelled" if isinstance(exc, asyncio.CancelledError) else "failed"
            raise


async def _submit(workflow_type, workflow_id, payload):
    from temporalio.common import WorkflowIDReusePolicy
    from temporalio.exceptions import WorkflowAlreadyStartedError

    from src.core.config import get_settings
    from src.workflows.temporal_app import _client

    settings = get_settings()
    client = await _client()
    if client is None:
        raise RuntimeError("Temporal未启用，不能伪装为已排队")
    try:
        handle = await client.start_workflow(
            workflow_type.run, payload, id=workflow_id, task_queue=settings.TEMPORAL_TASK_QUEUE,
            execution_timeout=timedelta(days=7), task_timeout=timedelta(seconds=10),
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
        )
        status = "queued"
    except WorkflowAlreadyStartedError:
        handle = client.get_workflow_handle(workflow_id)
        status = "existing"
    return {"workflow_id": handle.id, "enabled": True, "status": status}


async def submit_project_workflow(plan_id, version):
    from src.core.config import get_settings

    settings = get_settings()
    return await _submit(ProjectGenerationWorkflow, f"project-plan:{plan_id}:v{version}", {
        "plan_id": plan_id, "version": version, "activity_queue": settings.TEMPORAL_REVIEW_TASK_QUEUE,
        "maintenance_queue": settings.TEMPORAL_MAINTENANCE_TASK_QUEUE,
    })


async def submit_export_workflow(artifact_id):
    from src.core.config import get_settings

    return await _submit(ProjectExportWorkflow, f"project-export:{artifact_id}", {
        "artifact_id": artifact_id, "activity_queue": get_settings().TEMPORAL_REVIEW_TASK_QUEUE,
    })
