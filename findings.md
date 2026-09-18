# 调研与实现发现

## 基线

- 源码来自天宫医疗 day05 知识问答 Agent。
- 源码已经包含 LangGraph Checkpoint、Milvus、Neo4j、Redis、MinIO、文档摄取和长期记忆雏形。
- 原始 day05 中的 inquiry 医疗流程、药品数据和医疗 Prompt 已从独立副本删除；入口已改为工程领域模块。
- 目标项目必须支持无 Key 的 Fake 模式，真实模型通过 OpenAI 兼容接口接入。

## 运行约束

- 项目 Conda 环境放在 F 盘，不使用默认 envs 目录。
- MinerU 现成环境位于 `F:\code\homework\project\1_membrane_project_precheck\runtime\envs\mineru`，版本 3.4.4。
- Temporal、DeepAgents 和 Kafka 使用可选依赖/Profile，不阻塞普通问答启动。
- 新项目已安装并验证 `deepagents==0.7.9`、`temporalio==1.32.0`、`aiokafka==0.14.0`、`pymilvus==2.6.17`、`neo4j==5.28.4` 和 `minio==7.2.20`。

## 安全与数据

- 公开资料保存来源、许可证、下载时间和 SHA-256。
- 公司内部文件、客户信息、真实合同和真实报价不得提交。
- 合成价格只能用于测试，不能描述为市场报价。

## 已实现链路

- 默认 `RUNTIME_MODE=local` 使用 F 盘项目内 SQLite、上传目录和 fixture，不依赖 Docker 或 API Key。
- `MODEL_MODE=api` 使用 DashScope/DeepSeek/OpenAI 兼容接口，失败时返回可识别的 Fake fallback 元数据。
- DeepAgents 只处理多文档资料包；Temporal 只处理长任务；Kafka 只处理批量事件。

## 2026-08-27 续作审计

- Git 起始状态为干净的 `main` 分支；会话恢复脚本未发现未同步内容。
- 当前自动化测试只有 3 条，不能证明 Full、DeepAgents、Temporal 或 Kafka 的真实链路。
- 原有 `MODEL_MODE=api` 失败后返回 Fake fallback 的行为不符合本轮验收要求，必须改为显式失败。
- DeepAgents、Temporal、Kafka 当前只能视为代码骨架/facade，真实链路通过前不得标记完成或写入简历。
- 后续读取 AgriGraph `.env.ai` 时只允许检查变量名并由脚本导入值，不得把 Secret 打印到终端或写入仓库文件。
- Provider 当前把 DashScope、DeepSeek、通用 Gateway 和 Embedding 共用 `BASE_URL_CHAT`；`MODEL_PROVIDER=auto` 无有效配置会选 Fake，API 调用/Embedding 失败也会静默返回 Fake。
- `EngineeringSupervisor.ainvoke()` 只调用 `append_short(..., "assistant", ...)`，没有保存用户消息；`_compose()` Prompt 只注入长期记忆，没有读取短期会话。
- `document_chunks` 不保存文件名，`search_chunks()` 只对正文 `_score()`，因此按上传文件名无法命中文档片段。
- `/health/deps` 只回显 MinerU 路径是否非空和各功能开关，没有探测数据库、Redis、MinIO、Milvus、Neo4j、Temporal、Kafka 或模型端点的可用性。

## 阶段 1 验收结果

- AgriGraph `.env.ai` 的白名单配置已安全导入本地 `.env`；该文件存在且被 Git 忽略，导入与验收输出均未显示 Secret。
- 实际配置解析为 Gateway 聊天模型和独立 Embedding 端点；真实聊天返回 token usage，真实 Embedding 返回 1024 维向量。
- API 模式 readiness 实测为 `ok`，数据库、模型端点和本地上传目录均实际可达；未启用组件明确报告 `disabled`。
- Fake 覆盖模式下 pytest 为 9 passed，Ruff 和 compileall 通过。

## 阶段 2 初始数据审计

