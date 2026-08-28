from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.api.dependencies import current_principal, require_global_role
from src.core.security import ROLES, Principal, create_access_token, hash_password, verify_password
from src.engineering.storage import storage

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=8, max_length=256)


class CreateUserRequest(LoginRequest):
    role: str


@router.post("/login")
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


@router.get("/me")
async def me(principal: Principal = Depends(current_principal)) -> dict:
    return {
        "user_id": principal.user_id,
        "username": principal.username,
        "tenant_id": principal.tenant_id,
        "role": principal.role,
    }


@router.post("/users", status_code=201)
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
