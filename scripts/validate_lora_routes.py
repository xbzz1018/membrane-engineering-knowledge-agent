"""Read model registrations only; never submit an inference request."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.infrastructure.model_provider import get_task_model_provider  # noqa: E402


async def main() -> None:
    providers = [get_task_model_provider(task) for task in ("query_normalization", "review_organization")]
    provider = providers[0]
    async with httpx.AsyncClient(timeout=provider.settings.HEALTHCHECK_TIMEOUT_SECONDS) as client:
        response = await client.get(provider._base_url() + "/models",
                                    headers={"Authorization": "Bearer " + provider._api_key()})
        response.raise_for_status()
        registered = {row["id"] for row in response.json()["data"]}
    missing = [item.model for item in providers if item.model not in registered]
    if missing:
        raise RuntimeError("Configured task adapter aliases are not registered")
    print(json.dumps({"registered_tasks": 2, "inference_run": False, "quality_verified": False}))


if __name__ == "__main__":
    asyncio.run(main())
