# 膜结构企业资料审查平台

面向膜结构公司内部设计、膜材采购和项目审核人员的后端演示系统。系统提供项目级资料隔离、工程知识问答、文档解析、三领域资料审查、证据引用、人工审批与长期任务恢复。不进行结构安全计算，不生成正式报价。

## 架构边界

- FastAPI 提供 JWT、RBAC、项目、文档、问答、审查、工作流和记忆 API。
- LangChain `create_agent` 实现一个 KnowledgeAgent 和设计、膜材、价格三个审查 Worker。
- LangGraph 是 Agent 运行时；Full 模式使用 Redis Checkpointer 保存 24 小时短期会话状态。
- Temporal 是唯一后台任务系统，负责解析、批量导入、审查、重试、Heartbeat、Query、Signal 和 Cancellation。
- PostgreSQL 保存业务事实、审查报告、记忆权威记录、预算与运行摘要；MinIO 保存原文件和派生图片；Milvus 保存文档及已确认记忆向量。
- 项目不使用 DeepAgents、Neo4j、Kafka、RabbitMQ、A2A 或 Kubernetes。

## 文档与证据

- PDF 强制使用 MinerU 时支持 `auto/text/ocr`，失败显式进入 `failed`。
- DOCX/XLSX 原生提取正文、标题、表格和单元格；嵌入栅格图片交给 MinerU OCR。
- EvidenceUnit 保存稳定 ID、页码或 Office 定位、版本、解析器、OCR 标记和 SHA-256。
- Cloud Provider 只能处理 `public` 资料；项目包含 `internal/restricted` 资料时显式拒绝云调用。

## 本地验证

```powershell
cd F:\code\homework\project\membrane-engineering-knowledge-agent
$python = 'F:\code\homework\conda-envs\agent-membrane\python.exe'

$env:RUNTIME_MODE = 'local'
$env:MODEL_MODE = 'fake'
$env:PARSER_MODE = 'basic'
$env:TEMPORAL_ENABLED = 'false'
$env:AUTH_ENABLED = 'false'

& $python -m pytest -q
& $python -m ruff check src scripts test alembic
& $python -m pip check
& $python scripts\validate_data.py
```

## Full 模式

```powershell
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\import_api_env.ps1 `
  -SourceFile F:\code\homework\project\2-AgriGraph\.env.ai `
  -TargetFile .env -EnableApiMode

& powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\configure_full_local.ps1 `
  -TargetFile .env -EnableTemporal

docker compose up -d postgres redis minio etcd milvus
docker compose --profile temporal up -d temporal
& F:\code\homework\conda-envs\agent-membrane\Scripts\alembic.exe upgrade head
& $python scripts\run_temporal_worker.py
& $python -m uvicorn src.main:app --host 127.0.0.1 --port 8080
```

Full 存储/模型链路与 Temporal 恢复链路分别运行：

```powershell
# Full 验证时临时设置 TEMPORAL_ENABLED=false
& $python scripts\validate_full_runtime.py

# Temporal 验证时设置 TEMPORAL_ENABLED=true，并确保 Worker 可启动
& $python scripts\validate_temporal.py
```

## API

| 范围 | 主要端点 |
|---|---|
| 身份 | `POST /api/v1/auth/login`, `GET /api/v1/auth/me` |
| 项目 | `GET/POST /api/v1/projects`, `POST /api/v1/projects/{id}/members` |
| 问答 | `POST /api/v1/chat`, `POST /api/v1/chat/stream` |
| 文档 | `POST /api/v1/documents/upload`, `POST /api/v1/documents/{id}/index` |
| 审查 | `POST /api/v1/package-reviews`, `GET /api/v1/package-reviews/{id}`, `GET .../stream` |
| 批量 | `POST /api/v1/batch-imports`, `GET /api/v1/batch-imports/{id}`, `GET .../stream` |
| 工作流 | `GET /api/v1/workflows/{id}`, approve/reject/cancel 子路径 |
| 记忆 | 候选、确认、拒绝、列表和删除 under `/api/v1/memories` |

完整合同见 [frontend-contract.md](docs/frontend-contract.md)，架构和运行说明见 [architecture.md](docs/architecture.md) 与 [operator-runbook.md](docs/operator-runbook.md)。
