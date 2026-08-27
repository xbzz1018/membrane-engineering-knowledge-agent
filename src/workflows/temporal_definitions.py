from __future__ import annotations

from datetime import timedelta

try:
    from temporalio import workflow
except ImportError:  # pragma: no cover - optional profile
    workflow = None


if workflow:

    @workflow.defn
    class DocumentIngestWorkflow:
        @workflow.run
        async def run(self, document_id: str) -> dict:
            return await workflow.execute_activity(
                "parse_and_index_activity",
                document_id,
                start_to_close_timeout=timedelta(minutes=15),
            )


    @workflow.defn
    class PackageReviewWorkflow:
        def __init__(self):
            self.approved = False

        @workflow.signal
        async def approve(self) -> None:
            self.approved = True

        @workflow.run
        async def run(self, payload: dict) -> dict:
            result = await workflow.execute_activity(
                "package_review_activity",
                payload,
                start_to_close_timeout=timedelta(minutes=20),
            )
            if result.get("conflicts"):
                await workflow.wait_condition(lambda: self.approved)
            return result
else:
    DocumentIngestWorkflow = None
    PackageReviewWorkflow = None