- `public_cases.jsonl` 100 条、`synthetic_cases.jsonl` 100 条、fixture cases 5 条，案例数量已达目标。
- 膜材规格只有 3 条，价格只有 3 条，仓库内没有 PDF/DOCX/XLSX/TXT/MD 文档 fixture。
- 当前 `validate_data.py` 只要求 100 公开案例、50 合成案例，并仅检查规格/价格含 `source_url` 与 `synthetic`，无法覆盖新验收门禁。
- 需要把详细案例字段、40/60/30 数量、来源 URL、许可说明、抓取时间、SHA-256 和 synthetic 标记全部编码为校验规则。

## 阶段 2 验收结果

- 数据校验实测：100 公开案例、100 合成案例、5 fixture 案例、100 详细案例、43 条规格（40 公开）、60 条 synthetic 价格。
- 文档 fixture 为 10 PDF + 10 DOCX + 10 XLSX；连续重建 30 个文件的 SHA-256 变化数为 0。
- 公开规格来自 Birdair 托管的 Serge Ferrari 官方 Precontraint 502 技术表，只保存事实字段和源 PDF SHA，不提交公开 PDF 原文。
- 普通解析测试覆盖 PDF 页码、DOCX 和 XLSX；真实 MinerU 3.4.4 pipeline 测试通过，耗时 624 秒并返回 `parser=mineru`。
- pytest 为 13 passed、1 skipped（默认不重复运行昂贵 MinerU）；显式 MinerU 测试为 1 passed。Ruff、compileall 和数据校验通过。

## 阶段 3 验收结果

- Compose 六个默认依赖全部 healthy；因宿主已有服务，项目 Redis 使用 16379，MinIO 使用 19000/19001，未停止外部容器。
- Full 统一验收通过：PostgreSQL 205 案例、1 上传文档和 1 长期记忆；Redis 4 条短期消息与 20 个 LangGraph checkpoint key。
- MinIO 权威对象大小 1475 bytes；Milvus 2 个文档片段向量与 1 个长期记忆向量；Neo4j 205 个项目、615 条结构/膜材/场景关系。
- 文档检索来源同时包含 PostgreSQL 与 Milvus，并返回 `weighted_rrf(k=60)` 融合解释、页码、日期和版本；Full readiness 为 `ok`。
- 长期记忆查看/删除 API 已加入；Local/Fake 回归为 17 passed、1 skipped。

## 阶段 4 验收结果

- DeepAgents 0.7.9 使用 StateBackend 虚拟文件系统，仅允许读取 `/evidence/**`，工具白名单为 `ls/read_file`。
- Harness profile 排除 Shell `execute` 与所有写入/删除/任意搜索文件工具，禁用默认 general-purpose 子 Agent。
- 仅配置设计、膜材、价格三个子 Agent，真实 Gateway 模型完成双文档资料包审查。
- 真实报告 2132 字符、4 条证据；`package_reviews` 和 `package_review_evidence` 各持久化 1/4 条，GET API 回读与响应一致。
- Alembic 已升级到 `0002_package_reviews (head)`；Local/Fake 回归为 18 passed、1 skipped。

## 阶段 5 验收结果

- Temporal 1.29 + temporalio 1.32 真实服务可用，Temporal 与独立 PostgreSQL Compose 服务均 healthy。
- DocumentIngestWorkflow 实测 completed，重复提交复用相同 workflow_id；PackageReviewWorkflow 实测 approved 与 rejected，数据库状态同步。
- Activity 配置 schedule/start/heartbeat timeout、3 次指数退避 RetryPolicy、每 10 秒 heartbeat 和副作用幂等检查。
- Worker 在 heartbeat Activity 中途被终止，重启后同一 Workflow 恢复并 completed；先前因 Worker 注册失败滞留的 Workflow 也由修复后的 Worker 自动接续完成。
- 取消实测 Query state=`cancelled` 且 Temporal execution=`canceled`；Workflow 状态/approve/reject/cancel API 均走 Temporal handle。

## 阶段 6 验收结果

- Kafka 4.0 单节点 KRaft Broker Compose healthy；统一 EventEnvelope 包含 schema_version/event_id/type/aggregate/time/trace/payload/metadata。
- 批量导入在同一 PostgreSQL 事务写 batch_imports 与 2 条 Outbox；Relay 实测发布 3 条事件且标记 published。
- Consumer 实测 2 条 document.ingest.requested 提交 Temporal 并 completed，1 条故障事件写 Inbox failed 并发送 system.event.dlq。
- 按 event_id 重放保留原 ID；Consumer Inbox 将其识别为 duplicate，不重复提交长任务。
- Kafka 仅分发事件，Temporal 仍是 DocumentIngestWorkflow 的执行与状态权威；Redis 未承担队列职责。

