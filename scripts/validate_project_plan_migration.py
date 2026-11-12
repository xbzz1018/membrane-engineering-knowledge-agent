"""Exercise 0017 on an isolated Local pre-0017 schema; not the PG-only full chain."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


async def main():
    output = ROOT / "data/runtime/project-plan-migrations" / uuid.uuid4().hex
    output.mkdir(parents=True)
    os.environ.update(RUNTIME_MODE="local", MODEL_MODE="fake", DATABASE_URL="", LOCAL_DB_PATH=str(output / "isolated.db"))
    from sqlalchemy import inspect

    from src.infrastructure.database import engine, metadata

    names = [name for name in metadata.tables if name.startswith("project_plan")]
    async with engine.begin() as connection:
        await connection.run_sync(lambda bind: metadata.create_all(bind, tables=[
            table for name, table in metadata.tables.items() if name not in names
        ]))
    await engine.dispose()
    commands = [["stamp", "0016_document_ingest_claims"], ["upgrade", "head"],
                ["downgrade", "0016_document_ingest_claims"], ["upgrade", "head"]]
    results = []
    for index, command in enumerate(commands):
        result = await asyncio.to_thread(subprocess.run, [sys.executable, "-m", "alembic", *command],
                                         cwd=ROOT, env=os.environ.copy(), capture_output=True, text=True, encoding="utf-8")
        (output / f"step-{index}.log").write_text(result.stdout + result.stderr, encoding="utf-8")
        if result.returncode:
            raise RuntimeError("isolated migration failed; inspect " + str(output))
        async with engine.connect() as connection:
            actual = await connection.run_sync(lambda bind: inspect(bind).get_table_names())
        present = sorted(set(names) & set(actual))
        expected = sorted(names) if command[0] == "upgrade" else []
        assert present == expected
        results.append({"command": command, "exit_code": result.returncode, "proposal_tables": present})
        await engine.dispose()
    summary = {"all_passed": True, "at": datetime.now(UTC).isoformat(), "steps": results,
               "scope": "SQLite pre-0017 metadata baseline stamped 0016, then 0017 up/down/up",
               "not_validated": ["PostgreSQL migration execution", "full migration chain on SQLite (0013 requires pgvector)"]}
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(output), **summary}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
