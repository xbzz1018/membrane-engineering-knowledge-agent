"""Check exact document constraints through HTTP, LangChain tool and MCP stdio."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


async def main():
    from mcp import Client, StdioServerParameters
    from src.agents.knowledge_agent import KnowledgeAgent
    from src.core.security import Principal
    from src.infrastructure.database import storage

    async with httpx.AsyncClient(base_url="http://127.0.0.1:8080", timeout=60, trust_env=False) as client:
        project_response = await client.post("/api/v1/projects", json={"name": "SYNTHETIC-exact-" + uuid.uuid4().hex[:8]})
        project_response.raise_for_status()
        project = project_response.json()["id"]
        ids = []
        for model in ("PTFE-502", "PTFE-5020"):
            upload = await client.post("/api/v1/documents/upload", data={"project_id": project},
                files={"file": (model + ".txt", f"SYNTHETIC material spec {model} 0.8mm".encode(), "text/plain")})
            upload.raise_for_status()
            did = upload.json()["document_id"]
            ids.append(did)
            (await client.post(f"/api/v1/documents/{did}/index")).raise_for_status()
            doc = (await client.get(f"/api/v1/documents/{did}")).json()
            declaration = await client.put(f"/api/v1/documents/{did}/business-metadata", json={
                "engineering_model": model, "applicable_revision": "R1", "document_type": "material",
                "effective_from": "2026-01-01", "effective_to": "2026-12-31",
                "source_note": "SYNTHETIC fixture, uploader declaration", "expected_lock_version": doc["lock_version"],
            })
            declaration.raise_for_status()
        filters = {"engineering_model": "PTFE-502", "applicable_revision": "R1", "effective_on": "2026-11-02"}
        arguments = {"project_id": project, "query": "spec", "limit": 8, "filters": filters}
        response = await client.post("/api/v1/documents/search", json=arguments)
        response.raise_for_status()

    def assert_exact(payload):
        assert {row["evidence_id"].split(":")[0] for row in payload["evidence"]} == {ids[0]}, payload
        assert payload["applied_filters"] == filters

    assert_exact(response.json())
    await storage.init()
    try:
        admin = await storage.get_user_by_username("admin")
        principal = Principal(admin["id"], admin["username"], admin["tenant_id"], admin["role"])
        tool = KnowledgeAgent()._tools(principal, project)[0]
        tool_result = await tool.ainvoke({"query": "spec", "filters": filters})
        assert_exact(json.loads(tool_result))
    finally:
        await storage.close()
    parameters = StdioServerParameters(command=sys.executable,
        args=["-m", "src.mcp.server", "--transport", "stdio"], cwd=str(ROOT),
        env={key: os.environ[key] for key in (
            "RUNTIME_MODE", "MODEL_MODE", "MODEL_PROVIDER", "PARSER_MODE", "TEMPORAL_ENABLED", "AUTH_ENABLED",
            "LOCAL_DB_PATH", "DATABASE_URL",
        )},
    )
    async with Client(parameters) as mcp:
        result = await mcp.call_tool("search_project_documents", arguments)
        assert not result.is_error
        assert_exact(result.structured_content)
        absent = await mcp.call_tool("search_project_documents", {
            **arguments, "filters": {**filters, "engineering_model": "PTFE-NO-ANSWER"},
        })
        assert not absent.is_error and absent.structured_content["evidence"] == []
    record = {"validated_at": datetime.now(UTC).isoformat(), "mode": "local/fake/basic",
        "project_id": project, "document_ids": ids, "checks": {
            "http_exact_filter": "passed", "langchain_tool_filter": "passed", "mcp_stdio_filter": "passed",
            "near_model_excluded": "passed", "mcp_no_answer": "passed",
        }, "not_validated": ["PostgreSQL execution", "real vector embeddings", "Temporal server"]}
    path = ROOT / "data/runtime/resume-slice-acceptance.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(record, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    os.environ.update(RUNTIME_MODE="local", MODEL_MODE="fake", MODEL_PROVIDER="fake", PARSER_MODE="basic",
        TEMPORAL_ENABLED="false", AUTH_ENABLED="false", LOCAL_DB_PATH=str(ROOT / "data/runtime/demo.db"), DATABASE_URL="")
    asyncio.run(main())