## 最终发布门禁

- pytest 37 passed、1 skipped；真实 MinerU opt-in 测试已单独 1 passed（624 秒）。
- Ruff、compileall、pip check、Alembic `0003_kafka_outbox_inbox (head)`、Compose config 和数据校验通过。
- 九个 Compose 容器全部 healthy；Full readiness 对模型、PostgreSQL、Redis、MinIO、Milvus、Neo4j、Temporal、Kafka 全部返回 healthy。
- 冻结评测 `frozen_v1` 共 80 条，SHA-256 `675687d687f26eb13a15c90e58fad6487fcb67e21c9eb41ed6f49a4de3d20bfa`；最终 80/80 route、80/80 source、0 errors。
- gitleaks 本机未安装；已执行 tracked known-pattern 扫描和本地 `.env` API Key 值逐项 Git 对照，结果 clean，`.env` 被忽略。

## 2026-08-28 架构与简历复核

- 用户指出当前简历把 LangGraph、DeepAgents、Temporal、Kafka 等并列为主技术栈，可能造成“为展示而堆技术”的观感，需要回到真实工程职责重新分层。
- 已确认当前仓库实现了相关真实链路，但尚未证明这些能力都应进入同一条业务主链路或都应出现在简历技术栈中。
- 当前仓库没有批量任务耗时降低 45% 的前后性能基线；该数字不能作为已完成结果。
- 天宫医疗目录包含总览、Supervisor/记忆、MultiAgent、问诊、报告解读、多维知识库、MinerU、TruLens、NL2SQL 等原始 Markdown，后续以这些设计文档为架构对照来源。
- 天宫医疗总览强调“业务痛点映射技术挑战”，各数据库和模型由明确业务需求引入，不主张为了技术展示而并列堆叠。
- 天宫医疗 Supervisor/记忆示例以 `langchain.agents.create_agent` 创建 Agent；Redis `AsyncRedisSaver` 和 Milvus `BaseStore` 属于 LangGraph 运行时状态/记忆能力。这支持“LangChain Agent 抽象 -> LangGraph 运行时”的分层描述。
- DeepAgents 应定位为面向复杂、多步骤、文件上下文密集任务的 Agent Harness，而不应替代所有在线问答；膜结构项目中最适合它的边界是资料包深度审查。
- 初步目标架构：普通知识问答使用 LangChain `create_agent`；需要确定性状态流转时使用显式 LangGraph；多文档审查使用 DeepAgents；Temporal 只编排文档摄取/审查长任务；Kafka 只承接批量导入事件。
- 当前在线聊天入口调用自定义 `EngineeringSupervisor`，并未使用 LangChain `create_agent`；因此现状不能准确描述为“LangChain Agent 应用”。
- 当前 DeepAgents 仅在 `deep_review.py` 的多文档资料包审查中启用，边界本身合理；需要通过模块命名和应用服务进一步显式化，而不是把它列成通用在线框架。
- 当前 Package Review Router 同时处理同步执行、Temporal 提交、持久化和事件发布，职责偏重；应抽出应用服务统一控制同步/异步入口。
- 本地已安装 `langchain==1.3.17`、`deepagents==0.7.9`；`langchain.agents.create_agent` 与 `deepagents.create_deep_agent` 均返回 LangGraph `CompiledStateGraph`，证实它们不是互斥运行时，而是不同层次的抽象。
- `create_agent` 支持 tools、middleware、response_format、checkpointer 和 store；DeepAgents 在其上额外组合文件系统、子 Agent、摘要和 Harness 权限等中间件，适合资料密集的多步骤审查。
- 当前自定义 Supervisor 手工拼接短期消息，同时又编译 LangGraph Checkpoint，存在两套短期状态机制；在线 Agent 改造后应以 LangGraph Checkpointer 为对话状态权威，业务库只保留审计消息。
- 推荐代码边界：`RetrievalService` 隔离存储与融合；`KnowledgeChatAgent` 使用 LangChain Agent；`PackageReviewAgent` 使用 DeepAgents；应用服务负责同步/Temporal 提交与持久化；Router 只做协议适配。
- 天宫医疗 Neo4j 文档明确 PostgreSQL 与 Neo4j 是互补关系：前者负责事务/统计，后者仅负责多跳关系与路径推理；固定业务使用预写 Cypher，动态开放问题才考虑 NL2Cypher。
- 智慧问诊是独立的确定性 LangGraph StateGraph：维护 `InquiryState`，按 CLARIFY/GRAPH_QUERY/SYMPTOM_CONFIRM/CONCLUDE/HANDOFF 等阶段流转，并非所有 Worker 都手写 StateGraph。
- 症状标准化采用 LLM 结构化提取 -> Neo4j 精确验证 -> Milvus 语义兜底，技术按“口语与标准术语不一致”这一具体问题引入。
- 多维知识库被设计为独立基础设施，以 Doc RAG、GraphRAG、NL2SQL 三种工具服务其他 Agent；MinIO、Milvus、PostgreSQL、Neo4j 各自只承担对应数据形态。
- MultiAgent 文档明确 Master/Supervisor 有状态、Worker 无状态；五个 Worker 均用 LangChain `create_agent` 创建，再包装成 `@tool` 交给 Supervisor 调用，Supervisor 本身也由 `create_agent` 创建。
- Supervisor 的短期记忆仅由 LangGraph `AsyncRedisSaver` 管理，调用时传 `thread_id`；长期记忆通过 LangGraph `BaseStore` 协议和 Agent 工具主动读写 Milvus，不另造第二套手工聊天历史。
- 天宫医疗的“框架主线”因此是 LangChain Agent 抽象，LangGraph负责运行时状态和少数确定性业务图；课程核心链路没有使用 DeepAgents。
- 问诊完整实现给出明确规则：确定性、多节点、共享状态的业务流程才显式使用 LangGraph；持续问诊由 FastAPI + Redis 状态直接分流，绕过不确定的 ReAct Supervisor。
- 知识问答 Agent 本身仍由 LangChain `create_agent` 组装，调用 Doc RAG、GraphRAG、NL2SQL、多通道融合、处方审核五类工具；底层检索模块是普通 Python 服务，而不是再套一层 Agent 框架。
- 文档 RAG 按 HyDE -> Milvus Top-20 -> Reranker Top-5 -> 生成回答组织；GraphRAG 与 NL2SQL各自有 Schema/只读/重试边界，多通道仅在复杂问题时并行融合。
- MinerU 是文档摄取组件，生产建议大文件异步提交任务；它不属于模型层或在线 Agent 编排层。
- TruLens通过独立适配层追踪 retrieve/generate/query，不侵入每条检索实现；审计、实时幻觉检查和离线评估是三个不同职责。
- 天宫医疗总览从用户角色与业务痛点出发选择技术：患者多轮问诊、医生知识检索/图推理、运营结构化查询，基础设施先于 Agent 框架建设。
- 一份源数据分别映射到 PostgreSQL 业务事实、Neo4j 实体关系和 Milvus 文本/语义索引，强调同一事实的不同查询模型，而不是数据库相互替代。
- NL2SQL/ChatBI 是独立业务引擎，内部完成上下文判断、SQL生成、代码级安全校验、执行、图表推荐和摘要；它作为运营 Worker 的单一工具，不把数据库执行逻辑写进 Supervisor。
- 已覆盖天宫医疗目录全部 Markdown：总览、Neo4j、Supervisor记忆、MultiAgent、问诊设计/同义词/完整实现、知识问答、MinerU、TruLens、多通道评估、NL2SQL、模块索引、报告解读占位及源码 README。
- 当前膜结构 Neo4j 仅保存 `Project -> Structure/Material/Scenario` 三类一跳标签关系，查询只是关键词过滤后返回案例，不具备天宫医疗那类多跳推理价值；在补足关系模型前应降为可选案例关系检索，而不是主链路核心。
- 当前膜结构 PostgreSQL“关键词检索”是应用层字符串计数，不是 BM25；当前 RRF 只融合 PostgreSQL/SQLite 排名与 Milvus/Neo4j排名，不能直接宣称完整的混合检索优化体系。

