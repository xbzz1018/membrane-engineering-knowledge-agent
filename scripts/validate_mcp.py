"""Validate MCP v2 discovery, resources, tools, auth, MRTR elicitation, and idempotency."""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx
import httpx2
import mcp.types as types
from mcp.client.streamable_http import streamable_http_client

from mcp import Client, StdioServerParameters

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core.config import get_settings

QUERY_TOOLS = {
    "search_project_documents",
    "query_material_specs",
    "query_price_records",
    "get_document_evidence",
    "get_review_status",
}
WRITE_TOOLS = {
    "create_review_request",
    "cancel_review_request",
    "approve_review_request",
    "reject_review_request",
}
RESOURCE_TEMPLATES = {
    "membrane://documents/{document_id}",
    "membrane://documents/{document_id}/evidence/{evidence_id}",
    "membrane://reviews/{review_id}/report",
}


async def validate_stdio() -> dict:
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "src.mcp.server", "--transport", "stdio"],
        cwd=str(Path(__file__).resolve().parents[1]),
    )
    async with Client(parameters) as client:
        tools = await client.list_tools()
        names = {item.name for item in tools.tools}
        if names != QUERY_TOOLS:
            raise AssertionError(f"stdio tool boundary mismatch: {sorted(names)}")
        templates = await client.list_resource_templates()
        if {item.uri_template for item in templates.resource_templates} != RESOURCE_TEMPLATES:
            raise AssertionError("stdio resource template boundary mismatch")
        result = await client.call_tool(
            "query_material_specs",
            {"project_id": get_settings().DEFAULT_PROJECT_ID, "query": "Precontraint 502", "limit": 2},
        )
        if result.is_error or not result.structured_content:
            raise AssertionError("stdio material tool returned no structured content")
        return {
            "protocol": client.protocol_version,
            "tools": len(names),
            "resources": len(templates.resource_templates),
            "material_query": "ok",
        }


async def _accepted_elicitation(_context, _params) -> types.ElicitResult:
    return types.ElicitResult(action="accept", content={"confirmed": True})


