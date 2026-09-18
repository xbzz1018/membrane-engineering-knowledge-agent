# 膜结构企业资料审查平台实施计划

## 目标与边界

单公司内部 Docker Compose 工程资料智能审查平台，按项目隔离设计、膜材、价格和审查资料，形成资料入库、知识检索、多 Agent 审查和人工复核闭环；保持技术栈聚焦，不加入 A2A/Kubernetes，不提交企业内部资料或密钥。

## 已完成

- [x] 企业基础：JWT、管理员/设计/膜材采购/审核人、项目成员与服务端 ProjectScope。
- [x] 架构收敛：删除 DeepAgents、Neo4j、Kafka；LangChain Agent + LangGraph Checkpointer + Temporal。
- [x] 数据模型：PostgreSQL 业务事实/权限/审查/问题单/记忆/预算/运行摘要，迁移到 `0008`。
- [x] 文档智能：PDF MinerU auto/text/ocr；DOCX/XLSX 原生解析和嵌图 OCR；EvidenceUnit、SHA、版本和显式失败。
- [x] 存储：MinIO 原件/派生图片、PostgreSQL/pgvector 文档与确认记忆向量、Redis Checkpoint/限流。
- [x] RAG：项目过滤、PostgreSQL 规范化字段与 pgvector 向量召回、通道轮询、带权 RRF、可选 Reranker。
- [x] Agent：KnowledgeAgent、LLM ReviewSupervisor、Design/Material/Price Review Worker、JSON Schema 与 Evidence ID 校验、Map-Reduce。
- [x] 工程审查：确定性完整性/版本/膜材厚度/价格可比性规则，统一问题单、稳定证据定位和审核人状态更新。
- [x] 记忆：pending 候选、确认/拒绝/更新/删除；更新后重新确认，记忆不作为证据。
- [x] Temporal：单文档、20/50 批量、资料包审查、Retry/Heartbeat/Query/Signal/Cancellation、Worker 重启恢复。
- [x] 工程控制：文档条件锁、审批首决定、Token/成本周期预算、Redis 令牌桶、GET+SSE、OTel 安全元数据。
- [x] 合同：OpenAPI、RBAC、状态机、错误码、SSE 和 frontend contract。

## 当前验收证据

- Local/Fake pytest：最终 76 passed，2 个真实 MinerU opt-in 测试默认跳过。
- 真实 MinerU：PDF 1 passed；DOCX/XLSX 嵌图 OCR 1 passed。
- Full：真实模型、Embedding、PostgreSQL/pgvector、Redis Checkpoint、MinIO、确认记忆与 health 通过。
- Temporal：20 份、重复 20 份、50 份批量，批准/退回、取消和 Worker 重启恢复通过。
- 困难检索 v3：60 条，最新重跑纯向量 Recall@10=0.5000，混合 + `qwen3-rerank`=1.0，提升 50 个百分点；仅作为固定回归集结果。
- 真实资料包 v3：5/20 文档分别完成 Groundedness、引用覆盖、Token、成本估算和 p50/p95 记录；只用于该机器、模型和合成资料的回归对照。
- Ruff、compileall、pip check、Compose config、7 个服务 health、数据校验、Alembic 和 Secret 扫描通过。

## 尚未完成

- [x] 阶段 13：阿里模型能力与真实 Reranker
  - 安全探测本地阿里端点支持的模型与协议，不输出 Key。
  - 配置并真实验收 `qwen3-rerank`，记录模型、延迟和候选缩减结果。
  - 增加只读模型能力 API，展示当前 Chat/Embedding/Reranker 策略与可用状态。
- [x] 阶段 14：多 Agent 产品化与OpenAPI功能完整性
  - 保留确定性 Supervisor，由 Design/Material/Price 三个 LangChain Worker 并行审查。
  - 增加 Worker 状态、领域结果、证据、冲突、Agent Run/Step 和审查列表 API。
  - 增加文档列表/详情/Evidence、项目预算、用户列表等企业后台必要读接口。
  - Swagger 用于确认功能接口完整，不把界面中文化作为验收项。
- [x] 阶段 15：困难检索与真实模型评测
  - 建立困难查询纯向量基线 vs 混合检索 + Reranker 对照，验证 Recall@10 至少提升 5 个百分点。
  - 对真实模型 5/20 文档资料包记录 Groundedness、引用覆盖、冲突 F1、Token、成本和 p50/p95。
  - 验证所有 EvidenceUnit processed/skipped/failed 状态，无静默丢失或截断成功。
