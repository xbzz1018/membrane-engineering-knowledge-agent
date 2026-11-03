"""Exercise a running HTTP service and the real MCP stdio transport with synthetic data."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SAMPLES = {
    "A120-design-demo.txt": "SYNTHETIC 测试资料。A-120 设计方案，膜材型号 PTFE-502，节点采用可更换连接件，设计要求厚度 0.8 mm。适用版本 R1。版本 v1。",
    "PTFE502-material-demo.txt": "SYNTHETIC 测试资料。PTFE-502 膜材规格，厚度 0.7 mm，适用版本 R1，单位面积质量 700 g/m2，版本 v1。",
    "A120-price-demo.txt": "SYNTHETIC 历史测试价格。A-120 项目 PTFE-502 膜材，价格 235 CNY/m2，日期 2026-03，地区 上海，含税。版本 v1。非正式报价。",
}


async def main(base_url: str, skip_mcp: bool) -> dict:
    os.environ.update(
        {
            "RUNTIME_MODE": "local",
            "MODEL_MODE": "fake",
            "MODEL_PROVIDER": "fake",
            "PARSER_MODE": "basic",
            "TEMPORAL_ENABLED": "false",
            "AUTH_ENABLED": "false",
            "LOCAL_DB_PATH": str(ROOT / "data/runtime/demo.db"),
            "DATABASE_URL": "",
        }
    )
    sample_dir = ROOT / "data/demo"
    sample_dir.mkdir(parents=True, exist_ok=True)
    documents = []
    async with httpx.AsyncClient(base_url=base_url, timeout=60, trust_env=False) as client:
        (await client.get("/health")).raise_for_status()
        for name, text in SAMPLES.items():
            content = text.encode("utf-8")
            (sample_dir / name).write_bytes(content)
            upload = await client.post(
                "/api/v1/documents/upload",
                files={"file": (name, content, "text/plain")},
                data={
                    "project_id": "demo-project",
                    "data_classification": "public",
                    "version": "1",
                },
            )
            upload.raise_for_status()
            document_id = upload.json()["document_id"]
            indexed = await client.post(f"/api/v1/documents/{document_id}/index")
            indexed.raise_for_status()
            assert indexed.json()["chunks"] > 0
            documents.append(document_id)
        replay = await client.post(
            "/api/v1/documents/upload",
            files={
                "file": (next(iter(SAMPLES)), next(iter(SAMPLES.values())).encode(), "text/plain"),
            },
            data={"project_id": "demo-project", "data_classification": "public", "version": "1"},
        )
        replay.raise_for_status()
        assert replay.json()["document_id"] == documents[0]
        chat = await client.post(
            "/api/v1/chat",
            json={
                "project_id": "demo-project",
                "session_id": "landing-demo",
                "message": "PTFE-502 膜材的单位面积质量和厚度是什么？",
            },
        )
        chat.raise_for_status()
        assert chat.json()["sources"]
        response = await client.post(
            "/api/v1/package-reviews",
            json={
                "project_id": "demo-project",
                "document_ids": documents,
                "question": "核验 A-120 设计方案、PTFE-502 膜材和历史价格的厚度、单位与版本冲突。",
                "review_mode": "full",
            },
        )
        response.raise_for_status()
        review = response.json()
        trace = review["usage"]["supervisor"]["delegation"]
        assert set(trace["tool_names"]) == {"review_retrieval", "review_material", "review_review"}
        assert trace["tool_calls"] == 3
        assert any(item["issue_type"] == "thickness_conflict" for item in review["issues"])
        assert review["human_review_required"]
        blocked = await client.post(
            f"/api/v1/package-reviews/{review['review_id']}/decision",
            json={
                "decision": "approved",
                "expected_lock_version": review["lock_version"],
            },
        )
        assert blocked.status_code == 409
        report = await client.get(f"/api/v1/package-reviews/{review['review_id']}")
        report.raise_for_status()
        assert report.json()["report"] == review["report"]
        issue = next(item for item in review["issues"] if item["issue_type"] == "thickness_conflict")
        assert issue["evidence_refs"]
        issue_path = f"/api/v1/package-reviews/{review['review_id']}/issues/{issue['issue_id']}"
        decision = {"status": "resolved", "expected_lock_version": review["lock_version"]}
        updated = await client.patch(issue_path, json=decision)
        updated.raise_for_status()
        stale = await client.patch(issue_path, json=decision)
        assert stale.status_code == 409
        restored = await client.patch(
            issue_path,
            json={
                "status": "pending_human",
                "expected_lock_version": updated.json()["lock_version"],
            },
        )
        restored.raise_for_status()
        latest = (await client.get(f"/api/v1/package-reviews/{review['review_id']}")).json()
        for item in latest["issues"]:
            handled = await client.patch(
                f"/api/v1/package-reviews/{review['review_id']}/issues/{item['issue_id']}",
                json={
                    "status": "resolved",
                    "reason": "SYNTHETIC验收：已核对资料差异",
                    "expected_lock_version": latest["lock_version"],
                },
            )
            handled.raise_for_status()
            latest["lock_version"] = handled.json()["lock_version"]
        approved = await client.post(
            f"/api/v1/package-reviews/{review['review_id']}/decision",
            json={
                "decision": "approved",
                "expected_lock_version": latest["lock_version"],
            },
        )
        approved.raise_for_status()
        assert approved.json()["status"] == "approved"
        terminal = await client.patch(
            issue_path, json={"status": "pending_human", "expected_lock_version": approved.json()["lock_version"]}
        )
        assert terminal.status_code == 409
        approved_id = review["review_id"]
        # Leave a new, unresolved report for the user's browser demonstration.
        pending = await client.post(
            "/api/v1/package-reviews",
            json={
                "project_id": "demo-project",
                "document_ids": documents,
                "review_mode": "full",
                "question": "核验 A-120 设计与 PTFE-502 规格的一致性及历史价格口径。",
            },
        )
        pending.raise_for_status()
        review = pending.json()
    mcp_result = {"status": "not_run"}
    if not skip_mcp:
        from scripts.validate_mcp import validate_stdio

        mcp_result = await validate_stdio()
    result = {
        "validated_at": datetime.now(UTC).isoformat(),
        "mode": "local/fake/basic",
        "api_url": base_url,
        "document_ids": documents,
        "review_id": review["review_id"],
        "approved_review_id": approved_id,
        "checks": {
            "upload_parse_index": "passed",
            "duplicate_upload": "passed",
            "retrieval_chat": "passed",
            "supervisor_subagent_tools": "passed",
            "thickness_conflict": "passed",
            "persisted_report": "passed",
            "human_issue_update": "passed",
            "stale_update_409": "passed",
            "unresolved_approval_blocked": "passed",
            "report_approval": "passed",
            "terminal_issue_update_409": "passed",
        },
        "delegation": trace,
        "issue_count": len(review["issues"]),
        "mcp_stdio": mcp_result,
        "not_validated": ["real LLM", "PostgreSQL/pgvector", "neural reranker", "Temporal recovery", "MinerU"],
    }
    output = ROOT / "data/runtime/demo-acceptance.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--skip-mcp", action="store_true")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(main(args.base_url, args.skip_mcp)), ensure_ascii=False, indent=2))
