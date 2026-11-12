# 架构说明

当前实测以 [current-validation.md](current-validation.md) 为准。以下 Full 组件图描述代码设计，不表示本轮实际启动了全部服务。

## 主链路

项目方案增量详见[实现与交付](project-plan-delivery-2026-11-03.md)：生成请求进入独立ProjectGenerationWorkflow，检索/材料工具并发取证，来源快照与生成草稿分离，复用ReviewAgent审查，持久决定消费后批准同版内容。ProjectExportWorkflow确定性生成MD/Word；修改新版本使旧批准失去当前交付效力。方案使用新增五表与独立Workflow类型，资料包原流程保留。

```mermaid
flowchart TD
    U[企业用户 / JWT] --> API[FastAPI + 项目权限]
    H[外部 Agent / MCP Host] --> MCP[MCP Gateway]
    API --> APP[应用服务层]
    MCP --> APP
    APP --> DOC[资料上传、版本与分级]
    DOC --> P[PDF MinerU / Office 原生解析与 OCR]
    P --> E[EvidenceUnit: 文件、页码、位置、版本、SHA]
    E --> PG[(PostgreSQL 业务事实)]
    E --> V[(pgvector 向量索引)]
    APP --> KA[ConversationSupervisor：结构化意图与服务端策略]
    KA --> GK[通用概念直接回答]
    KA --> QT[检索 / 材料查询子Agent工具]
    APP --> T[Temporal 长任务]
    T --> S[ReviewSupervisorAgent]
    S --> R[确定性工程规则]
    S --> DT[review_retrieval 工具]
    S --> MT[review_material 工具]
    DT --> CT[review_review 工具]
    MT --> CT
    DT --> D[RetrievalAgent]
    MT --> M[MaterialAgent]
    CT --> C[ReviewAgent]
    D --> I[结构化问题单、证据、人工审批]
    M --> I
    C --> I
    I --> PG
    KA --> CH[(PostgreSQL 范围化会话审计)]
```

本地模式使用SQLite、文件目录，可显式选择Fake/API模型及Temporal；当前演示为Local/Fake配真实Temporal开发Server。Full存储使用PostgreSQL/pgvector、Redis和MinIO，模型是否可用由端点及资料分级决定。

## 存储职责

| 组件 | 职责 |
|---|---|
| PostgreSQL | 用户、项目、文档元数据、Evidence、报告、问题单、预算、运行摘要和长期记忆权威记录 |
| pgvector | PostgreSQL 内的 Evidence 与已确认长期记忆向量索引，使用 cosine distance 与 HNSW 索引 |
| Redis | LangGraph 24 小时会话 Checkpoint、接口令牌桶和热点缓存 |
| MinIO | 按文件内容哈希与版本保存原件，按图片哈希保存派生 OCR 图片 |
| Temporal | 文档解析、批量导入、资料包审查、重试、恢复、查询、审批、退回和取消 |

PostgreSQL 先写入 Evidence，再写入同库中可重建的 pgvector 索引；索引成功后资料才会成为 `indexed`。向量失败必须保留 `index_failed`，不能把半完成资料暴露给检索。

## 应用服务与工具边界

FastAPI 与 MCP 共同调用 `ProjectAuthorizationService`、`KnowledgeQueryService` 和 `PackageReviewApplicationService`。协议层不直接实现权限、检索、预算或 Temporal 操作。

`/api/v1/chat`及其SSE接口现调用ConversationSupervisor。API模式先由LangChain模型输出受Schema限制的意图，服务端校验企业事实取证要求、派生角色及执行顺序，再调用`query_retrieval`或`query_material`工具。无依赖并发；先查项目才能知道型号时顺序执行，型号不明确则澄清。通用概念直接回答，普通问答不调用独立ReviewAgent。Fake显式使用规则分类和实际授权查询工具，不冒充模型推理。

