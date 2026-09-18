from __future__ import annotations

import argparse
import json
from contextlib import asynccontextmanager
from typing import Annotated, Any, Literal

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import Elicit, Resolve
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import AnyHttpUrl, BaseModel, Field

from mcp.server import MCPServer
from src.core.config import get_settings
from src.core.security import MCP_SCOPES, MCPIdentity, Principal
from src.infrastructure.bootstrap import seed_local_data
from src.infrastructure.database import storage
from src.mcp.auth import MCPTokenVerifier, identity_from_access_token
from src.mcp.gateway import MCPGateway


class Confirmation(BaseModel):
    confirmed: bool = Field(description="用户是否确认执行该操作")


@asynccontextmanager
async def mcp_lifespan(_server: MCPServer):
    settings = get_settings()
    full_backends = None
    if settings.RUNTIME_MODE.lower() == "full":
        from src.infrastructure.full_backends import get_full_backends

        full_backends = get_full_backends()
        await full_backends.initialize()
    await storage.init()
    await seed_local_data(storage)
    try:
        yield None
    finally:
        if full_backends is not None:
            await full_backends.close()
        await storage.close()


async def _identity() -> MCPIdentity:
    access_token = get_access_token()
    if access_token is not None:
        return identity_from_access_token(access_token)
    settings = get_settings()
    row = await storage.get_user_by_username(settings.BOOTSTRAP_ADMIN_USERNAME)
    if row is None:
        raise RuntimeError("本地MCP管理员尚未初始化")
    return MCPIdentity(
        principal=Principal(row["id"], row["username"], row["tenant_id"], row["role"]),
        client_id="local-stdio",
        scopes=MCP_SCOPES,
    )


def _confirm_create_review(
    project_id: str, document_ids: list[str], review_mode: str,
) -> Elicit[Confirmation]:
    return Elicit(
        f"确认在项目 {project_id} 发起 {review_mode} 资料审查？资料数量：{len(document_ids)}。",
        Confirmation,
    )


def _confirm_cancel_review(review_id: str) -> Elicit[Confirmation]:
    return Elicit(f"确认取消审查 {review_id}？", Confirmation)


def _confirm_approve_review(review_id: str) -> Elicit[Confirmation]:
    return Elicit(f"确认批准审查 {review_id}？", Confirmation)


def _confirm_reject_review(review_id: str, reason: str) -> Elicit[Confirmation]:
    return Elicit(f"确认退回审查 {review_id}？原因：{reason[:200]}", Confirmation)


