"""Acceptance-only worker: real activities with an explicit post-commit fault."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from temporalio import activity
from temporalio.client import Client
from temporalio.worker import Worker

from src.core.config import get_settings
from src.workflows import activities as actions
from src.workflows.temporal_definitions import (
    BatchDocumentIngestWorkflow,
    DocumentIngestWorkflow,
    PackageReviewWorkflow,
)


@activity.defn(name="plan_package_review_activity")
async def plan_with_pause(payload: dict) -> dict:
    if "--pause-plan" in sys.argv:
        directory = Path(sys.argv[sys.argv.index("--markers") + 1])
        (directory / "plan-started").write_text(payload["review_id"], encoding="ascii")
        await actions._heartbeat_delay("acceptance-review-running")
    return await actions.plan_package_review_activity(payload)


@activity.defn(name="compose_package_review_activity")
async def compose_with_fault(payload: dict) -> dict:
    result = await actions.compose_package_review_activity(payload)
    if activity.info().attempt == 1 and "--commit-fault" in sys.argv:
        directory = Path(sys.argv[sys.argv.index("--markers") + 1])
        (directory / "compose-committed").write_text(payload["review_id"], encoding="ascii")
        # Hold after the real commit until the harness has made a human decision.
        async with asyncio.timeout(45):
            while not (directory / "human-committed").exists():
                await asyncio.sleep(0.1)
        raise RuntimeError("acceptance injected failure after report commit")
    return result


async def main():
    settings = get_settings()
    client = await Client.connect(settings.TEMPORAL_TARGET)
    workers = [
        Worker(client, task_queue=settings.TEMPORAL_TASK_QUEUE,
               workflows=[DocumentIngestWorkflow, BatchDocumentIngestWorkflow, PackageReviewWorkflow]),
        Worker(client, task_queue=settings.TEMPORAL_PARSE_TASK_QUEUE,
               activities=[actions.parse_and_index_activity], max_concurrent_activities=1),
        Worker(client, task_queue=settings.TEMPORAL_REVIEW_TASK_QUEUE,
               activities=[plan_with_pause, actions.review_worker_activity,
                           actions.repair_review_coverage_activity, compose_with_fault], max_concurrent_activities=3),
        Worker(client, task_queue=settings.TEMPORAL_MAINTENANCE_TASK_QUEUE,
               activities=[actions.finalize_package_review_activity, actions.update_batch_activity,
                           actions.settle_review_budget_activity]),
    ]
    async with workers[0], workers[1], workers[2], workers[3]:
        Path(sys.argv[sys.argv.index("--ready") + 1]).write_text("ready", encoding="ascii")
        await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
