# Project Agent Rules

## Boundaries

- This repository is a local Docker Compose demonstration, not structural safety software or a quotation system.
- Do not add A2A or Kubernetes. Do not perform structural safety calculations or generate formal quotations.
- Do not commit company-internal documents, customer data, contracts, real quotations, `.env`, API keys, or model responses containing secrets.
- Fake mode is allowed only when `MODEL_MODE=fake`. API mode must fail explicitly and must never silently fall back to Fake.

## Backend Ownership

- PostgreSQL stores business facts, reports, Outbox, and Inbox records.
- Redis stores short-term conversation state and LangGraph checkpoints. It is not a task queue.
- MinIO is the authoritative uploaded-file store in Full mode.
- Milvus stores document-chunk and long-term-memory vectors.
- Neo4j stores project-to-structure/material/scenario relations.
- Temporal is authoritative for long-running document and package-review workflows.
- Kafka distributes batch events through PostgreSQL Outbox Relay; it does not own workflow state.

## Development Rules

- Preserve the Local/Fake path while changing Full mode.
- Every external capability must have a real-chain validation before it is described as complete.
- Public data requires URL, license note, retrieval time, and SHA-256. Synthetic prices must remain explicitly synthetic.
- Use Alembic for schema changes. Update both PostgreSQL and SQLite migrations.
- Keep EventEnvelope backward-compatible or increment `schema_version`.
- Keep DeepAgents on StateBackend with read-only `/evidence/**`; do not expose Shell or arbitrary network tools.

## Commands

```powershell
$python = 'F:\code\homework\conda-envs\agent-membrane\python.exe'
& $python -m pytest -q
& $python -m ruff check src scripts test alembic
& $python scripts\validate_data.py
& $python scripts\run_frozen_eval.py
```

## Documentation

- [Architecture](docs/architecture.md)
- [Integration Guide](docs/integration-guide.md)
- [Operator Runbook](docs/operator-runbook.md)
- [Handoff](docs/handoff.md)
