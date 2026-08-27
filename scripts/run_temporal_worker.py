from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def main() -> None:
    from temporalio.client import Client
    from temporalio.worker import Worker

    from src.core.config import get_settings
    from src.workflows.activities import package_review_activity, parse_and_index_activity
    from src.workflows.temporal_definitions import DocumentIngestWorkflow, PackageReviewWorkflow

    settings = get_settings()
    client = await Client.connect(settings.TEMPORAL_TARGET, namespace=settings.TEMPORAL_NAMESPACE)
    worker = Worker(
        client,
        task_queue="membrane-engineering",
        workflows=[DocumentIngestWorkflow, PackageReviewWorkflow],
        activities=[parse_and_index_activity, package_review_activity],
    )
    print(f"Temporal worker listening on {settings.TEMPORAL_TARGET}")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