## 2026-08-28 企业平台重构结论

- 当前运行架构已收敛为 LangChain `create_agent` + LangGraph Checkpointer + Temporal；DeepAgents、Neo4j、Kafka 已从运行时删除。
- KnowledgeAgent 采用应用层确定性检索后注入 Evidence，工具调用只是补充路径，避免模型跳过 RAG；真实 Gateway 已验证。
- Gateway thinking mode 不支持 LangChain structured-output 的 `tool_choice`；审查 Worker 改为无工具 `create_agent`、精确 JSON Schema、Pydantic 校验和一次修复重试，真实三 Worker 通过。
- Reranker 关闭时原实现按通道拼接后截断，导致结构化事实通道饥饿；改为各通道按 rank 轮询后，60 条精确检索 Recall@10 从 0 恢复到 1.0，MRR 为 0.3507。
- PostgreSQL 旧文档没有内容 SHA，迁移必须使用 `sha256 <> ''` 部分唯一索引；不能伪造旧文件内容哈希。
- 文档 Evidence 写入 PostgreSQL 后，Milvus 失败会保留 `index_failed`，不再把半完成文档暴露为 indexed。
- Redis 旧版 245 个 `membrane:short:*` 键已迁移清理；新 Full 验收只有 LangGraph Checkpoint，无双份会话历史。
- 真实验收已覆盖 Full、MinerU PDF、Office 图片 OCR、Temporal 20/重复20/50 批量、审批/退回、取消和 Worker 重启。
- 当前安全配置没有 Reranker endpoint/key，因此 qwen3-rerank 只能保留为可选能力；不得写成已真实验收。
- Recall@10=1.0 来自精确 ID 冻结集，只能作为回归门禁，不能描述为系统“准确率 100%”。困难查询纯向量基线、真实 Groundedness 和 5/20 文档性能仍待完成。

