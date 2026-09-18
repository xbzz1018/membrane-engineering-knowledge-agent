from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def main() -> None:
    from temporalio.client import Client
    from temporalio.worker import Worker

    from src.core.config import get_settings
    from src.workflows.activities import (
        compose_package_review_activity,
        finalize_package_review_activity,
        parse_and_index_activity,
        plan_package_review_activity,
        repair_review_coverage_activity,
        review_worker_activity,
        settle_review_budget_activity,
        update_batch_activity,
    )
    from src.workflows.temporal_definitions import (
        BatchDocumentIngestWorkflow,
        DocumentIngestWorkflow,
        PackageReviewWorkflow,
    )

    settings = get_settings()
    client = await Client.connect(settings.TEMPORAL_TARGET, namespace=settings.TEMPORAL_NAMESPACE)
    orchestration_worker = Worker(
        client,
        task_queue=settings.TEMPORAL_TASK_QUEUE,
        workflows=[DocumentIngestWorkflow, BatchDocumentIngestWorkflow, PackageReviewWorkflow],
    )
    parse_worker = Worker(
        client,
        task_queue=settings.TEMPORAL_PARSE_TASK_QUEUE,
        activities=[parse_and_index_activity],
        max_concurrent_activities=1,
    )
    review_worker = Worker(
        client,
        task_queue=settings.TEMPORAL_REVIEW_TASK_QUEUE,
        activities=[
            plan_package_review_activity,
            review_worker_activity,
            repair_review_coverage_activity,
            compose_package_review_activity,
        ],
        max_concurrent_activities=3,
    )
    maintenance_worker = Worker(
        client,
        task_queue=settings.TEMPORAL_MAINTENANCE_TASK_QUEUE,
        activities=[finalize_package_review_activity, update_batch_activity, settle_review_budget_activity],
    )
    print(
        "Temporal workers listening on "
        f"{settings.TEMPORAL_TARGET} ({settings.TEMPORAL_TASK_QUEUE}, "
        f"{settings.TEMPORAL_PARSE_TASK_QUEUE}, {settings.TEMPORAL_REVIEW_TASK_QUEUE})"
    )
    await asyncio.gather(
        orchestration_worker.run(),
        parse_worker.run(),
        review_worker.run(),
        maintenance_worker.run(),
    )


if __name__ == "__main__":
    asyncio.run(main())
