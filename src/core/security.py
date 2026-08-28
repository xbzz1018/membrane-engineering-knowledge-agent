from __future__ import annotations

import base64
import hashlib
import hmac
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt

from src.core.config import Settings, get_settings

ROLES = frozenset({"admin", "design_engineer", "material_procurement", "reviewer"})


@dataclass(frozen=True, slots=True)
class Principal:
    user_id: str
    username: str
    tenant_id: str
    role: str


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, salt_text, digest_text = encoded.split("$", 2)
        if algorithm != "scrypt":
            return False
        salt = base64.b64decode(salt_text)
        expected = base64.b64decode(digest_text)
    except (ValueError, TypeError):
        return False
    actual = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return hmac.compare_digest(actual, expected)


def create_access_token(principal: Principal, settings: Settings | None = None) -> str:
    config = settings or get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": principal.user_id,
        "username": principal.username,
        "tenant_id": principal.tenant_id,
        "role": principal.role,
        "iat": now,
        "exp": now + timedelta(minutes=config.JWT_TTL_MINUTES),
    }
    return jwt.encode(payload, config.JWT_SECRET, algorithm=config.JWT_ALGORITHM)


def decode_access_token(token: str, settings: Settings | None = None) -> Principal:
    config = settings or get_settings()
    payload = jwt.decode(token, config.JWT_SECRET, algorithms=[config.JWT_ALGORITHM])
    role = str(payload.get("role", ""))
    if role not in ROLES:
        raise jwt.InvalidTokenError("invalid role")
    return Principal(
        user_id=str(payload["sub"]),
        username=str(payload.get("username", "")),
        tenant_id=str(payload["tenant_id"]),
        role=role,
    )
