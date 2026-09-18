# 膜结构企业资料审查平台

面向膜结构公司设计、膜材采购和项目审核人员的企业工程资料智能审查平台。系统提供项目级资料隔离、工程知识问答、文档解析、三领域资料审查、证据引用、人工审批与长任务恢复。

## 项目定位

这是一个面向膜结构企业内部资料的工程审查平台：它把文档、材料规格、价格记录和设计问题放进有权限边界的项目空间，再通过证据单元、受控 Agent、人工审批和可恢复工作流生成审查结果。

项目明确不做结构安全计算、正式报价、施工设计或自动安全审批；模型输出必须绑定证据，云 Provider 只能处理公开资料，内部或受限资料需要本地 Provider。

项目背景、技术栈、评测口径和可点击源码导航见 [面试准备-膜构智审-综合版.md](面试准备-膜构智审-综合版.md)。

## 架构边界

- FastAPI 提供 JWT、RBAC、项目、文档、问答、审查、工作流和记忆 API。
- LangChain `create_agent` 实现 KnowledgeAgent、ReviewSupervisorAgent 以及设计、膜材、价格三个审查 Worker；Supervisor 只生成受限审查计划，不直接操作权限或数据。
- LangGraph 是 Agent 运行时；Full 模式使用 Redis Checkpointer 保存 24 小时短期会话状态。
- Temporal 是唯一后台任务系统，负责解析、批量导入、审查、重试、Heartbeat、Query、Signal 和 Cancellation。
- PostgreSQL 保存业务事实、审查报告、记忆权威记录、预算与运行摘要，并通过 pgvector 保存文档及已确认记忆向量；MinIO 保存原文件和派生图片。
- MCP 只作为外部 Agent 接入层，复用应用服务并执行 Scope、项目权限、幂等、Elicitation 和调用审计；它不参与内部 Agent 调度。
- `membrane-package-review` Skill 只描述外部 Agent 如何组合 MCP 工具，不能越权或自动审批。
- 独立 `frontend/` 使用 Vue 3 + TypeScript + Vite + Element Plus，调用 FastAPI REST/SSE 提供企业资料、台账、问答和审查工作台；前端不直接调用 MCP 或基础设施。
- 项目不使用 DeepAgents、Neo4j、Kafka、RabbitMQ、A2A 或 Kubernetes。

## 文档与证据

- PDF 强制使用 MinerU 时支持 `auto/text/ocr`，失败显式进入 `failed`。
- DOCX/XLSX 原生提取正文、标题、表格和单元格；嵌入栅格图片交给 MinerU OCR。
- EvidenceUnit 保存稳定 ID、页码或 Office 定位、版本、解析器、OCR 标记和 SHA-256。
- Cloud Provider 只能处理 `public` 资料；项目包含 `internal/restricted` 资料时显式拒绝云调用。
- 公开案例来自 TensiNet 列表页和详情页元数据，记录字段来源 URL、抓取时间和 SHA-256；不把受版权保护的原始案例 PDF 提交到仓库。
- 测试用 PDF fixture 每份为 2 页；公开膜材规格源 PDF 为 7 页，规格记录保留来源页码，校验会拒绝单页或页数不一致的 fixture。

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

首次迁移到 pgvector 或切换 `EMBEDDING_MODEL` 后，需要执行 `& $python scripts\reindex_full_embeddings.py` 重建文档与确认记忆向量。

## 环境迁移

项目运行时不使用 Conda `base`。完整环境固定在 `F:\code\homework\conda-envs\agent-membrane`；`base` 中的 `conda.exe` 只用于创建或更新该 prefix 环境。

```powershell
cd F:\code\homework\project\membrane-engineering-knowledge-agent
powershell -ExecutionPolicy Bypass -File .\scripts\setup_env.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\verify_env.ps1

# 后续命令避免直接使用终端的 python。
$python = 'F:\code\homework\conda-envs\agent-membrane\python.exe'
& $python -m pytest -q
```

`environment.yml` 和 `requirements-full.txt` 包含 Full 模式依赖；`setup_env.ps1 -Minimal` 只安装本地开发依赖。

## Full 模式

```powershell
# api.txt 只保存在本机，不要提交或粘贴到日志；脚本不会回显 Key。
$apiFile = 'C:\path\to\api.txt'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\sync_api_config.ps1 `
  -SourceFile $apiFile -TargetFile .env

& powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\configure_full_local.ps1 `
  -TargetFile .env -EnableTemporal

docker compose up -d postgres redis minio
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

Full 模式的 PDF 强制走 MinerU；`PARSER_MODE=basic` 仅用于本地 Fake 开发和快速单元测试。

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
| MCP | `POST /api/v1/auth/mcp-token`, Streamable HTTP `/mcp` |

前端启动和门禁见 [frontend/README.md](frontend/README.md)，视觉验收见 [docs/design-qa.md](docs/design-qa.md)。

完整合同见 [frontend-contract.md](docs/frontend-contract.md)，架构和运行说明见 [architecture.md](docs/architecture.md) 与 [operator-runbook.md](docs/operator-runbook.md)。

## 当前状态

本仓库包含本地 Fake 模式的快速验证、Full 模式的配置和 Temporal/MCP/Kafka 的显式验证脚本。只有在对应服务和数据门禁实际通过后，才能把 Full、MinerU、Temporal 或 Kafka 描述为已验证能力；本 README 不把配置文件存在等同于生产就绪。

## 公开仓库边界

- `.env`、真实 API Key、公司内部文件、客户合同和原始上传文件不属于仓库。
- `data/` 中的合成案例和公开元数据必须保留来源、许可证和 provenance。
- `docker/`、数据库、上传目录、日志和向量索引属于本地运行状态或可重建产物。
