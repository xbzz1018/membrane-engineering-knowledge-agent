# Frontend Contract

## Roles

| Capability | Admin | Design engineer | Material/procurement | Reviewer |
|---|---:|---:|---:|---:|
| Manage users/projects/members | yes | no | no | no |
| Upload and index authorized project documents | yes | yes | yes | no |
| Chat within authorized project | yes | yes | yes | yes |
| Start package review | yes | yes | yes | yes |
| Approve or reject review | yes | no | no | yes |
| Confirm/delete own memory | yes | yes | yes | yes |

Unauthorized project objects normally return 404 to avoid disclosing their existence.

## State Machines

```text
Document: uploaded|failed|index_failed -> indexing -> indexed|failed|index_failed
Batch: queued -> running -> completed|partial_failed|failed|cancelled
Review: queued -> running -> completed
                    \-> awaiting_approval -> approved|rejected
                    \-> failed|cancelled
Memory: pending -> confirmed|rejected -> deleted
```

## Client Rules

- Store the JWT outside rendered application state and attach it as a Bearer token.
- Select a project from `GET /api/v1/projects`; never invent a tenant or user ID.
- Treat GET status as authoritative. SSE may disconnect and contains no business content.
- Display source title, page/location, date, version, and evidence ID beside every review finding.
- Label synthetic prices as historical test data and never present them as quotations.
- Show internal/restricted cloud rejection as a policy state, not a retryable generic model error.
- On 409, refresh the object state. On 429, distinguish rate limiting from project budget detail. On 502/503, retain the workflow ID and allow status retry.

FastAPI `/openapi.json` is the field-level API authority. This file defines cross-endpoint behavior and UI assumptions.
