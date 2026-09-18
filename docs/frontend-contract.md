# 前端接口合同

## 角色

| 能力 | 管理员 | 设计工程师 | 膜材/采购 | 审核人 |
|---|---:|---:|---:|---:|
| 管理用户、项目和成员 | 是 | 否 | 否 | 否 |
| 上传并索引已授权项目资料 | 是 | 是 | 是 | 否 |
| 在已授权项目内问答 | 是 | 是 | 是 | 是 |
| 发起资料包审查 | 是 | 是 | 是 | 是 |
| 批准、退回和处理问题单 | 是 | 否 | 否 | 是 |
| 确认、删除自己的长期记忆 | 是 | 是 | 是 | 是 |

未授权的项目对象通常返回 `404`，避免泄露其存在。

## 状态机

```text
资料：uploaded|failed|index_failed -> indexing -> indexed|failed|index_failed
批量：queued -> running -> completed|partial_failed|failed|cancelled
审查：queued -> running -> completed
                    \-> awaiting_approval -> approved|rejected
                    \-> failed|cancelled
问题单：open|pending_human -> resolved|dismissed
记忆：pending -> confirmed|rejected -> deleted
```

## 客户端规则

- JWT 不进入渲染态，所有请求使用 Bearer Token。
- 项目只能来自 `GET /api/v1/projects`，前端不得伪造 tenant 或 user ID。
- GET 状态为权威；SSE 可能断线，且只包含进度元数据。
- 每条审查结论展示来源标题、页码/位置、日期、版本和 Evidence ID。
- `GET /api/v1/package-reviews/{review_id}/issues` 返回结构化问题单，展示领域、类型、严重级别、实际/预期值、建议、状态和证据定位。
- 审核人使用 `PATCH /api/v1/package-reviews/{review_id}/issues/{issue_id}` 更新状态，必须携带报告的 `expected_lock_version`；`409` 时刷新报告后重试。
- synthetic 价格只能显示为历史测试数据，不能显示为报价。
- `internal/restricted` 云端拒绝是策略状态，不应作为可无限重试的模型错误。
- `429` 区分接口限流和项目预算；`502/503` 保留 workflow ID 后允许重新查询状态。

## 上传、问答与审查

- `POST /api/v1/documents/upload` 使用 multipart，提交 `file`、`project_id`、`data_classification`、`parse_method=auto|text|ocr` 和业务版本；默认最大 25 MB。
- `POST /api/v1/chat` 提交 `project_id`、`session_id` 和消息。来源显示稳定 Evidence ID、文件、页码或 Office 位置、日期、版本和检索说明。
- `POST /api/v1/package-reviews` 接收同一项目的 1 至 20 份已索引资料；`review_mode=full` 固定覆盖三个领域，`focused` 由 Supervisor 从白名单选择领域。
- 审查可能处于 `queued`、`running`、`awaiting_approval` 或终态。没有有效证据的模型输出只能显示为待人工确认。
- 记忆由 Agent 提议为 `pending`，用户确认后才写入 pgvector 索引；记忆只辅助理解上下文，不作为审查证据。

SSE 端点包括 `GET /api/v1/batch-imports/{id}/stream` 和 `GET /api/v1/package-reviews/{id}/stream`。SSE 不返回 Prompt、完整资料、模型正文或隐藏推理。

FastAPI `/openapi.json` 是字段级权威接口定义；本文件描述跨端点行为和前端交互约束。

## Vue 前端实现

仓库中的 `frontend/` 是独立 Vue 3 + TypeScript + Vite + Element Plus 工作台，默认运行在 `http://127.0.0.1:5173`，通过 `VITE_API_BASE_URL` 连接 FastAPI。前端只调用 REST/SSE，不直接连接 MCP、PostgreSQL/pgvector、MinIO 或 Temporal。页面不自动降级为演示数据。
