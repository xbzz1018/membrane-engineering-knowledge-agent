# 膜结构工程知识助手

基于天宫医疗 day05 知识问答 Agent 改造的工程资料助手，面向膜结构设计方案、膜材规格、公开工程案例和历史价格资料。

## 能力

- LangGraph Supervisor 按问题类型调度方案案例、膜材规格和价格查询 Agent。
- 支持 PDF、DOCX、XLSX、TXT 和 Markdown 上传、切分、版本登记和证据返回。
- PostgreSQL/SQLite 保存业务数据，Redis 保存短期会话，Milvus/Neo4j 作为可选向量和关系检索后端。
- DeepAgents 仅用于多文档方案比较和资料包审查。
- Temporal 仅用于长时间文档处理和人工等待；Kafka 仅用于批量资料事件分发。
- 不进行结构安全计算，不生成正式报价。

## 快速启动（无 Key）

```powershell
cd F:\code\homework\project\membrane-engineering-knowledge-agent
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup_env.ps1 -CondaExe D:\Codesoftwares\anaconda\Anaconda3\Scripts\conda.exe
Copy-Item .env.example .env
& F:\code\homework\conda-envs\agent-membrane\python.exe -m pytest -q
& F:\code\homework\conda-envs\agent-membrane\python.exe -m uvicorn src.main:app --host 127.0.0.1 --port 8080
```

需要 DeepAgents、Temporal、Kafka 和 Milvus/Neo4j SDK 时，在创建环境命令后增加 `-InstallOptional`。

默认 `MODEL_MODE=fake`，使用 SQLite 和本地文件，不需要启动 Docker。

## 使用真实模型

在本地 `.env` 中设置 `MODEL_MODE=api`，然后填写已有的 DashScope 或 DeepSeek Key。真实 Key 不要提交到 Git。

如果要从已有项目的环境文件导入允许的模型配置，可显式执行：

```powershell
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\import_api_env.ps1 -SourceFile F:\path\to\existing\.env
```

```text
MODEL_PROVIDER=auto
DASHSCOPE_API_KEY=
DEEPSEEK_API_KEY=
BASE_URL_CHAT=
CHAT_MODEL=deepseek-chat
EMBEDDING_MODEL=text-embedding-v3
```

## Docker 依赖

需要完整检索时执行：

```powershell
docker compose up -d postgres redis minio etcd milvus neo4j
```

Temporal 和 Kafka 使用独立 Profile：

```powershell
docker compose --profile temporal up -d
docker compose --profile kafka up -d
```

然后把 `.env` 中的 `RUNTIME_MODE=full`、`TEMPORAL_ENABLED=true` 或 `KAFKA_ENABLED=true` 打开，并分别运行：

```powershell
& F:\code\homework\conda-envs\agent-membrane\python.exe scripts\run_temporal_worker.py
& F:\code\homework\conda-envs\agent-membrane\python.exe scripts\run_kafka_consumer.py
```

## API

```text
GET  /health
GET  /health/deps
POST /api/v1/chat
POST /api/v1/chat/stream
POST /api/v1/documents/upload
POST /api/v1/documents/{document_id}/index
POST /api/v1/package-reviews
```

## 数据

`data/processed` 中的文件是可提交的小型 fixture。公开数据采集和 100+ 案例扩充使用 `scripts`，原始 PDF 放在本地 `data/raw`，仓库只保存来源、许可证和 SHA-256 manifest。合成案例和价格记录均标记 `synthetic=true`。

生成并导入本地案例：

```powershell
& F:\code\homework\conda-envs\agent-membrane\python.exe scripts\collect_public_case_metadata.py --limit 100
& F:\code\homework\conda-envs\agent-membrane\python.exe scripts\build_synthetic_cases.py --count 100
& F:\code\homework\conda-envs\agent-membrane\python.exe scripts\seed_data.py
& F:\code\homework\conda-envs\agent-membrane\python.exe scripts\validate_data.py
```

## 项目边界

这是一个可复现的 Agent 应用项目，不是正式工程设计或报价软件。所有工程安全结论、最终选材和合同报价都必须由专业人员复核。
