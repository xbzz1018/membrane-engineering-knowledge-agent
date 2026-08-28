# Operator Runbook

## Start

```powershell
cd F:\code\homework\project\membrane-engineering-knowledge-agent
$python = 'F:\code\homework\conda-envs\agent-membrane\python.exe'

docker compose up -d postgres redis minio etcd milvus
docker compose --profile temporal up -d temporal
& F:\code\homework\conda-envs\agent-membrane\Scripts\alembic.exe upgrade head
& $python scripts\run_temporal_worker.py
& $python -m uvicorn src.main:app --host 127.0.0.1 --port 8080
```

Ports: API 8080, PostgreSQL 5432, Redis 16379, Redis UI 18001, MinIO 19000/19001, Milvus 19530/9091, Temporal 7233/8233.

## Configuration

Import only allow-listed provider variables through `scripts/import_api_env.ps1`; never print or commit `.env`. Use `scripts/configure_full_local.ps1 -EnableTemporal` for local service endpoints. Change bootstrap password, JWT secret, database password, and MinIO credentials before any shared deployment.

## Migrations And Gates

Current migration head is `0005_fix_evidence_asset_sha`.

```powershell
& $python -m pytest -q
& $python -m ruff check src scripts test alembic
& $python -m pip check
& $python scripts\validate_data.py
docker compose config --quiet
```

Run `validate_full_runtime.py` with Temporal disabled and `validate_temporal.py` with Temporal enabled. Real MinerU fixture validation is opt-in with `RUN_MINERU_TEST=1` and can take several minutes.

## Failure Handling

- `failed`: parsing or model work failed; inspect error type and Temporal Activity history.
- `index_failed`: PostgreSQL Evidence exists but Milvus indexing failed; retry indexing, do not expose as searchable.
- stuck `reserved` budget: verify workflow state, then run the maintenance compensation path; do not edit project counters independently.
- Redis unavailable: chat Checkpointer/rate-limited APIs fail explicitly; Redis is never bypassed as a queue.
- Worker restart: restart `run_temporal_worker.py`; Temporal replays Workflow history and retries unfinished Activities.
- cloud call rejected: check document classification and configure an approved local provider before handling internal/restricted data.

No command in this runbook removes volumes. Back up PostgreSQL, MinIO, Milvus, Redis, and Temporal data before any manual cleanup.