## 2026-08-28 第二轮产品化补强

- 用户截图中的 Swagger 只显示 7 条路径；只读检查发现 8080 对应 Uvicorn 创建于 2026-08-27，早于 `4a2d686` 重构提交，因此展示的是旧进程加载的 OpenAPI，不代表当前源码功能数量。
- 当前源码已有身份、项目、记忆、批量、工作流等 Router，但 tags/summary/Schema 仍以英文为主，三 Worker 结果也缺少专门的列表、证据和执行轨迹 API，产品可见性不足。
- 本地 `EMBEDDING_API_BASE` 指向阿里百炼 Workspace 的 `/compatible-mode/v1`，且独立 Embedding Key 已配置；可从同一 Workspace 根地址构造模型列表和 Rerank endpoint，无需复用 Gateway Key。
- 阿里云官方文档说明 `qwen3-rerank` 支持最多 500 个文档、单条最多 4,000 Token，RAG 场景使用 Workspace 下的兼容 Rerank API；请求字段为 model/query/documents/top_n/instruct。
- 官方模型列表 API 为 Workspace `/api/v1/models`；可以只返回模型 Code/能力元数据，不输出 API Key。
- 真实 `qwen3-rerank` 调用已通过：HTTP 200，目标 PTFE 规格片段排第 1，相关度 0.919566，本次 usage=95 Token；阿里 Workspace endpoint 与 Embedding Key 可直接复用。
- 同一 Workspace `/api/v1/models` 实际返回 20 个当前生成/视频模型；控制台截图中的 17 个是免费额度覆盖的向量/重排序 Model Code，两者不是同一目录语义，API 必须分开展示。
- 当前 `configure_full_local.ps1` 尚未从 Embedding Workspace 自动派生 Rerank URL/Key；需要安全写入本地 `.env`，不得把 Key加入 `.env.example` 或日志。
- 多 Agent 产品化采用受限 LLM `ReviewSupervisorAgent` 生成审查计划，Temporal/应用层继续负责权限、证据范围、并发、状态和持久化；业务执行 Agent 为 Design/Material/Price 三个 LangChain Worker。
- 当前 `agent_runs` 缺少 review/session 业务关联，无法从审查详情查询三 Worker 轨迹；需要新增 `business_id` 并通过 Alembic 迁移。
- 企业后台缺少文档列表/详情/Evidence、审查列表/Worker/Evidence/轨迹、用户列表、项目成员与预算读取接口；这些是“源码有功能但 Swagger 看不见”的主要原因。