查询角色复用KnowledgeAgent的四类底层工具：`search_project_documents`、`query_material_specs`、`query_price_records`、`get_document_evidence`；仅暴露该角色需要的集合。Principal与项目由服务端闭包绑定，文档读取也校验当前项目。项目事实仍强制当前调用返回的Evidence，不能用“允许直接回答”绕过精确参数取证。最终合并为确定性带来源分段，不额外用模型重写。生成项目意图受理独立方案任务；资料包审查意图仍提示已有接口，不自动提交任务。方案任务复用两种查询角色，冻结来源后生成结构化正文，再用ProjectReviewAdapter调用既有ReviewAgent，不重复启动整套资料包取证。

当前动态问答从PostgreSQL/Local SQLite的既有conversations审计表读取最近6条上下文，session键由租户、用户、项目及客户端session做SHA-256派生，不混读旧的无项目范围会话。查询子Agent不复用持久Checkpoint，因此不把历史ToolMessage当本轮证据。旧KnowledgeAgent入口保留其Redis/InMemory Checkpointer兼容路径，但不是当前Chat API默认入口。此增量不改表结构。

MCP Streamable HTTP 提供五个查询工具和四个需要 Scope、幂等键及 Elicitation 的工作流工具；stdio 只提供查询工具。MCP 首版只返回 `public` 资料，不上传、删除、改价或修改问题单，也不参与内部多 Agent 调度。

## 可选任务Adapter（2026-11-12）

`LORA_TASKS_ENABLED`默认关闭。启用时，API查询角色在资料分级门禁后调用查询标准化任务，保留原始问题，字面型号/日期/版次不一致时拒用改写。领域审查及规则合并后，可调用审查整理任务，输入既有问题和相关原始证据，输出仅附加为辅助说明；结构化问题、状态与批准权限仍由原流程控制。Temporal调用在Activity内并持续Heartbeat，没有改变旧资料包Workflow的命令顺序。

两任务由`LORA_API_BASE`共享端点、`LORA_QUERY_MODEL`和`LORA_REVIEW_MODEL`不同别名选择；Supervisor及通用Agent继续使用原Provider配置。失败显式返回，不切Fake。字面标识与引用检查不能证明完整语义正确，整理内容需人工复核。公司模型、本地0.6B实验与当前接入的证据边界见[模型适配说明](model-adaptation.md)；本地JSON任务Adapter不能直接替代平台的纯文本业务任务。

## 文档与权限

- Full模式PDF强制使用MinerU auto/text/ocr；basic用于Local开发/合成回归，不能冒充MinerU验收。
- DOCX 提取段落、标题路径、表格和嵌图位置；XLSX 提取工作表、单元格和锚定图片位置。
- 每个 EvidenceUnit 保留稳定 ID、文档/版本、页码或 Office 定位、解析类型、OCR 标记、文本 SHA 和处理状态。
- 资料分为 `public/internal/restricted`。云端模型只能处理 `public` 资料，服务端而不是模型决定权限。

## 审查与问题单

2026-11-03 复现副本更新了 `DomainAgentTools`：在线 `PackageReviewService.run` 先制定计划，再由带工具的 LangChain Supervisor 调用 `review_retrieval/review_material/review_review`。每个工具在服务端闭包内绑定已授权的 Evidence 和记忆，并调用对应领域 Agent；同一请求内重复调用复用结果。工具 Schema 不接受身份、项目或文档 ID。最终报告从实际工具输出构建，Supervisor 文本不能替代领域结果。

本地 Fake 模式显式使用脚本模型产生 Tool Calls，实际运行 LangChain 工具分发；确定性规则检查全包，领域工具不伪造模型发现或Token。API 模式使用配置的聊天模型执行工具选择和领域审查，失败不降级为 Fake。旧协议曾出现21/24通过、2误报、1结构失败。2026-11-02已将模型输出与报告字段拆分，增加引文校验与比较门禁；新协议记录每条额外阻断发现，结果见当前验证。

