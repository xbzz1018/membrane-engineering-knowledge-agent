# 运行手册

更新：2026-11-02。实际通过项和边界见[当前验证](current-validation.md)。本机Python固定为F:\code\homework\conda-envs\agent-membrane\python.exe，运行时不使用Conda base。

新增单机容器部署入口 `deploy/compose.yaml`，包含迁移、应用、Worker 与基础设施；具体操作见[部署说明](deployment.md)。它使用独立命名卷和 deployment 队列，不与下述本机 demo 数据混用。当前仅完成静态配置与门禁验证，未完成容器整栈验收。

## 三种运行方式

| 模式 | 入口与存储 | 用途 |
|---|---|---|
| 同步Local/Fake | start_demo.ps1；data/runtime/demo.db | 小包同步演示，旧demo_acceptance/validate_resume_slice脚本 |
| 持久异步Local/Fake | start_demo.ps1 -Temporal -Mcp；data/runtime/temporal-demo-v2/business.db与temporal.db | 当前真实Temporal开发Server演示、人工等待与重启 |
| Full/API | .env配置、Docker PostgreSQL/pgvector/Redis/MinIO、真实模型及Worker | 单独验收；本轮完整栈未运行 |

两种Local库分开，禁止把旧同步脚本直接对异步服务运行。新Temporal演示使用独立v2队列，不能接管未经重放验证的旧生产历史。

## 当前异步演示

```powershell
cd 'F:\工作\04项目资料\简历项目\资料智能审查落地版'
$python = 'F:\code\homework\conda-envs\agent-membrane\python.exe'
# 首次缺CLI时：下载官方开发Server并在隔离库做故障验收
& $python scripts\validate_temporal_local.py
# 已有演示需先停再启动；停止脚本核对PID及启动时间
& .\scripts\stop_demo.ps1
& .\scripts\start_demo.ps1 -Temporal -Mcp
& $python scripts\seed_temporal_demo.py
```

入口http://127.0.0.1:5173，API http://127.0.0.1:8080/docs，MCP http://127.0.0.1:8090/mcp，Temporal gRPC默认127.0.0.1:17233（无Web UI）。开发账号admin / admin-change-me。seed留下待复核合成报告，ID保存在data/runtime/temporal-demo-acceptance.json。重复seed会新建审查，原文件按哈希/版本复用。

脚本设置RUNTIME_MODE=local、MODEL_MODE/MODEL_PROVIDER=fake、PARSER_MODE=basic、RERANKER_ENABLED=false；-Temporal启用TEMPORAL_ENABLED、TEMPORAL_TARGET及TEMPORAL_TASK_QUEUE/PARSE_TASK_QUEUE/REVIEW_TASK_QUEUE/MAINTENANCE_TASK_QUEUE。持久库不随停止删除，整套重启后待复核报告和工作流仍可继续。进程记录在data/runtime/demo-processes.json，日志同目录。

资料列表可编辑型号、适用版次、类型、业务生效区间和声明依据；409后重载。检索允许只有精确条件，未知日期不命中effective_on。审核人先处理阻断问题，再提交决定；decision_pending需等Workflow消费，页面每6秒刷新。

