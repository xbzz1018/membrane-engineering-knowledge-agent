from __future__ import annotations

import jwt
from mcp.server.auth.provider import AccessToken, TokenVerifier

from src.core.config import get_settings
from src.core.security import MCPIdentity, Principal, decode_mcp_access_token
from src.infrastructure.database import storage


class MCPTokenVerifier(TokenVerifier):
    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            identity = decode_mcp_access_token(token)
        except jwt.PyJWTError:
            return None
        row = await storage.get_user(identity.principal.user_id)
        if not row or not row["is_active"] or row["tenant_id"] != identity.principal.tenant_id:
            return None
        return AccessToken(
            token=token,
            client_id=identity.client_id,
            scopes=sorted(identity.scopes),
            subject=identity.principal.user_id,
            resource=get_settings().MCP_AUDIENCE,
            claims={
                "username": identity.principal.username,
                "tenant_id": identity.principal.tenant_id,
                "role": identity.principal.role,
            },
        )


def identity_from_access_token(access_token: AccessToken) -> MCPIdentity:
    claims = access_token.claims or {}
    return MCPIdentity(
        principal=Principal(
            user_id=str(access_token.subject or ""),
            username=str(claims.get("username", "")),
            tenant_id=str(claims.get("tenant_id", "")),
            role=str(claims.get("role", "")),
        ),
        client_id=access_token.client_id,
        scopes=frozenset(access_token.scopes),
    )