Temporal保留计划Activity和三个独立领域Activity，领域级独立重试；review_worker_activity也通过同一个领域工具执行。Workflow固定先并行检索/材料，随后传入两路摘要执行审查；LLM仅放Activity。真实开发Server已验证Worker强杀/恢复、审批离线提交、取消及5份本次历史重放，业务存储SQLite、模型Fake；不外推生产故障切换或旧历史迁移。

`full`必须覆盖retrieval/material/review三个角色；API模式使用受限LangChain Supervisor规划，full不可遗漏角色，focused选择review时自动补齐取证依赖。在线流程由Supervisor分两阶段调用工具，检索/材料先并行，审查随后执行。Fake模式使用确定性计划和脚本模型，不冒充真实LLM。计划阶段不提供工具；后续在线调度阶段仅提供已绑定资料范围的领域 Agent 工具，不提供 Shell、任意公网、文件写入、权限或数据库写入能力。

Evidence 在审查阶段采用多标签路由：跨领域片段可以同时进入多个 Worker，无明确领域特征的片段作为共享 Evidence。首次调用后逐领域核对各自应处理的 `processed/skipped` 集合，不能由其他领域的 processed 抵消本领域漏审；未报告状态不自动算处理，最多补审一轮。仍有缺口则生成 `evidence_coverage_gap` 并进入人工复核。`focused` 只在已选领域内补审，`full` 覆盖三个领域。

在 Worker 前后执行作用域明确的规则：独立资料完整性、相同文件编号有效版次、同型号/适用版本的名义厚度与单位归一、设计引用与适用规格对齐、价格地区/税/币种和历史日期可比性。缺失适用性转人工，独立文件版次不同不报冲突。规则对复杂表格和产品命名仍有限，详见业务范围。LLM补充发现仍会误报，引用ID合法不能代替语义审查。

每个问题单包含编号、领域、类型、严重级别、实际/预期值、建议、处理状态与证据定位。领域归属、编号、定位和状态由服务端控制；worker选择错误、不可见/未处理引用均拒绝。审核人用乐观锁事务处理问题、批准或退回，未处理阻断问题不能批准。忽略/退回要原因，终态禁止修改；当前审计事件在usage JSON内。

`RetrievalAgent`在冻结包内调用只读查询工具整理证据；`MaterialAgent`查询包内规格并核对参数/单位；`ReviewAgent`以原始Evidence复核上游结果与跨文档一致性。设计/材料/价格仍是资料和业务检查类型，价格不再对应独立Agent，且未提交价格不阻断普通设计/规格审查。项目级PostgreSQL/pgvector检索与冻结包内snapshot_lexical查询范围不同，不能混称。

Prompt Catalog新增`conversation-router/v1`、`general-knowledge/v1`、`retrieval-query/v1`和`material-query/v1`；保留 `knowledge/v1`、`review-supervisor/v2`、`review-delegator/v2`、`retrieval-review/v2`、`material-review/v2`、`review-review/v2`。`review-supervisor` 是计划阶段，`review-delegator` 是在线工具调度阶段。Agent Run 保存名称、版本和 SHA，不保存完整 Prompt、Evidence 正文或隐藏思维链。

## 工作流与观测

- `document-parse`：单份资料解析、OCR 和索引，解析 Worker 并发 1。
- `agent-review`：Supervisor、领域 Worker 和报告合并，Worker 并发 3。
- `maintenance`：批次进度、审批持久化和预算补偿。

文档身份为 `项目 + SHA-256 + 业务版本`；重复提交复用既有文档/工作流。Full 模式使用 PostgreSQL 行锁预留预算，本地模式使用按项目异步锁保持相同语义。审查决定和问题单处理都使用 `lock_version`。

OpenTelemetry 与 `agent_runs/agent_steps` 只保存模型、工具、Token、延迟、结束原因和错误类型，不保存 Prompt、全文证据、模型正文、密钥或隐藏推理。

