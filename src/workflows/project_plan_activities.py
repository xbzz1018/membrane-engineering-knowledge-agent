from __future__ import annotations

from temporalio import activity

from src.application.project_plans import get_project_plan_service
from src.workflows.activities import _await_with_heartbeat


def claim():
    info = activity.info()
    return f"{info.workflow_id}:{info.workflow_run_id}:{info.activity_id}", info.attempt


@activity.defn
async def generate_project_plan_activity(payload: dict) -> dict:
    activity.heartbeat({"stage": "generating"})
    service = get_project_plan_service()
    await _await_with_heartbeat(service.generate(payload["plan_id"], payload["version"], claim()), "generating")
    record = await service.repo.get(payload["plan_id"], payload["version"])
    return {"status": record["status"]}


@activity.defn
async def review_project_plan_activity(payload: dict) -> dict:
    activity.heartbeat({"stage": "reviewing"})
    service = get_project_plan_service()
    await _await_with_heartbeat(service.review(payload["plan_id"], payload["version"], claim()), "reviewing")
    record = await service.repo.get(payload["plan_id"], payload["version"])
    return {"status": record["status"]}


@activity.defn
async def consume_project_plan_decision_activity(payload: dict) -> dict | None:
    activity.heartbeat({"stage": "decision"})
    service = get_project_plan_service()
    return await service.repo.consume_decision(payload["plan_id"], payload["version"])


@activity.defn
async def settle_project_plan_activity(payload: dict) -> dict:
    service = get_project_plan_service()
    return await service.repo.settle(payload["plan_id"], payload["version"], payload["status"])


@activity.defn
async def export_project_plan_activity(payload: dict) -> dict:
    activity.heartbeat({"stage": "exporting"})
    service = get_project_plan_service()
    await _await_with_heartbeat(service.render(payload["artifact_id"], claim()), "exporting")
    item = await service.repo.get_artifact(payload["artifact_id"])
    return {"status": item["status"]}
