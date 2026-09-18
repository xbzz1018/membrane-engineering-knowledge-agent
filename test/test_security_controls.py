from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from src.api import dependencies
from src.core.config import Settings
from src.core.security import Principal


def test_full_mode_rate_limiter_returns_429_after_capacity(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeRedis:
        calls = 0

        def __init__(self, **_kwargs):
            pass

        async def eval(self, *_args):
            type(self).calls += 1
            return [1, 0] if type(self).calls == 1 else [0, 0]

        async def aclose(self):
            return None

    settings = Settings(_env_file=None, RUNTIME_MODE="full", API_RATE_LIMIT_PER_MINUTE=1)
    monkeypatch.setattr(dependencies, "get_settings", lambda: settings)
    monkeypatch.setattr("redis.asyncio.Redis", FakeRedis)
    principal = Principal("user", "tester", "tenant", "reviewer")

    assert asyncio.run(dependencies.rate_limited_principal(principal)) == principal
    with pytest.raises(HTTPException) as captured:
        asyncio.run(dependencies.rate_limited_principal(principal))
    assert captured.value.status_code == 429
