"""Validate that the active interpreter is a complete project environment."""

from __future__ import annotations

import importlib.util
import sys

REQUIRED = (
    "fastapi",
    "langchain",
    "langgraph",
    "temporalio",
    "pgvector",
    "minio",
    "redis",
    "pymupdf",
    "openpyxl",
    "docx",
    "pytest",
    "ruff",
    "mcp",
)


def main() -> int:
    missing = [name for name in REQUIRED if importlib.util.find_spec(name) is None]
    print(f"executable={sys.executable}")
    print(f"prefix={sys.prefix}")
    print(f"python={sys.version.split()[0]}")
    if missing:
        print(f"missing packages: {', '.join(missing)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