## 2026-08-28 api.txt 连接测试

- `api.txt` 包含两组明文凭据：VibeAPI Chat 和阿里 Workspace；测试仅读取到内存，没有写入仓库或输出 Key。
- VibeAPI `deepseek-v4-flash`：单请求与同一 URL 三路并发均 HTTP 200，响应有正文且 `finish_reason=stop`，延迟约 2.8-3.2 秒。
- 阿里 Workspace `qwen3.7-plus`：单请求与三路并发均 HTTP 200，延迟约 0.8-1.4 秒。
- 阿里 Workspace `text-embedding-v4` 正确路径为 `/compatible-mode/v1/embeddings`：单请求与三路并发均 HTTP 200。
- 阿里 Workspace `qwen3-rerank` 正确路径为 `/compatible-api/v1/reranks`：单请求与三路并发均 HTTP 200并返回排序结果。
- 低并发实测不需要为三个 Agent 各开一个 API。更合理的是按任务配置一个 Chat 主端点、一个 Embedding、一个 Reranker 和一个 Review 端点；高并发用应用层限流/连接池/指数退避，只有主端点持续失败时才显式切换备用 Chat Provider。
- `api.txt` 仍是明文敏感文件，不能提交 Git或截图；如果曾经共享过文件内容，应在平台侧轮换凭据。
- 困难检索第三版使用正文不存在的SHA归档别名与语义干扰项：纯向量 Recall@10=0.5167/MRR=0.3274，混合+qwen3-rerank Recall@10=1.0/MRR=0.7083，Recall提升48.33个百分点。
- 未精排混合检索 Recall@10仍为0.5167，说明简单RRF不能替代Reranker；真实收益来自“多通道扩大候选 + qwen3-rerank重排”，不能只写“混合检索”笼统归因。

## 2026-08-28 当前项目 API 配置同步

- `api.txt` 的 URL 和 Key 行包含文字标签；同步脚本必须提取 `https://...` 子串和冒号后的 Key，不能把标签写入 Base URL 或 Authorization。
- 当前膜结构项目 `.env` 已按两组凭据配置：VibeAPI 负责 Gateway/DeepSeek Chat，阿里 Workspace 负责 DashScope 兼容 Review、Embedding 和 Reranker。
- 真实代码级验证结果为 Chat 正常返回、Embedding 1024 维、qwen3-rerank 目标片段 Top-1、Review JSON 正常返回；同一 Chat URL 三路并发通过。
- 仅同步当前项目；其他项目环境保持原状，待后续单独迁移并保留各自专属变量。

## 2026-08-28 LLM Supervisor 接入

- 三领域审查现为 `ReviewSupervisorAgent -> Design/Material/PriceReviewAgent` 的多智能体链路；Supervisor 只能从固定 Worker 白名单中选择，不接收工具权限，不写数据库。
- Fake 模式使用确定性全量计划，API 模式使用阿里 Workspace `qwen3.7-flash` JSON 计划；真实计划调用返回三个 Worker，随后完整三 Worker 审查返回 `langchain-supervisor-multi-agent`。

## 2026-08-28 审查闭环与部署环境

- 工程规则与 Agent 分工：确定性代码负责完整性、字段/版本一致性、膜材与价格可比性；Supervisor 只选择白名单 Worker；领域 Worker 只解释非结构化资料和歧义。这样不会让模型直接修改事实或流程状态。
- `ReviewIssue` 是统一业务对象，引用 `evidence_id` 并冗余保存文件名、页码/Office 定位和版本，避免报告引用不能回溯原资料。审批人对问题单状态的修改使用乐观锁。
- 文档向量不能跨 Embedding 模型复用；`documents.embedding_model` 与 Milvus 元数据在索引成功后同步记录，检索只读取当前模型指纹，`reindex_full_embeddings.py` 负责补偿重建。
- 困难检索 v3 的纯向量 Recall@10=0.6500，混合候选配合 `qwen3-rerank`=1.0，MRR=0.5254/0.8333；属于固定合成回归集，不能外推为工程知识总体准确率。
- 真实资料包 v3 的 5/20 文档测试均记录完成情况、引用、Groundedness、Token、估算成本和 p50/p95；这些值仅可用于同机同模型同资料的前后比较。
- 项目可迁移环境为 Conda prefix `F:\code\homework\conda-envs\agent-membrane`。`base` 仅提供 Conda 管理器；运行和脚本验证都必须使用该 prefix 的 Python。MinerU 保持单独环境，避免其依赖污染应用环境。