## 环境与Full模式

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup_env.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\verify_env.ps1
```

setup_env默认安装Full依赖，-Minimal用于本地开发。凭据通过scripts/sync_api_config.ps1从获准本机文件同步，不能输出、截图或提交.env。Full参数由scripts/configure_full_local.ps1配置；云模型只能处理public资料。

```powershell
docker compose up -d postgres redis minio
docker compose --profile temporal up -d temporal-postgres temporal
& F:\code\homework\conda-envs\agent-membrane\Scripts\alembic.exe upgrade head
& $python scripts\seed_data.py
& $python scripts\run_temporal_worker.py
# 另终端、相同配置
& $python -m uvicorn src.main:app --host 127.0.0.1 --port 8080
```

Full端口：PostgreSQL5432、Redis16379/UI18001、MinIO19000/19001、Temporal7233/8233。Full PDF强制MinerU，不能以basic代替OCR验收。切换EMBEDDING_MODEL后运行scripts/reindex_full_embeddings.py，旧模型向量不参与新检索。

迁移以alembic head为准：0014业务声明、0015不可变审查快照、0016执行认领。Local create_all会新增独立表，Full已有库必须迁移；本轮仅SQLite迁移演练通过。工作流命令序列改变时使用新Worker版本/队列或排空旧任务，并重放目标历史；本轮5份新历史通过不代表旧历史迁移完成。

## 接入约定

- POST /api/v1/auth/login取JWT，身份/项目范围由服务端派生。GET /api/v1/projects后选择有权项目。
- 上传multipart含file/project_id/data_classification/parse_method/版本；同项目、SHA及版本重复提交复用文档。
- GET/PUT /api/v1/documents/{id}/business-metadata用于声明，PUT需source_note和expected_lock_version；POST /api/v1/documents/search接受query/filters/limit。
- GET报告和工作流是状态权威；SSE只传进度元数据，断线后以业务ID查状态。
- 问题PATCH及报告decision都需当前锁版本；忽略/退回有原因，阻断未处理禁止批准，终态不可修改。
- MCP HTTP先以/api/v1/auth/mcp-token兑换短期scope token，写工具需确认及幂等键；stdio只读。

常见状态码：401身份、403角色/分级、404对象隐藏、409版本/状态冲突、415格式、422校验、429限流/预算、502/503外部依赖不可用。API失败不切Fake；MinerU失败不切basic。

## 复跑验证

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
& $python -m pytest -q -p pytest_asyncio.plugin
& $python -m ruff check src scripts test alembic
& $python -m pip check
& $python scripts\validate_data.py
& $python scripts\validate_temporal_local.py
& $python scripts\run_business_retrieval_eval.py --mode local-contract
# 当前异步演示及seed已运行
& $python scripts\validate_mcp.py
Push-Location frontend
node scripts/browser_documents.mjs
node scripts/browser_temporal.mjs
Pop-Location
```

validate_mcp需当前进程拥有与API/MCP一致的Local数据库和Temporal配置；从start_demo.ps1相同PowerShell运行最直接。各工具使用隔离项目与合成资料，浏览器脚本会创建测试记录。

Full/API配置成功后再运行validate_full_runtime.py（TEMPORAL_ENABLED=false）、validate_temporal.py（true）、run_business_retrieval_eval.py --mode full-api。真实模型开发集用run_business_eval.py --mode api；默认Fake只证明功能。每次输出独立目录，保留错误和源码hash，不能挑最好一轮。

## 故障处理

- 解析遗留indexing：查Temporal Activity是否已重试、document_ingest_claims的执行/attempt；重启Worker等待重派，不能手改indexed。旧attempt被围栏拒绝是预期保护。
- failed/index_failed：查安全错误类型及Activity历史。索引失败不是可检索完成；重试需保持相同资料身份。
- decision_pending停滞：决定已入库，启动Worker；正常Activity最长15秒轮询消费。裸Signal不能批准。
- terminal_sync_error或强制terminate/执行超时：可能未完成补偿；需查业务库/Workflow和预算并人工对账，当前无自动对账服务。
- Worker中断：重启run_temporal_worker.py，历史恢复调度；Activity可能再次执行，业务写入必须幂等。实际强杀/重启已测，生产容灾未测。
- 云端被拒绝：internal/restricted需要获准本地Provider；403 Embedding端点错误不生成伪造向量成绩。
- 预算reserved停滞：先查工作流后维护补偿，不能手改计数。Redis只做Checkpoint/限流/缓存，不是队列。

停止演示不会删除数据。备份业务库、原件及Temporal历史；Full还需备份PostgreSQL、MinIO和Redis。

## 前端依赖

当前frontend/node_modules为指向原项目的Junction，不允许通过它npm ci/install/升级或删除。新电脑/独立副本使用自己的依赖目录npm ci，再npm run dev。当前Vite缓存和dist均在本副本，详见[前端说明](../frontend/README.md)。
