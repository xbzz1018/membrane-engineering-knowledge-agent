from __future__ import annotations

import time
from collections.abc import Iterable

import jwt
from fastapi import Depends, Header, HTTPException

from src.application.authorization import ProjectAccessError, project_authorization
from src.core.config import get_settings
from src.core.security import Principal, decode_access_token
from src.infrastructure.database import storage


async def current_principal(authorization: str | None = Header(default=None)) -> Principal:
    settings = get_settings()
    if not settings.AUTH_ENABLED:
        row = await storage.get_user_by_username(settings.BOOTSTRAP_ADMIN_USERNAME)
        if not row:
            raise HTTPException(status_code=503, detail="开发管理员尚未初始化")
        return Principal(row["id"], row["username"], row["tenant_id"], row["role"])
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="缺少Bearer Token")
    try:
        principal = decode_access_token(authorization.split(" ", 1)[1])
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Token无效或已过期") from exc
    row = await storage.get_user(principal.user_id)
    if not row or not row["is_active"] or row["tenant_id"] != principal.tenant_id:
        raise HTTPException(status_code=401, detail="用户不可用")
    return principal


async def rate_limited_principal(
    principal: Principal = Depends(current_principal),
) -> Principal:
    settings = get_settings()
    if settings.RUNTIME_MODE.lower() != "full":
        return principal
    from redis.asyncio import Redis

    client = Redis(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        password=settings.REDIS_PASSWORD or None,
        db=settings.REDIS_DB,
        decode_responses=True,
    )
    script = """
    local values = redis.call('HMGET', KEYS[1], 'tokens', 'updated_ms')
    local tokens = tonumber(values[1]) or tonumber(ARGV[1])
    local updated = tonumber(values[2]) or tonumber(ARGV[3])
    local elapsed = math.max(0, tonumber(ARGV[3]) - updated)
    tokens = math.min(tonumber(ARGV[1]), tokens + elapsed * tonumber(ARGV[2]))
    local allowed = 0
    if tokens >= 1 then tokens = tokens - 1; allowed = 1 end
    redis.call('HSET', KEYS[1], 'tokens', tokens, 'updated_ms', ARGV[3])
    redis.call('PEXPIRE', KEYS[1], 120000)
    return {allowed, tokens}
    """
    try:
        capacity = settings.API_RATE_LIMIT_PER_MINUTE
        result = await client.eval(
            script,
            1,
            f"membrane:rate:{principal.tenant_id}:{principal.user_id}",
            capacity,
            capacity / 60_000,
            int(time.time() * 1000),
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail="接口限流服务不可用") from exc
    finally:
        await client.aclose()
    if not int(result[0]):
        raise HTTPException(status_code=429, detail="请求过于频繁")
    return principal


def require_global_role(principal: Principal, roles: Iterable[str]) -> None:
    if principal.role not in set(roles):
        raise HTTPException(status_code=403, detail="当前角色无权执行此操作")


async def require_project_role(
    project_id: str,
    principal: Principal,
    roles: Iterable[str] | None = None,
) -> str:
    try:
        scope = await project_authorization.authorize(principal, project_id, roles)
    except ProjectAccessError as exc:
        status_code = 404 if exc.code == "not_found" else 403
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    return scope.role