## 2026-08-29 最终验收复跑

- 使用 `F:\code\homework\conda-envs\agent-membrane\python.exe` 执行默认测试，结果为 `63 passed, 2 skipped`；未发现 Ruff、依赖或编译错误。
- 显式开启 `RUN_MINERU_TEST=1` 与 `RUN_MINERU_OFFICE_OCR_TEST=1` 后，真实解析测试为 `11 passed`；最后一项 Office 图片 OCR 使用独立 MinerU 环境完成。
- Temporal 复验输出：`document_ingest=completed`、`batch_20=completed`、`batch_20_duplicate=completed`、`batch_50=completed`、`approved_review=approved`、`rejected_review=rejected`、`cancellation=cancelled`、`worker_restart=completed`。
- 当前 8080 端口服务的 `/health/deps` 返回所有已启用依赖 `healthy=true`，OpenAPI 共 49 个操作；旧的 7 路由截图不再代表当前服务。
- 验收结论是“后端主链路可验收”，不是生产级工程安全软件验收。前端、正式扫描/混合 PDF 大矩阵和真实工程准确率仍属于后续边界；当前工作区未创建提交。

## 2026-08-29 MCP 接入审计

- 当前项目环境未安装 `mcp`/`fastmcp`，源码也没有 MCP Client/Server；现有工具是 LangChain `@tool`，因此必须真实实现并验收后才能写入简历。
- MCP 最合适的边界是外部 Agent 到企业资料平台，不用于替换 KnowledgeAgent、ReviewSupervisor 或 Temporal，也不让内部模块绕行 MCP。
- 项目已有 `Principal`、`require_project_role`、项目成员表和资料分级，可复用为 MCP 工具的身份与 ProjectScope；工具参数中的 `project_id` 不是权限凭证。
- 文档、Evidence、膜材规格、价格和审查状态已有存储/检索方法。MCP 层应做薄适配，不能复制 PostgreSQL、Milvus 或 MinIO 查询逻辑。
- 现有 `agent_runs/agent_steps` 表描述模型执行轨迹，不适合作为协议调用审计；MCP 调用需要独立表记录工具、调用者、项目、耗时、结果状态与错误类型。
- stdio 没有 HTTP Authorization Header，只适用于可信本地进程；远程 Streamable HTTP 必须校验 Bearer Token，并从令牌取得调用者身份。
- MCP Elicitation 是服务端主动请求，Streamable HTTP 需要 SSE 双向会话；纯 JSON 响应会让写工具等待至客户端超时。客户端未声明 Elicitation 能力时应在调用前直接 fail closed。
- 领域 Skill 只描述如何组合 MCP 工具并保留人工确认边界，不能复制权限、检索或工作流实现，也不能把 Skill 当作第五个业务 Agent。
- 清理前核对 `.env`：当前本地数据库为 `data/runtime/engineering.db`；`engineering-rebuilt.db` 为旧副本已删除，原始上传文件和 Compose 数据目录未删除。

## 2026-08-30 企业前端与 MCP v2 基线

- 当前仓库没有 `frontend/`、`package.json` 或既有前端设计系统，需要新建独立 Vue 工程。
- 后端缺少前端完整工作台所需的项目聚合总览、批次列表、预算更新和规格/价格台账 REST 接口。
- 规格与价格已有 PostgreSQL 规范化字段和租户/项目检索过滤，但缺少状态、乐观锁、创建者和更新时间。
- 当前 MCP 为 `mcp==1.29.1`，实现 9 个 Tool、v1 Streamable HTTP/stdio、短期 Bearer Token、Elicitation、幂等和审计；尚无 Resource Template。
- 官方 Python SDK 当前稳定主线为 v2，实施需以安装后的 v2 API 为准，不能沿用 v1 `FastMCP/ClientSession` 假设。
- 前端视觉方向已确定为浅灰白/石墨/青绿的高信息密度工程控制台；当前会话无直接图像生成工具，视觉稿不可伪造为已完成。

