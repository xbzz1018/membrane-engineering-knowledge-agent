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
                    \-> awaiting_approval -> decision_pending -> approved|rejected（Temporal）
                    \-> failed|cancelled
      completed -> approved|rejected（审核人可决定）
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
- `POST /api/v1/package-reviews/{review_id}/decision`提交`decision=approved|rejected`、`expected_lock_version`和可选`reason`；退回必须有原因。Local无需Temporal即可决定，Temporal人工等待模式返回`decision_pending`及command_id后继续查权威状态，Activity消费决定后到终态；已自动完成报告可直接由审核人决定。
- 忽略问题时PATCH还必须提交非空`reason`。未解决/忽略的阻断或conflict问题禁止批准；终态禁止修改问题。UI只在`completed/awaiting_approval`展示处理与决定按钮，取消确认框不发请求。
- 旧`/workflows/package-review:{id}/approve|reject`也要求当前`expected_lock_version`并经过同一业务检查，不能绕过问题处理门禁。
- synthetic 价格只能显示为历史测试数据，不能显示为报价。
- `internal/restricted` 云端拒绝是策略状态，不应作为可无限重试的模型错误。
- `429` 区分接口限流和项目预算；`502/503` 保留 workflow ID 后允许重新查询状态。

## 上传、问答与审查

- `POST /api/v1/documents/upload` 使用 multipart，提交 `file`、`project_id`、`data_classification`、`parse_method=auto|text|ocr` 和业务版本；默认最大 25 MB。
- `POST /api/v1/chat` 提交 `project_id`、`session_id` 和消息。来源显示稳定 Evidence ID、文件、页码或 Office 位置、日期、版本和检索说明。
- `POST /api/v1/package-reviews` 接收同一项目的 1 至 20 份已索引资料；`review_mode=full`覆盖retrieval/material/review，`focused`由Supervisor从白名单选择；review依赖retrieval/material。问题业务domain可以仍为design/price等，与Agent角色不同。
- 审查可能处于 `queued`、`running`、`awaiting_approval` 或终态。没有有效证据的模型输出只能显示为待人工确认。
- 记忆由 Agent 提议为 `pending`，用户确认后才写入 pgvector 索引；记忆只辅助理解上下文，不作为审查证据。

SSE 端点包括 `GET /api/v1/batch-imports/{id}/stream` 和 `GET /api/v1/package-reviews/{id}/stream`。SSE 不返回 Prompt、完整资料、模型正文或隐藏推理。

FastAPI `/openapi.json` 是字段级权威接口定义；本文件描述跨端点行为和前端交互约束。

`completed`表示自动审查结束且无当前阻断项，不等于人工批准。`issues`是复核处理状态的权威；报告正文和`worker_results`保留生成时发现。引用的`content_sha256/document_sha256`用于追溯，不等于已验证模型解释。

## Vue 前端实现

仓库中的 `frontend/` 是独立 Vue 3 + TypeScript + Vite + Element Plus 工作台，默认运行在 `http://127.0.0.1:5173`，通过 `VITE_API_BASE_URL` 连接 FastAPI。前端只调用 REST/SSE，不直接连接 MCP、PostgreSQL/pgvector、MinIO 或 Temporal。页面不自动降级为演示数据。

## 显式业务检索条件

- GET/PUT /api/v1/documents/{id}/business-metadata读取或声明engineering_model、applicable_revision、document_type、effective_from/to、source_note；PUT必须带expected_lock_version，返回声明人和新文档锁版本。资料列表已有编辑弹窗，先读取当前文档版本与声明，再保存；409禁止继续提交直到重载。来源说明必填，声明人由服务端生成。
- `POST /api/v1/documents/search`提交project_id、query、filters、limit；filters含engineering_model/applicable_revision/upload_version/effective_on/document_type。query可为空，用于纯精确条件查询。硬条件为空且query为空返回空；生效区间未知不命中effective_on。
- `applied_filters`回显实际条件。Function Calling和MCP工具接受同名filters对象，身份与tenant不属于工具输入。

资料页切换项目清除旧结果/编辑状态，序列号保护过期响应；搜索结果显示来源、位置、版本、片段并打开真实Evidence抽屉。加载/空/错误状态分开。

审查详情对queued/running/awaiting_approval/decision_pending每6秒安静刷新，卸载时停止；以GET状态更新操作权限。等待审批时可取消，decision_pending冻结人工处理，终态隐藏决定/问题修改操作。浏览器验收覆盖实际异步转换。

## Markdown与角色显示（2026-11-03）

GET /api/v1/documents/{id}/markdown在indexed后返回派生文本；GET /api/v1/package-reviews/{id}/markdown在报告存在后返回生成时正文及当前问题状态。两者使用JWT/项目权限和Cache-Control:no-store，未就绪409，内容为text/markdown。页面通过鉴权请求下载，不能把URL作为公开静态文件分享。审查详情显示检索/材料/审查；历史design/price结果保留历史标签。
