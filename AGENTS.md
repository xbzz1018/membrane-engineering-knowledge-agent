# Project Agent Rules

## Boundaries

- This is a single-company Docker Compose demonstration, not structural safety or quotation software.
- Do not add A2A, Kubernetes, DeepAgents, Neo4j, Kafka, or RabbitMQ.
- Do not commit internal documents, customer data, real quotations, `.env`, API keys, prompts, or model output containing secrets.
- Fake mode is explicit. API mode retries and fails; it never silently returns Fake output.

## Ownership

- PostgreSQL is authoritative for identities, projects, facts, reports, memory, budget, and safe Agent run summaries.
- Redis stores LangGraph checkpoints, rate-limit state, and optional cache. It is not a queue and must not keep duplicate chat lists.
- MinIO is authoritative for original files and derived Office images.
- PostgreSQL + pgvector indexes EvidenceUnit and confirmed memory vectors; vector tables are rebuildable indexes, not business authority.
- Temporal is the only durable queue and long-running workflow authority.
- LangChain `create_agent` is the Agent abstraction; LangGraph is the runtime/checkpointer layer.

## Engineering Rules

- Every read and tool call must receive server-derived Principal and ProjectScope.
- Cloud providers may process only public data. Internal or restricted data requires a configured local provider.
- MinerU failure is explicit. Do not silently fall back to the basic PDF parser.
- Enterprise/project facts and precise engineering parameters need valid evidence IDs; memory is context, never evidence. Explicitly labeled general explanations may answer without retrieval; they must not assert project facts or claim tool execution.
- Use Alembic for schema changes. Keep Local/Fake tests isolated from a developer `.env`.
- Every ingest write must validate its persisted execution/attempt claim; a stale Activity must not write chunks, vectors or status.
- Keep synchronous demo.db and persistent Temporal demo-v2 databases/queues separate. Legacy synchronous acceptance scripts must not target the asynchronous demo.
- frontend/node_modules is a dependency junction: never install, delete or upgrade through it.
- Do not claim Full, real-model, MinerU, or Temporal recovery completion without current validation output.

## Verification

```powershell
$python = 'F:\code\homework\conda-envs\agent-membrane\python.exe'
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
& $python -m pytest -q -p pytest_asyncio.plugin
& $python -m ruff check src scripts test alembic
& $python -m pip check
& $python scripts\validate_data.py
```

See `docs/architecture.md`, `docs/frontend-contract.md`, and `docs/operator-runbook.md`.
