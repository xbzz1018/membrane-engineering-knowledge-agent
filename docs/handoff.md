# Handoff Status

## Implemented

- JWT, four enterprise roles, project membership, server-derived identity, and project-scoped document/review access.
- LangChain KnowledgeAgent plus design/material/price review Workers; LangGraph Redis Checkpointer is the only short-term conversation state.
- PDF MinerU modes, DOCX/XLSX native extraction, embedded-image OCR, EvidenceUnit metadata, SHA idempotency, and explicit index failure state.
- PostgreSQL/MinIO/Milvus storage boundaries, confirmed-memory workflow, weighted retrieval, optional reranker, and stable evidence citations.
- Temporal single document, batch child workflows, package review, Query/Signal/Cancellation, retry/heartbeat, and three isolated activity queues.
- Transactional Token reservation/settlement, Redis API token bucket, Agent run summaries, safe OTel hooks, GET status, and SSE progress.
- Local/Fake automated suite, data validator, migrations, and updated backend/frontend contracts.

## Current Evidence

- Local/Fake: 41 passed, 2 real-MinerU tests skipped by default.
- Ruff and pip check: pass.
- Fresh Alembic upgrade: `0005_fix_evidence_asset_sha`.
- Full real model/storage/checkpoint validation: pass.
- Temporal 20/duplicate-20/50 batch, approve/reject, restart, and cancel validation: pass.
- Real MinerU PDF and DOCX/XLSX embedded-image OCR: pass.
- Frozen retrieval v2: 60 rows, Recall@10 1.0, MRR 0.3507; exact-ID scope only.
- Frozen package v2: 20 deterministic Fake reviews, schema/citation/evidence/conflict metrics 1.0.

## Remaining Gates

1. Configure and validate the optional qwen3-rerank endpoint.
2. Add a difficult-query pure-vector baseline and prove the required relative Recall improvement.
3. Run 5/20-document real-model performance, groundedness, citation, Token, and cost evaluations.
4. Expand the formal 16-fixture parser matrix and the RBAC/budget concurrency attack suite.

Do not reuse the previous DeepAgents/Neo4j/Kafka validation results for this architecture.
