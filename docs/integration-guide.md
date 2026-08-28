# API Integration Guide

## Authentication

Call `POST /api/v1/auth/login` and send `Authorization: Bearer <token>`. The JWT identity is authoritative; clients must not rely on legacy `user_id` fields. Query `GET /api/v1/projects` before selecting a project.

## Upload And Index

`POST /api/v1/documents/upload` is multipart with `file`, `project_id`, `data_classification`, `parse_method`, and `version`. Duplicate `project + SHA + version` returns the existing document. `POST /api/v1/documents/{id}/index` returns either a local result or a Temporal `workflow_id`.

Allowed parse methods are `auto`, `text`, and `ocr`. MinerU errors return 422 and persist a failed state. Unsupported file types return 415; the default file limit is 25 MB.

## Chat And Review

Chat requires `project_id`, `session_id`, and `message`. Sources contain stable source ID, location/page, excerpt, date, version, retrieval explanation, and optional fusion score.

Package review accepts 1-20 indexed document IDs from one project. The response may be `queued`, `completed`, or `awaiting_approval`. Facts without valid evidence remain uncertainties or human-review items.

## Long Tasks

Use normal GET status as the recovery authority. SSE endpoints are convenience streams:

- `GET /api/v1/batch-imports/{id}/stream`
- `GET /api/v1/package-reviews/{id}/stream`

SSE carries stage/status, worker state, counts, elapsed state, and error type only. After disconnect, reconnect by business ID or GET workflow status. Never expect prompt, source content, output body, or hidden reasoning in SSE.

## Memory

Agents only propose `pending` candidates. Use confirm/reject endpoints before a candidate becomes project or user memory. Confirmed memory is indexed in Milvus but remains non-evidentiary. Delete removes both authority row and vector index.

## Errors

| Status | Meaning |
|---|---|
| 401 | missing/invalid JWT or disabled user |
| 403 | authenticated role lacks action permission |
| 404 | object missing or deliberately hidden by project scope |
| 409 | state conflict, duplicate running work, or required Temporal disabled |
| 415 | unsupported upload type |
| 422 | invalid request or parser failure |
| 429 | API rate limit or project budget/concurrency quota |
| 502 | model, reranker, or Temporal operation failed |
| 503 | required Redis/dependency unavailable |

See `frontend-contract.md` for states and role matrix.
