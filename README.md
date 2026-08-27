# 膜结构工程知识助手

本机 Docker Compose 求职演示项目，支持膜结构案例、膜材规格、synthetic 历史价格、上传资料与项目记忆检索。项目不进行结构安全计算，不生成正式报价。

## 能力

- LangGraph 路由设计、膜材、价格与复合问题。
- PDF、DOCX、XLSX、TXT、Markdown 上传、解析、版本与页码证据。
- Full 模式使用 PostgreSQL、Redis、MinIO、Milvus、Neo4j，并返回可解释的多源融合结果。
- DeepAgents 设计/膜材/价格三子 Agent 受限资料包审查。
- Temporal 长任务、审批/拒绝、取消、幂等与恢复。
- Kafka PostgreSQL Outbox Relay、Inbox 幂等、DLQ 与 event_id 重放。
- 37 条单元/接口测试、30 份文档 fixture、80 条 SHA 锁定评测集。

## 快速验证

```powershell
cd F:\code\homework\project\membrane-engineering-knowledge-agent
$python = 'F:\code\homework\conda-envs\agent-membrane\python.exe'

$env:RUNTIME_MODE = 'local'
$env:MODEL_MODE = 'fake'
$env:DEEPAGENTS_ENABLED = 'false'
$env:TEMPORAL_ENABLED = 'false'
$env:KAFKA_ENABLED = 'false'

& $python -m pytest -q
& $python -m ruff check src scripts test alembic
& $python scripts\validate_data.py
```

## Full 模式

安全复用本地模型配置（只导入白名单变量，不显示值）：

```powershell
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\import_api_env.ps1 `
  -SourceFile F:\code\homework\project\2-AgriGraph\.env.ai `
  -TargetFile .env -EnableApiMode

& powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\configure_full_local.ps1 `
  -TargetFile .env -EnableDeepAgents -EnableTemporal -EnableKafka
```

启动依赖：

```powershell
docker compose up -d postgres redis minio etcd milvus neo4j
docker compose --profile temporal up -d temporal
docker compose --profile kafka up -d kafka

& F:\code\homework\conda-envs\agent-membrane\Scripts\alembic.exe upgrade head
& $python -m uvicorn src.main:app --host 127.0.0.1 --port 8080
```

Worker/Relay 使用独立终端：

```powershell
& $python scripts\run_temporal_worker.py
& $python scripts\run_kafka_relay.py
& $python scripts\run_kafka_consumer.py
```

## API

| Area | Endpoints |
|---|---|
| Health | `GET /health`, `GET /health/deps` |
| Chat | `POST /api/v1/chat`, `POST /api/v1/chat/stream` |
| Documents | `POST /api/v1/documents/upload`, `POST /api/v1/documents/{id}/index` |
| Reviews | `POST /api/v1/package-reviews`, `GET /api/v1/package-reviews/{id}` |
| Workflows | status, approve, reject, cancel under `/api/v1/workflows/{id}` |
| Memory | list/delete under `/api/v1/memories/{user_id}` |
| Batch events | `POST /api/v1/batch-imports`, `POST /api/v1/events/{event_id}/replay` |

## 数据门禁

```powershell
& $python scripts\validate_data.py
& $python scripts\run_frozen_eval.py
```

公开记录包含 URL、许可说明、抓取时间与 SHA-256。价格数据全部标记 `synthetic=true`，不是市场报价。

## 文档

- [Agent 规则](AGENTS.md)
- [架构与数据模型](docs/architecture.md)
- [API 接入指南](docs/integration-guide.md)
- [运维手册](docs/operator-runbook.md)
- [交接状态](docs/handoff.md)