def create_mcp_server(*, authenticated: bool, allow_write: bool) -> MCPServer:
    settings = get_settings()
    auth: dict[str, Any] = {}
    if authenticated:
        auth = {
            "token_verifier": MCPTokenVerifier(),
            "auth": AuthSettings(
                issuer_url=AnyHttpUrl(settings.MCP_ISSUER_URL),
                resource_server_url=AnyHttpUrl(settings.MCP_RESOURCE_SERVER_URL),
                required_scopes=[],
            ),
        }
    server = MCPServer(
        name="membrane-engineering",
        title="膜结构企业资料智能审查平台",
        version="2.0.0",
        instructions="通过项目权限访问公开工程资料，并受控发起或处理三领域资料审查。",
        lifespan=mcp_lifespan,
        **auth,
    )
    gateway = MCPGateway()

    @server.tool()
    async def search_project_documents(project_id: str, query: str, limit: int = 8) -> dict[str, Any]:
        """检索已授权项目的公开文档Evidence，返回文件、位置、版本和受限长度摘要。"""
        return await gateway.search_project_documents(await _identity(), project_id, query, limit)

    @server.tool()
    async def query_material_specs(project_id: str, query: str, limit: int = 8) -> dict[str, Any]:
        """查询当前企业公开膜材型号、规格、性能、来源和版本。"""
        return await gateway.query_material_specs(await _identity(), project_id, query, limit)

    @server.tool()
    async def query_price_records(project_id: str, query: str, limit: int = 8) -> dict[str, Any]:
        """查询项目可见的公开历史测试价格，始终返回synthetic标记和免责声明。"""
        return await gateway.query_price_records(await _identity(), project_id, query, limit)

    @server.tool()
    async def get_document_evidence(document_id: str, limit: int = 20) -> dict[str, Any]:
        """按文档ID分页读取公开Evidence定位和受限长度正文。"""
        return await gateway.get_document_evidence(await _identity(), document_id, limit)

    @server.tool()
    async def get_review_status(review_id: str) -> dict[str, Any]:
        """查询资料包审查进度、领域状态、问题数量、锁版本和人工审批状态。"""
        return await gateway.get_review_status(await _identity(), review_id)

    @server.resource(
        "membrane://documents/{document_id}",
        name="document-metadata",
        description="读取公开工程资料的版本、解析器、分级和状态元数据。",
        mime_type="application/json",
    )
    async def document_resource(document_id: str) -> str:
        return json.dumps(
            await gateway.get_document_resource(await _identity(), document_id),
            ensure_ascii=False,
            default=str,
        )

    @server.resource(
        "membrane://documents/{document_id}/evidence/{evidence_id}",
        name="document-evidence",
        description="读取一条公开Evidence的稳定定位和受限长度摘要。",
        mime_type="application/json",
    )
    async def evidence_resource(document_id: str, evidence_id: str) -> str:
        return json.dumps(
            await gateway.get_evidence_resource(await _identity(), document_id, evidence_id),
            ensure_ascii=False,
            default=str,
        )

    @server.resource(
        "membrane://reviews/{review_id}/report",
        name="review-report",
        description="读取仅包含公开资料的审查报告、问题单和证据引用。",
        mime_type="application/json",
    )
    async def review_report_resource(review_id: str) -> str:
        return json.dumps(
            await gateway.get_review_report_resource(await _identity(), review_id),
            ensure_ascii=False,
            default=str,
        )

    if allow_write:
        @server.tool()
        async def create_review_request(
            project_id: str,
            document_ids: list[str],
            question: str,
            idempotency_key: str,
            review_mode: Literal["full", "focused"] = "full",
            confirmation: Annotated[Confirmation, Resolve(_confirm_create_review)] = Confirmation(confirmed=False),
        ) -> dict[str, Any]:
            """经用户确认后启动三领域或专项资料包审查，并返回review_id与workflow_id。"""
            if not confirmation.confirmed:
                return {"status": "confirmation_declined", "side_effect": False}
            return await gateway.create_review_request(
                await _identity(), project_id, document_ids, question, review_mode, idempotency_key,
            )

        @server.tool()
        async def cancel_review_request(
            review_id: str,
            reason: str,
            idempotency_key: str,
            confirmation: Annotated[Confirmation, Resolve(_confirm_cancel_review)],
        ) -> dict[str, Any]:
            """经用户确认后取消本人发起的未完成审查；管理员可取消项目内任务。"""
            if not confirmation.confirmed:
                return {"status": "confirmation_declined", "side_effect": False}
            return await gateway.cancel_review_request(await _identity(), review_id, reason, idempotency_key)

        @server.tool()
        async def approve_review_request(
            review_id: str,
            expected_lock_version: int,
            idempotency_key: str,
            confirmation: Annotated[Confirmation, Resolve(_confirm_approve_review)],
        ) -> dict[str, Any]:
            """审核人经明确确认后批准审查；最终状态需再次查询。"""
            if not confirmation.confirmed:
                return {"status": "confirmation_declined", "side_effect": False}
            return await gateway.decide_review_request(
                await _identity(), review_id, "approved", expected_lock_version, "", idempotency_key,
            )

        @server.tool()
        async def reject_review_request(
            review_id: str,
            reason: str,
            expected_lock_version: int,
            idempotency_key: str,
            confirmation: Annotated[Confirmation, Resolve(_confirm_reject_review)],
        ) -> dict[str, Any]:
            """审核人经明确确认后退回审查并记录原因；最终状态需再次查询。"""
            if not confirmation.confirmed:
                return {"status": "confirmation_declined", "side_effect": False}
            return await gateway.decide_review_request(
                await _identity(), review_id, "rejected", expected_lock_version, reason, idempotency_key,
            )

    return server


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the membrane engineering MCP gateway")
    parser.add_argument("--transport", choices=("stdio", "streamable-http"), default="stdio")
    args = parser.parse_args()
    is_http = args.transport == "streamable-http"
    server = create_mcp_server(authenticated=is_http, allow_write=is_http)
    if is_http:
        settings = get_settings()
        server.run(
            transport="streamable-http",
            host=settings.MCP_HOST,
            port=settings.MCP_PORT,
            streamable_http_path="/mcp",
            json_response=False,
            stateless_http=True,
            transport_security=TransportSecuritySettings(
                enable_dns_rebinding_protection=True,
                allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*"],
                allowed_origins=[
                    item.strip() for item in settings.MCP_ALLOWED_ORIGINS.split(",") if item.strip()
                ],
            ),
        )
    else:
        server.run(transport="stdio")


if __name__ == "__main__":
    main()
