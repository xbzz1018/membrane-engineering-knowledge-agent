"""Bounded process-loss fixture for the new proposal workflows only."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ready", type=Path, required=True)
    parser.add_argument("--marker", type=Path)
    parser.add_argument("--pause", choices=["generation", "export"])
    args = parser.parse_args()
    from temporalio import activity
    from temporalio.client import Client
    from temporalio.worker import Worker

    from src.core.config import get_settings
    from src.documents.project_export import ProjectDocumentService
    from src.infrastructure.database import storage
    from src.infrastructure.project_plan_repository import ProjectPlanRepository
    from src.workflows.project_generation import ProjectExportWorkflow, ProjectGenerationWorkflow
    from src.workflows.project_plan_activities import (
        consume_project_plan_decision_activity,
        export_project_plan_activity,
        generate_project_plan_activity,
        review_project_plan_activity,
        settle_project_plan_activity,
    )

    async def pause(stage):
        if args.marker:
            args.marker.write_text(stage, encoding="utf-8")
        while True:
            activity.heartbeat({"synthetic_fault_pause": stage})
            await asyncio.sleep(1)

    original_acquire = ProjectPlanRepository.acquire
    original_store = ProjectDocumentService.store

    async def acquire(self, plan_id, version, stage, claim):
        result = await original_acquire(self, plan_id, version, stage, claim)
        if result and args.pause == "generation" and stage == "generating":
            await pause(stage)
        return result

    async def store(self, artifact, data):
        result = await original_store(self, artifact, data)
        if args.pause == "export":
            await pause("object_written_before_publication")
        return result

    ProjectPlanRepository.acquire = acquire
    ProjectDocumentService.store = store
    settings = get_settings()
    await storage.init()
    client = await Client.connect(settings.TEMPORAL_TARGET, namespace=settings.TEMPORAL_NAMESPACE)
    workers = [
        Worker(client, task_queue=settings.TEMPORAL_TASK_QUEUE,
               workflows=[ProjectGenerationWorkflow, ProjectExportWorkflow]),
        Worker(client, task_queue=settings.TEMPORAL_REVIEW_TASK_QUEUE,
               activities=[generate_project_plan_activity, review_project_plan_activity, export_project_plan_activity]),
        Worker(client, task_queue=settings.TEMPORAL_MAINTENANCE_TASK_QUEUE,
               activities=[consume_project_plan_decision_activity, settle_project_plan_activity]),
    ]
    args.ready.write_text("ready", encoding="utf-8")
    try:
        await asyncio.gather(*(worker.run() for worker in workers))
    finally:
        await storage.close()


if __name__ == "__main__":
    asyncio.run(main())
