from __future__ import annotations

import os
import uuid
from pathlib import Path

TEST_DB = Path(f"data/runtime/pytest-enterprise-{os.getpid()}-{uuid.uuid4().hex}.db").resolve()

# Unit and API tests must not inherit a developer's Full/Temporal/API switches.
os.environ.update({
    "RUNTIME_MODE": "local",
    "MODEL_MODE": "fake",
    "PARSER_MODE": "basic",
    "TEMPORAL_ENABLED": "false",
    "AUTH_ENABLED": "false",
    "LOCAL_DB_PATH": str(TEST_DB),
})


def pytest_sessionfinish() -> None:
    TEST_DB.unlink(missing_ok=True)