- [x] 阶段 16：解析矩阵与安全并发
  - 扩充扫描/混合 PDF、DOCX/XLSX 嵌图等 16 份正式 Fixture 并保存逐份结果。
  - 完成角色越权、项目/记忆隔离、预算并发、审批并发、重复上传和受限资料零云请求攻击测试。
- [x] 阶段 17：中文交付与实习项目评估
  - 架构、运行方式、前端合同、README 和验收报告全部中文化；Swagger 不做专门语言要求。
  - 完成全门禁、Secret 扫描、提交和三个月实习工作量/简历边界评估。

## 完成规则

未通过当前架构真实链路的能力不得写入简历。不能把精确冻结集的 1.0 包装成“系统准确率 100%”，也不能预设批量耗时降低 45%。外部 API Key 只存在被 Git 忽略的本地 `.env`，任何日志、结果和提交都不得包含密钥或模型正文。

## 附加配置变更

- [x] 当前项目 API 配置已从本机凭据文件同步；项目 1、2、3 暂不修改。
- [x] Chat、Embedding、Reranker、Review 真实连通性和同一 Chat URL 三路并发已验证。

## 数据质量补强

- [x] 公开案例详情页字段、失败状态和详情页 provenance 已补齐。
- [x] PDF fixture 与公开规格源文件页数已核验，manifest/校验会拒绝单页或页数不一致。
- [x] 业务数据库按当前 schema 保持 200 条案例、43 条规格和 60 条价格；5 条手工案例独立作为测试 Fixture。

## LLM Supervisor 补强

- [x] ReviewSupervisorAgent 使用 LangChain `create_agent` 生成固定白名单内的三领域审查计划。
- [x] 真实 API 和 Full 单资料链路已验证 Supervisor、三个 Worker 并行执行及报告合并。

## 2026-08-28 最终补强与环境迁移

- [x] 规则校验位于 LLM 调用前后：LLM 只能解释歧义，不能修改业务事实、权限或工作流状态。
- [x] 审查报告保存 Supervisor 计划、Worker 结果、问题单、Evidence 位置、Token 和审批状态；审核人可通过乐观锁更新问题单状态。
- [x] 文档向量记录 `embedding_model` 指纹；切换 Embedding 模型后可执行 `scripts/reindex_full_embeddings.py`，避免新查询模型检索旧向量。
- [x] `environment.yml`、`requirements-full.txt`、`scripts/setup_env.ps1` 和 `scripts/verify_env.ps1` 支持在任意机器重建 `agent-membrane` Conda prefix 环境；运行命令固定使用该环境 Python，不依赖 `base`。
- [x] 当前验收：数据校验、Alembic `0008`、Ruff、pip check、Full 真实依赖检查、Temporal 审批/退回/取消/恢复均通过。

## 阶段 18：MCP 企业工具服务

- [x] 使用官方 Python MCP SDK 建立独立 MCP Server，保留现有 FastAPI/Agent/Temporal 主链路。
- [x] 暴露 `search_project_documents`、`get_document_evidence`、`query_material_specs`、`query_price_records`、`get_review_status` 五个只读工具。
- [x] MCP 工具只调用现有业务服务；每次调用由服务端身份生成 `Principal + ProjectScope`，拒绝跨项目访问。
- [x] stdio 仅用于本地 Inspector/桌面宿主；Streamable HTTP 使用 Bearer Token 校验，不把 stdio 当作远程鉴权通道。
- [x] 默认只允许 MCP 返回 `public` 文档证据；价格结果保留日期、区域、币种、单位、来源和 `synthetic` 标记。
- [x] PostgreSQL 保存工具名、用户、项目、耗时、状态与错误类型，不保存密钥、Prompt 或完整资料正文。
- [x] 覆盖工具发现、结构化输出、无令牌、跨项目越权、受限资料、错误参数、超时和不存在数据测试。
- [x] 使用官方 MCP Client 验证 stdio 和 Streamable HTTP；全量回归通过后才将 MCP 写入简历。

## 阶段 19：最终架构整合实施

