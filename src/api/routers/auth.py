from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from src.api.dependencies import current_principal, require_global_role
from src.core.config import get_settings
from src.core.security import (
    MCP_SCOPES,
    ROLES,
    Principal,
    create_access_token,
    create_mcp_access_token,
    hash_password,
    verify_password,
)
from src.infrastructure.database import storage

router = APIRouter(prefix="/api/v1/auth", tags=["身份与用户"])


class LoginRequest(BaseModel):
    model_config = ConfigDict(title="登录请求")
    username: str = Field(min_length=1, max_length=128, description="企业用户名")
    password: str = Field(min_length=8, max_length=256, description="登录密码")


class CreateUserRequest(LoginRequest):
    model_config = ConfigDict(title="创建企业用户请求")
    role: str = Field(description="全局角色：admin/design_engineer/material_procurement/reviewer")


class MCPTokenRequest(BaseModel):
    model_config = ConfigDict(title="MCP短期令牌请求")
    scopes: list[str] = Field(default_factory=list, description="留空时使用当前角色允许的全部MCP Scope")


@router.post("/login", summary="使用用户名和密码登录")
async def login(request: LoginRequest) -> dict:
    row = await storage.get_user_by_username(request.username)
    if not row or not row["is_active"] or not verify_password(request.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    principal = Principal(row["id"], row["username"], row["tenant_id"], row["role"])
    return {
        "access_token": create_access_token(principal),
        "token_type": "bearer",
        "principal": {
            "user_id": principal.user_id,
            "username": principal.username,
            "tenant_id": principal.tenant_id,
            "role": principal.role,
        },
    }


@router.get("/me", summary="查看当前登录身份")
async def me(principal: Principal = Depends(current_principal)) -> dict:
    return {
        "user_id": principal.user_id,
        "username": principal.username,
        "tenant_id": principal.tenant_id,
        "role": principal.role,
    }


@router.post("/mcp-token", summary="换取外部Agent使用的短期MCP令牌")
async def mcp_token(
    request: MCPTokenRequest,
    principal: Principal = Depends(current_principal),
) -> dict:
    requested = set(request.scopes)
    if requested - MCP_SCOPES:
        raise HTTPException(status_code=422, detail="包含未知MCP Scope")
    try:
        token, scopes = create_mcp_access_token(principal, requested or None)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {
        "access_token": token,
        "token_type": "bearer",
        "audience": "membrane-mcp",
        "expires_in": get_settings().MCP_TOKEN_TTL_MINUTES * 60,
        "scopes": sorted(scopes),
    }


@router.post("/users", status_code=201, summary="管理员创建企业用户")
async def create_user(
    request: CreateUserRequest,
    principal: Principal = Depends(current_principal),
) -> dict:
    require_global_role(principal, {"admin"})
    if request.role not in ROLES:
        raise HTTPException(status_code=422, detail="不支持的角色")
    if await storage.get_user_by_username(request.username):
        raise HTTPException(status_code=409, detail="用户名已存在")
    row = await storage.create_user(request.username, hash_password(request.password), request.role)
    return {"user_id": row["id"], "username": row["username"], "role": row["role"]}


@router.get("/users", summary="管理员查看企业用户列表")
async def list_users(principal: Principal = Depends(current_principal)) -> list[dict]:
    require_global_role(principal, {"admin"})
    return await storage.list_users(principal.tenant_id)