async def validate_http() -> dict:
    settings = get_settings()
    validation_id = uuid.uuid4().hex
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8080", timeout=30) as api:
        login = await api.post("/api/v1/auth/login", json={
            "username": settings.BOOTSTRAP_ADMIN_USERNAME,
            "password": settings.BOOTSTRAP_ADMIN_PASSWORD,
        })
        login.raise_for_status()
        api_token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {api_token}"}
        exchange = await api.post("/api/v1/auth/mcp-token", headers=headers, json={"scopes": []})
        exchange.raise_for_status()
        token = exchange.json()["access_token"]
        documents = await api.get(
            "/api/v1/documents", headers=headers, params={"project_id": settings.DEFAULT_PROJECT_ID},
        )
        documents.raise_for_status()
        eligible = [
            item for item in documents.json()
            if item["status"] == "indexed" and item["data_classification"] == "public"
        ]
        if not eligible:
            raise AssertionError("MCP validation needs one indexed public document")
        document_id = eligible[0]["id"]
        evidence_response = await api.get(f"/api/v1/documents/{document_id}/evidence", headers=headers)
        evidence_response.raise_for_status()
        if not evidence_response.json():
            raise AssertionError("MCP validation needs one public EvidenceUnit")
        evidence_id = evidence_response.json()[0]["id"]

    async with httpx.AsyncClient(timeout=10) as origin_client:
        invalid_origin = await origin_client.post(
            settings.MCP_RESOURCE_SERVER_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Origin": "https://invalid-origin.example",
                "Content-Type": "application/json",
            },
            json={},
        )
    if invalid_origin.status_code != 403:
        raise AssertionError(f"MCP accepted invalid Origin: {invalid_origin.status_code}")

    async with httpx.AsyncClient(timeout=10) as unauthenticated_client:
        unauthenticated = await unauthenticated_client.post(
            settings.MCP_RESOURCE_SERVER_URL,
            headers={"Content-Type": "application/json"},
            json={},
        )
    if unauthenticated.status_code != 401:
        raise AssertionError(f"MCP endpoint accepted unauthenticated request: {unauthenticated.status_code}")

    mcp_headers = {"Authorization": f"Bearer {token}"}
    async with httpx2.AsyncClient(headers=mcp_headers, timeout=120) as raw_client:
        transport = streamable_http_client(settings.MCP_RESOURCE_SERVER_URL, http_client=raw_client)
        async with Client(transport, mode="2026-07-28") as client:
            tools = await client.list_tools()
            names = {item.name for item in tools.tools}
            if names != QUERY_TOOLS | WRITE_TOOLS:
                raise AssertionError(f"HTTP tool boundary mismatch: {sorted(names)}")
            templates = await client.list_resource_templates()
            if {item.uri_template for item in templates.resource_templates} != RESOURCE_TEMPLATES:
                raise AssertionError("HTTP resource template boundary mismatch")
            resource = await client.read_resource(f"membrane://documents/{document_id}")
            evidence = await client.read_resource(
                f"membrane://documents/{document_id}/evidence/{evidence_id}"
            )
            if not resource.contents or not evidence.contents:
                raise AssertionError("MCP public resources returned no content")
            result = await client.call_tool(
                "query_material_specs",
                {"project_id": settings.DEFAULT_PROJECT_ID, "query": "Precontraint 502", "limit": 2},
            )
            if result.is_error or not result.structured_content:
                raise AssertionError("HTTP material tool returned no structured content")
            try:
                await client.call_tool("create_review_request", {
                    "project_id": settings.DEFAULT_PROJECT_ID,
                    "document_ids": [document_id],
                    "question": "审查公开资料",
                    "review_mode": "full",
                    "idempotency_key": f"mcp-v2-no-elicitation-{validation_id}",
                })
            except Exception:
                pass
            else:
                raise AssertionError("write tool did not fail closed without elicitation capability")

    async with httpx2.AsyncClient(headers=mcp_headers, timeout=120) as raw_client:
        transport = streamable_http_client(settings.MCP_RESOURCE_SERVER_URL, http_client=raw_client)
        async with Client(
            transport,
            mode="2026-07-28",
            elicitation_callback=_accepted_elicitation,
        ) as client:
            arguments = {
                "project_id": settings.DEFAULT_PROJECT_ID,
                "document_ids": [document_id],
                "question": "审查公开资料",
                "review_mode": "full",
                "idempotency_key": f"mcp-v2-create-{validation_id}",
            }
            created = await client.call_tool("create_review_request", arguments)
            if created.is_error or not created.structured_content.get("review_id"):
                raise AssertionError("confirmed MCP review creation failed")
            review_id = created.structured_content["review_id"]
            replay = await client.call_tool("create_review_request", arguments)
            if replay.structured_content.get("idempotent_replay") is not True:
                raise AssertionError("MCP create idempotency did not replay")
            report = await client.read_resource(f"membrane://reviews/{review_id}/report")
            if not report.contents:
                raise AssertionError("MCP review report resource returned no content")
            cancelled = await client.call_tool("cancel_review_request", {
                "review_id": review_id,
                "reason": "MCP v2验收清理",
                "idempotency_key": f"mcp-v2-cancel-{validation_id}",
            })
            if cancelled.is_error:
                raise AssertionError("confirmed MCP cancellation failed")
            return {
                "protocol": client.protocol_version,
                "tools": len(names),
                "resources": len(RESOURCE_TEMPLATES),
                "authenticated_query": "ok",
                "unauthenticated": 401,
                "invalid_origin": 403,
                "elicitation_fail_closed": "ok",
                "create_idempotency": "ok",
                "cancel": "requested",
            }


async def main() -> None:
    summary = {"stdio": await validate_stdio(), "streamable_http": await validate_http()}
    summary["validated_at"] = datetime.now(UTC).isoformat()
    summary["runtime_mode"] = get_settings().RUNTIME_MODE
    summary["model_mode"] = get_settings().MODEL_MODE
    summary["temporal_enabled"] = get_settings().TEMPORAL_ENABLED
    output = Path(__file__).resolve().parents[1] / "data/runtime/mcp-validation" / (
        datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    )
    output.mkdir(parents=True)
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
