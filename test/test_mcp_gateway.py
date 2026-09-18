from __future__ import annotations

import asyncio
from types import SimpleNamespace

import jwt
import pytest

from src.core.config import Settings
from src.core.security import (
    MCPIdentity,
    Principal,
    create_mcp_access_token,
    decode_mcp_access_token,
)
from src.mcp.gateway import MCPGateway, MCPGatewayError
from src.mcp.server import create_mcp_server


def run(coro):
    return asyncio.run(coro)


def test_mcp_transport_profiles_expose_expected_tools() -> None:
    stdio = create_mcp_server(authenticated=False, allow_write=False)
    http = create_mcp_server(authenticated=True, allow_write=True)
    stdio_names = {item.name for item in run(stdio.list_tools())}
    http_names = {item.name for item in run(http.list_tools())}

    assert stdio_names == {
        "search_project_documents",
        "query_material_specs",
        "query_price_records",
        "get_document_evidence",
        "get_review_status",
    }
    assert http_names == stdio_names | {
        "create_review_request",
        "cancel_review_request",
        "approve_review_request",
        "reject_review_request",
    }
    resources = {item.uri_template for item in run(http.list_resource_templates())}
    assert resources == {
        "membrane://documents/{document_id}",
        "membrane://documents/{document_id}/evidence/{evidence_id}",
        "membrane://reviews/{review_id}/report",
    }
    create_tool = next(item for item in run(http.list_tools()) if item.name == "create_review_request")
    assert "confirmation" not in create_tool.input_schema["properties"]


def test_mcp_token_has_audience_and_role_limited_scopes() -> None:
    settings = Settings(
        _env_file=None,
        JWT_SECRET="test-secret-with-enough-entropy-32-bytes",
        MCP_AUDIENCE="membrane-mcp-test",
    )
    principal = Principal("user", "designer", "tenant", "design_engineer")
    token, scopes = create_mcp_access_token(principal, {"documents:read", "reviews:create"}, settings)
    identity = decode_mcp_access_token(token, settings)

    assert identity.principal == principal
    assert identity.scopes == scopes
    with pytest.raises(jwt.InvalidAudienceError):
        decode_mcp_access_token(token, Settings(
            _env_file=None,
            JWT_SECRET=settings.JWT_SECRET,
            MCP_AUDIENCE="another-audience",
        ))
    with pytest.raises(ValueError, match="exceed"):
        create_mcp_access_token(principal, {"prices:read"}, settings)


class FakeStore:
    def __init__(self):
        self.idempotency: dict[tuple[str, str], dict] = {}
        self.audits: list[dict] = []

    async def start_mcp_tool_call(self, **kwargs):
        self.audits.append({"start": kwargs})
        return f"call-{len(self.audits)}"

    async def finish_mcp_tool_call(self, call_id, **kwargs):
        self.audits.append({"finish": {"call_id": call_id, **kwargs}})

    async def get_mcp_idempotency(self, *, tool_name, idempotency_key, **_kwargs):
        return self.idempotency.get((tool_name, idempotency_key))

    async def save_mcp_idempotency(
        self,
        *,
        tool_name,
        idempotency_key,
        request_hash,
        result_payload,
        result_ref,
        status,
        **_kwargs,
    ):
        self.idempotency[(tool_name, idempotency_key)] = {
            "request_hash": request_hash,
            "result_payload": result_payload,
            "result_ref": result_ref,
            "status": status,
        }

    async def get_document(self, _document_id):
        return None

    async def get_package_review(self, _review_id):
        return None


class FakeReviews:
    def __init__(self):
        self.starts = 0

    async def start(self, request, _principal, *, review_id, public_only=False):
        self.starts += 1
        assert public_only is True
        return {
            "review_id": review_id,
            "status": "queued",
            "workflow": {"workflow_id": f"package-review:{review_id}"},
            "review_mode": request.review_mode,
        }


def test_mcp_create_review_is_idempotent_and_rejects_key_reuse() -> None:
    store = FakeStore()
    reviews = FakeReviews()
    gateway = MCPGateway(store=store, knowledge=SimpleNamespace(), reviews=reviews)
    identity = MCPIdentity(
        Principal("user", "reviewer", "tenant", "reviewer"),
        "client",
        frozenset({"reviews:create"}),
    )
    arguments = (identity, "project", ["doc-1"], "审查资料", "full", "key-1")
    first = run(gateway.create_review_request(*arguments))
    second = run(gateway.create_review_request(*arguments))

    assert reviews.starts == 1
    assert first["review_id"] == second["review_id"]
    assert second["idempotent_replay"] is True
    with pytest.raises(MCPGatewayError, match="不同请求"):
        run(gateway.create_review_request(
            identity, "project", ["doc-2"], "另一请求", "full", "key-1",
        ))


def test_mcp_concurrent_create_runs_side_effect_once() -> None:
    store = FakeStore()
    reviews = FakeReviews()
    gateway = MCPGateway(store=store, knowledge=SimpleNamespace(), reviews=reviews)
    identity = MCPIdentity(
        Principal("user", "reviewer", "tenant", "reviewer"),
        "client",
        frozenset({"reviews:create"}),
    )

    async def concurrent():
        arguments = (identity, "project", ["doc-1"], "审查资料", "full", "same-key")
        return await asyncio.gather(
            gateway.create_review_request(*arguments),
            gateway.create_review_request(*arguments),
        )

    first, second = run(concurrent())
    assert reviews.starts == 1
    assert first["review_id"] == second["review_id"]
    assert sum(bool(item.get("idempotent_replay")) for item in (first, second)) == 1


def test_mcp_scope_prevents_design_role_from_querying_prices() -> None:
    gateway = MCPGateway(store=FakeStore(), knowledge=SimpleNamespace(), reviews=FakeReviews())
    identity = MCPIdentity(
        Principal("user", "designer", "tenant", "design_engineer"),
        "client",
        frozenset({"documents:read"}),
    )
    with pytest.raises(MCPGatewayError, match="prices:read"):
        run(gateway.query_price_records(identity, "project", "PTFE"))