## 简历范围补充实现（2026-11-02）

- 模型只返回`ModelWorkerReview`；引用ID和逐字引文均校验，领域、文件定位、版本、问题ID和人工状态由服务端生成。厚度/文件版次/价格比较提议经确定性规则验证；材料引用缺失仅在全包检查。其他模型提议降为需人工核查线索，不作为确定工程冲突。缺少规则支持的提议仍可能漏检，未声称通用蕴含验证。
- `document_business_metadata`保存声明型号、适用版本、文档类型、生效区间、声明人和依据；声明采用文档版本CAS。它是用户声明，非模型抽取后自动确认的事实。`DocumentSearchFilters`贯通REST、Function Calling、MCP；两个召回通道在RRF前应用同样硬条件。词项计分和Top-N移入参数化SQL，仍是substring计分，不是BM25或中文全文索引。已有复合索引服务于硬条件，未证明词项通道的大规模性能。
- 新Temporal提交在开始前将已授权证据正文、文档与片段SHA和解析元信息冻结为`review_manifests`；四个阶段读取同一快照，不把正文加入Workflow输入。云调用前重查当前分级，避免后来升级保密的资料继续发送。旧Workflow输入没有manifest标识时保留旧读取路径，不声称历史任务已迁移。
- 审批在同一事务保存带command_id/actor/reason/expected_version的决定并进入`decision_pending`，禁止继续处理问题。Workflow通过Activity读取，最长每15秒轮询，Signal仅唤醒，不携带权威决定；重复消费返回相同回执。机器报告只发布一次，cancelled/failed后迟到结果不复活任务。取消与已提交决定竞争时，已提交决定优先。
- 迁移0014为业务声明、0015为审查快照、0016为document_ingest_claims。隔离SQLite升/降/再升已通过；PostgreSQL迁移未本轮验收。Workflow命令序列变化可能影响旧历史，此前演示使用v2队列/数据库；本轮角色变更使用隔离v3演示库与队列；本次5份真实历史可重放，不说明旧生产历史兼容。

## 解析执行认领与围栏

document_ingest_claims以document_id为主键，记录workflow_id/run_id/activity_id组合执行身份和attempt。事务先锁文档行；同一执行严格递增attempt才能接管遗留indexing，其他执行或旧attempt拒绝。片段替换、向量替换、失败状态与最终indexed提交前都验证当前认领。旧尝试即使后来返回也不能覆盖新结果；IngestOwnershipLost不可重试。无需另加任务队列，Temporal仍管理Heartbeat超时和Activity重派。

资料业务元数据由页面及REST声明，记录来源说明与actor，CAS使用文档lock_version。页面检索与问答/MCP复用DocumentSearchFilters。当前单文档声明单主要型号；它不是PLM或自动事实确认系统。

## 2026-11-03 角色路由与文本表示

Supervisor/Review共用STRONG端点、模型和密钥，Retrieval/Material共用LIGHT配置。ROLE_MODEL_ROUTING_ENABLED开启后API模式缺配置即失败；关闭时兼容原REVIEW配置。角色usage及Temporal轨迹记录实际Provider、模型、Token和耗时。

CONTEXTUAL_RETRIEVAL_ENABLED默认关闭；metadata-v1只给检索输入补文件/章节/工作表/位置，不用LLM生成摘要。向量命名空间含上下文版本，切换需重建；Evidence原文及引文门禁不变。Markdown导出由已有Evidence和报告重建，保留文件/片段SHA及当前复核状态，不作为新的原始证据。

审批消费Activity现设置15秒Heartbeat超时，避免强杀后等满2分钟执行超时才重派。其事务幂等仍由持久审批command_id保证。新语义使用demo-v3及deployment-v2队列，旧历史兼容未声明。

完整业务、参考面试MD的取舍及未实现项见[本轮说明](implementation-and-interview-2026-11-03.md)。
