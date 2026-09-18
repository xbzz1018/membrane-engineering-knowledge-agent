# 运行手册

## 环境

项目不使用 Conda `base` 的 Python。完整运行环境是 `F:\code\homework\conda-envs\agent-membrane`；base 中的 `conda.exe` 只用于创建该 prefix 环境。

```powershell
cd F:\code\homework\project\membrane-engineering-knowledge-agent
powershell -ExecutionPolicy Bypass -File .\scripts\setup_env.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\verify_env.ps1
```

`setup_env.ps1` 默认安装 Full 模式依赖。仅本地快速开发可使用 `-Minimal`。

## 启动 Full 模式

```powershell
$python = 'F:\code\homework\conda-envs\agent-membrane\python.exe'

docker compose up -d postgres redis minio
docker compose --profile temporal up -d temporal-postgres temporal
& F:\code\homework\conda-envs\agent-membrane\Scripts\alembic.exe upgrade head
& $python scripts\seed_data.py
& $python scripts\run_temporal_worker.py
```

另开一个终端启动 API：

```powershell
$python = 'F:\code\homework\conda-envs\agent-membrane\python.exe'
& $python -m uvicorn src.main:app --host 127.0.0.1 --port 8080
```

端口：API `8080`、PostgreSQL/pgvector `5432`、Redis `16379`、Redis UI `18001`、MinIO `19000/19001`、Temporal `7233/8233`。

Full 模式 PDF 强制走 MinerU。不要把 `PARSER_MODE` 改成 `basic` 后仍宣称通过真实 PDF 验收。

## 配置与迁移

- 使用 `scripts/sync_api_config.ps1` 从本机凭据文件同步模型端点；脚本不会回显 Key。
- `.env` 被 Git 忽略，不能提交、截图或写入日志。
- 修改模型、存储或数据库参数后先运行 `scripts/verify_env.ps1`。
- Alembic 以仓库当前 `head` 为准，不在手册硬编码版本号。切换 Embedding 模型后运行 `scripts\reindex_full_embeddings.py`，旧向量不会参与新模型检索。

## 客户端接入

- 调用 `POST /api/v1/auth/login` 获取 JWT，此后使用 `Authorization: Bearer <token>`；服务端身份是权威，旧 `user_id` 字段不能作为权限依据。
- 先调用 `GET /api/v1/projects` 获取可访问项目，再上传、检索或审查资料。
- 文档上传是 multipart，请求包含 `file`、`project_id`、`data_classification`、`parse_method` 和业务版本；相同项目、SHA 与版本重复提交返回原记录。
- 普通 GET 状态是长任务恢复权威，SSE 只传阶段、状态、数量和安全错误类型；断线后按业务 ID 重新查询。
- MCP Streamable HTTP 运行在 `http://127.0.0.1:8090/mcp`，先用 FastAPI 的 `POST /api/v1/auth/mcp-token` 兑换限定 Scope 的短期 Token。stdio 仅用于可信本地查询工具验证。

常见 HTTP 状态：`401` 身份无效，`403` 角色无权限，`404` 对象不存在或被项目范围隐藏，`409` 状态冲突，`415` 文件类型不支持，`422` 参数或解析失败，`429` 限流或预算不足，`502/503` 外部模型、工作流或依赖不可用。

## 验收命令

```powershell
$python = 'F:\code\homework\conda-envs\agent-membrane\python.exe'

& $python -m pytest -q
& $python -m ruff check src scripts test alembic
& $python -m pip check
& $python scripts\validate_data.py
docker compose config --quiet

# Full 存储/模型/MinerU 验收：临时设置 TEMPORAL_ENABLED=false
& $python scripts\validate_full_runtime.py

# Temporal：TEMPORAL_ENABLED=true
& $python scripts\validate_temporal.py
& $python scripts\validate_mcp.py
& $python scripts\run_retrieval_comparison.py
& $python scripts\run_real_package_benchmark.py
```

## 故障处理

- `failed`：解析或模型调用失败；检查错误类型和 Temporal Activity 历史。
- `index_failed`：PostgreSQL Evidence 已写入但 pgvector 索引失败；可重试索引，不能当作可检索资料。
- `reserved` 预算停滞：先查询工作流，再执行维护补偿；不要手工修改项目计数。
- Redis 不可用：会话 Checkpoint/限流接口显式失败，Redis 不承担队列职责。
- Worker 中断：重启 `run_temporal_worker.py`，Temporal 会重放未完成 Activity。
- 云端调用被拒绝：检查资料分级；`internal/restricted` 必须配置获批的本地模型后才能处理。

本手册不包含任何删除卷的命令。清理前备份 PostgreSQL（含 pgvector 索引）、MinIO、Redis 和 Temporal 数据。

## 启动 Vue 前端

```powershell
cd F:\code\homework\project\membrane-engineering-knowledge-agent\frontend
npm install --registry=https://registry.npmmirror.com
npm run dev
```

访问 `http://127.0.0.1:5173`。前端通过 `VITE_API_BASE_URL` 连接 API，开发时 API 监听 `http://127.0.0.1:8080`。