## 2026-08-29 最终整合基线

- 当前业务数据实际由100条公开案例、100条 synthetic 案例和5条手工测试 Fixture 组成；最终业务口径应为200条案例，5条 Fixture 单独管理。
- 云端 KnowledgeAgent 继续保留项目级非公开资料拒绝策略，避免当前调用链在证据选择前构造云模型；未来按本次 Evidence 放宽时必须先完成端到端脱敏与零云请求测试。
- `material_specs` 和 `price_records` 当前缺少 tenant/project/visibility 归属，不能直接对 MCP 或企业检索宣称完整项目隔离。
- Milvus 已保存 tenant/project/classification/embedding_model 元数据，但当前查询只过滤 project 和 embedding_model；需要补 tenant 与 classification。
- Gate A 结果为 `63 passed, 2 skipped`，Alembic head=`0008_document_embedding_model`，PostgreSQL、Redis、MinIO、Milvus、etcd、Temporal 与 Temporal PostgreSQL均 healthy。

## 2026-08-28 数据与 PDF 核查

- 当前公开案例爬虫原先只解析 TensiNet 列表页，100 条记录的应用、年份和膜材字段大量为空；它不是公开 PDF 文档下载器。
- 当前仓库的 10 个合成 PDF fixture 每个 2 页；Birdair `GB_Precontraint_Carte_502.pdf` 在线源文件 7 页，40 条规格数据来自其中第 3 页的表格。
- 基础解析和真实 MinerU pipeline 都能返回两个 fixture 页码；因此“PDF 只有一页”更可能来自旧运行库/查看了单页文本 fixture，而非 MinerU 截断。
- 详情页增强后，公开案例保留列表页 provenance，同时增加 `detail_source_url`、`detail_source_sha256`、`detail_status`；网络失败不再静默写入空详情。
- `data/runtime/engineering.db` 属于被旧 Uvicorn 进程占用的历史运行库，且 schema 缺少当前规范化字段；新建 `engineering-rebuilt.db` 后重新 seed，205/43/60 计数和详情/页码质量均通过。
- 5 条首次详情请求的失败均可重试成功；采集器已加入最多 3 次指数退避，最终 100 条公开案例均有 `detail_status=ok`，但缺失年份/膜材仍按源页面实际缺失保留为空。
## 2026-09-03 pgvector 迁移

- 当前 Milvus 仅保存 EvidenceUnit 和已确认长期记忆的向量副本；业务事实、权限、文档状态和记忆状态仍以 PostgreSQL 为准。
- 该项目是单公司内部 Docker Compose 应用，向量规模没有达到必须独立部署 Milvus 的程度；将向量索引收敛到 PostgreSQL + pgvector 可以移除 Milvus、etcd 两个服务及其独立备份、健康检查和数据一致性链路。
- 迁移保持 `index_document/search_documents/index_memory/search_memories/delete_memory` 上层接口不变，混合检索仍为结构化/关键词通道 + 向量通道 + weighted RRF + Reranker。
- pgvector 表只保存可重建的向量索引与检索元数据，不改变 PostgreSQL 现有业务表的权威边界；Embedding 维度仍固定为 1024，切换维度需要 schema 迁移和重建索引。
- 真实迁移后 `document_embeddings` 覆盖 751 份已索引资料、966 条 Evidence 向量，`memory_embeddings` 保存 12 条确认记忆；vector 扩展为 0.8.6，cosine distance 查询正常。
- pgvector 版困难检索 v3：纯向量 Recall@10=0.5000/MRR=0.4625，混合+qwen3-rerank Recall@10=1.0000/MRR=0.7083，MRR 相对提升约 53.15%；简历继续使用保守口径“Recall@10 90%+、MRR 提升约 30%”。