- [x] Gate A：保存当前 Local/Full/MinerU/Temporal/检索基线，确认所有改动均使用 F 盘 `agent-membrane` 环境。
- [x] Gate B：业务案例口径调整为 100 公开 + 100 synthetic；5 条手工案例迁入测试 Fixture；规格与价格补齐 tenant/project/visibility。
- [x] Gate C：PostgreSQL 与 Milvus 检索统一执行 tenant/project/classification/embedding_model 过滤。
- [x] Gate D：抽取 Authorization、KnowledgeQuery、PackageReview 三个应用服务，FastAPI 契约保持兼容。
- [x] Gate E：KnowledgeAgent 拆为四个专业 Function Tools，删除重复检索；审查增加 full/focused 模式和版本化 Prompt Catalog。
- [x] Gate F：保持三领域 Worker Evidence 注入和结构化输出，重新验证 Temporal Map-Reduce、审批、取消与恢复。
- [x] Gate G：实现官方 MCP SDK、一个 `/mcp` Streamable HTTP 端点、stdio 查询模式、九个工具、Scope、幂等、Elicitation 与安全审计。
- [x] Gate H：创建并校验一个 `membrane-package-review` Skill；Skill 不保存凭据、不越权、不自动批准。
- [x] Gate I：整合代码目录、文档、脚本与评测集；保留完整 Alembic 历史。
- [x] Gate J：通过所有门禁后清理缓存、临时数据库和旧 Kafka/Neo4j 卷；保留 uploads 与当前有效数据库/存储卷。
- [x] Gate K：重启服务，执行 pytest、Ruff、pip check、Alembic、数据、MinerU、Temporal、MCP、Compose 健康和 Secret 扫描。

## 阶段 20：企业台账、MCP v2 与 Vue 工作台

- [x] Gate L：保存当前 76 项测试、Full、Temporal、MCP v1 和工作区基线，确认不重置历史改动。
- [x] Gate M：增加 `0012_enterprise_frontend_contract`，补齐规格/价格状态、乐观锁、创建者和时间字段。
- [x] Gate N：实现项目总览、批次列表、预算更新、膜材规格和历史价格台账 API，并更新 OpenAPI/RBAC 测试。
- [x] Gate O：迁移 MCP Python SDK v2，保留 9 个 Tool，新增 3 个 Resource Template 和 v2 Elicitation/Origin 校验。
- [x] Gate P：更新并校验 `membrane-package-review` Skill，完成 MCP v2 官方 Client 双传输验收。
- [x] Gate Q：创建 Vue 3 + TypeScript + Vite + Element Plus 前端基础工程、登录、项目权限与 API/SSE 数据层。
- [x] Gate R：实现总览、资料、膜材、价格、问答、审查、问题单、批次、记忆和管理页面。
- [x] Gate S：完成 Vitest、构建、Playwright 真实联调与桌面/1024/窄屏视觉 QA。
- [x] Gate T：更新架构、运行手册、前端合同和验收报告，清理缓存并重启全部服务。

## 阶段 21：面试导学与项目面经

- [x] Gate U：恢复当前架构、代码、验收指标、简历口径与能力边界。
- [x] Gate V：将学习顺序、源码路径、核心原理、技术取舍和验证方法合并到综合项目文档。
- [x] Gate W：删除独立导学/面经题库，只保留项目背景、技术实现、评测与代码阐述。
- [x] Gate X：校验指标、术语、代码位置和业务场景，确保综合文档与当前代码一致。

## 阶段 22：可复制源码上下文包

- [x] Gate Y：直接以主仓库作为源码交付，不维护重复源码副本，避免后续代码漂移。
- [x] Gate Z：将项目背景、架构、技术栈、评测、Skill 和源码导航合并到 `面试准备-膜构智审-综合版.md`。
- [x] Gate AA：保留 `.env`、上传资料和 Docker 有效数据，但通过 `.gitignore` 与源码导航隔离运行数据、缓存和依赖目录。
- [x] Gate AB：删除旧导学/面经、重复源码包、Python 缓存和前端构建结果，将设计验收文档归入 `docs/`。

## 阶段 23：Milvus 迁移至 pgvector

- [x] Gate AC：盘点 Milvus 的文档向量、确认记忆、健康检查、部署与文档依赖。
- [x] Gate AD：新增 pgvector Alembic schema 与存储适配器，保持上层检索和记忆接口兼容。
- [x] Gate AE：将 Full 模式部署收敛为 PostgreSQL + pgvector，移除 Milvus/etcd 运行依赖。
- [x] Gate AF：更新验证脚本、单元测试、架构文档和综合项目说明。
- [x] Gate AG：执行迁移、静态检查与回归验证，并同步 Agent 开发实习经历口径。
