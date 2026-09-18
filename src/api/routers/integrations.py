from __future__ import annotations

from importlib.metadata import version

import httpx
from fastapi import APIRouter, Depends

from src.api.dependencies import current_principal
from src.core.config import get_settings
from src.core.security import Principal

router = APIRouter(prefix="/api/v1/integrations", tags=["外部AI集成"])


@router.get("/mcp", summary="查看MCP外部接入状态")
async def mcp_integration_status(principal: Principal = Depends(current_principal)) -> dict:
    settings = get_settings()
    healthy = False
    status_code = 0
    try:
        async with httpx.AsyncClient(timeout=settings.HEALTHCHECK_TIMEOUT_SECONDS) as client:
            response = await client.post(settings.MCP_RESOURCE_SERVER_URL, json={})
            status_code = response.status_code
            healthy = status_code in {200, 400, 401, 403, 406, 415}
    except Exception:
        pass
    return {
        "enabled": settings.MCP_ENABLED,
        "healthy": healthy,
        "endpoint": settings.MCP_RESOURCE_SERVER_URL,
        "sdk_version": version("mcp"),
        "transport": "streamable-http",
        "tools": 9,
        "resources": 3,
        "public_only": True,
        "status_code": status_code,
    }
