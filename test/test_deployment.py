"""Deployment gates must fail before a weak/mismatched configuration is started."""

from __future__ import annotations

import os

import pytest

from deploy.entrypoint import validate_configuration
from scripts.init_deployment import SECRET_KEYS, initialize
from src.core.config import Settings


def deployed(**changes):
    values = {
        "RUNTIME_MODE": "full", "AUTH_ENABLED": True, "TEMPORAL_ENABLED": True,
        "APP_DEBUG": False, "TRACE_CONTENT": False, "MODEL_MODE": "fake", "MODEL_PROVIDER": "fake",
        "EMBEDDING_MODEL": "demo-hash-1024", "EMBEDDING_DIMENSIONS": 1024, "PARSER_MODE": "mineru",
        "JWT_SECRET": "a" * 48, "BOOTSTRAP_ADMIN_PASSWORD": "b" * 48, "DB_PASSWORD": "c" * 48,
        "REDIS_PASSWORD": "d" * 48, "MINIO_SECRET_KEY": "e" * 48,
        "RERANKER_ENABLED": False,
    }
    values.update(changes)
    return Settings(_env_file=None, **values)


def test_random_credentials_and_existing_config_preserved(tmp_path):
    target = initialize(tmp_path / ".env")
    content = target.read_text(encoding="utf-8")
    pairs = dict(line.split("=", 1) for line in content.splitlines() if "=" in line and not line.startswith("#"))
    secrets = [pairs[key] for key in SECRET_KEYS]
    assert len(set(secrets)) == len(SECRET_KEYS) and all(len(value) == 48 for value in secrets)
    if os.name != "nt":
        assert target.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        initialize(target)
    assert target.read_text(encoding="utf-8") == content


@pytest.mark.parametrize("changes", [
    {"AUTH_ENABLED": False}, {"TEMPORAL_ENABLED": False}, {"RUNTIME_MODE": "local"},
    {"APP_DEBUG": True}, {"TRACE_CONTENT": True}, {"EMBEDDING_DIMENSIONS": 768},
    {"JWT_SECRET": "local-development-only-change-me"}, {"BOOTSTRAP_ADMIN_PASSWORD": "admin-change-me"},
    {"DB_PASSWORD": "engineering123"}, {"REDIS_PASSWORD": ""}, {"MINIO_SECRET_KEY": "minioadmin"},
    {"EMBEDDING_MODEL": "real-model"}, {"PARSER_MODE": "basic"},
    {"RERANKER_ENABLED": True, "RERANKER_API_KEY": "", "RERANKER_API_BASE": ""},
    {"MODEL_MODE": "api", "MODEL_PROVIDER": "fake"},
])
def test_unsafe_or_mismatched_config_rejected(changes):
    with pytest.raises((ValueError, RuntimeError)):
        validate_configuration(deployed(**changes))


def test_api_mode_requires_real_embedding_namespace_and_credentials():
    api = {"MODEL_MODE": "api", "MODEL_PROVIDER": "gateway", "GATEWAY_API_KEY": "synthetic-test-key",
           "GATEWAY_API_BASE": "http://gateway.invalid/v1", "GATEWAY_MODEL": "test-chat",
           "EMBEDDING_PROVIDER": "embedding", "EMBEDDING_API_BASE": "http://embedding.invalid/v1",
           "EMBEDDING_API_KEY": "synthetic-test-key"}
    with pytest.raises(ValueError, match="actual model name"):
        validate_configuration(deployed(**api))
    validate_configuration(deployed(**api, EMBEDDING_MODEL="test-real-1024"))
    with pytest.raises(RuntimeError, match="embedding provider"):
        validate_configuration(deployed(**{**api, "EMBEDDING_MODEL": "test-real-1024", "EMBEDDING_API_KEY": ""}))


def test_valid_fake_is_explicitly_separate():
    validate_configuration(deployed())
