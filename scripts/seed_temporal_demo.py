"""Seed an actual asynchronous demo; leaves a review waiting for a human."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

async def main():
    from scripts.demo_acceptance import SAMPLES

    async with httpx.AsyncClient(base_url="http://127.0.0.1:8080/api/v1", timeout=60, trust_env=False) as client:
        async def call(method, path, **kwargs):
            response = await client.request(method, path, **kwargs)
            response.raise_for_status()
            return response.json()

        async def wait(wid, target):
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                state = await call("GET", "/workflows/" + wid)
                if state.get("status") == target:
                    return state
                if state.get("status") in {"failed", "cancelled"}:
                    raise RuntimeError(json.dumps(state))
                await asyncio.sleep(0.5)
            raise TimeoutError(wid)

        ids = []
        for name, content in SAMPLES.items():
            doc = await call("POST", "/documents/upload", data={"project_id": "demo-project"},
                files={"file": (name, content.encode(), "text/plain")})
            did = doc["document_id"]
            indexed = await call("POST", f"/documents/{did}/index")
            await wait(indexed["workflow_id"], "completed")
            latest = await call("GET", "/documents/" + did)
            role = "design" if "design" in name else "material" if "material" in name else "price"
            await call("PUT", f"/documents/{did}/business-metadata", json={
                "engineering_model": "PTFE-502", "applicable_revision": "R1", "document_type": role,
                "effective_from": "2026-01-01", "effective_to": "2026-12-31",
                "source_note": "SYNTHETIC 演示声明；请以Evidence原文核对，不作为真实工程依据",
                "expected_lock_version": latest["lock_version"],
            })
            ids.append(did)
        review = await call("POST", "/package-reviews", json={"project_id": "demo-project", "document_ids": ids,
            "question": "核验设计、材料规格、历史价格的版本、厚度和价格口径。", "review_mode": "full"})
        assert review["status"] == "queued" and review["workflow"]["enabled"]
        await wait("package-review:" + review["review_id"], "awaiting_approval")
        record = {"validated_at": datetime.now(UTC).isoformat(), "mode": "local/fake/real-temporal",
                  "document_ids": ids, "review_id": review["review_id"], "submission_status": review["status"],
                  "review_url": "http://127.0.0.1:5173/reviews/" + review["review_id"], "waiting_for_human": True}
        (ROOT / "data/runtime/temporal-demo-acceptance.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
        print(json.dumps(record, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
