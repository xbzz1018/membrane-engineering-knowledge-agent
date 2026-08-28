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
