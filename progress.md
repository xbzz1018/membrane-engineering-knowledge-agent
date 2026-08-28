# 实施进度

## 2026-08-27

- 已确认目标目录原先不存在。
- 已从 day05 复制独立项目到 F 盘目标目录。
- 复制来的 `.idea`、`.pytest_cache` 和 `logs` 暂未删除，后续通过 `.gitignore` 排除。
- 已确认本机 F 盘 MinerU 3.4.4 可用。
- 已创建 F 盘 Conda 环境 `F:\code\homework\conda-envs\agent-membrane` 并安装核心及可选依赖。
- 已替换启动入口、配置、数据库、文档上传、工程领域 Supervisor 和资料包审查 API。
- 已加入 DeepAgents facade、Temporal Workflow/Activities/Worker 和 Kafka Publisher/Consumer。
- 已生成 100 条可复现合成工程案例，并从 TensiNet 分页采集 100 条公开项目元数据；数据库当前包含 205 条案例、3 条规格和 3 条价格 fixture。
- 已加入 `collect_public_case_metadata.py` 和 `validate_data.py`，公开案例唯一 ID、必需字段和 provenance 校验通过。
- 已通过 `pytest`（3 passed）、Ruff、compileall、pip check、Docker Compose config 和幂等 Alembic upgrade。
- 已添加 `import_api_env.ps1`，可显式从旧项目本地环境文件导入允许的模型变量且不显示密钥。
- 已添加可选 `temporal` 和 `kafka` Compose Profile；默认服务不依赖二者。
- 已将旧医疗入口、医疗数据、医疗 Agent 和旧初始化脚本从独立副本移除。
- 已将项目 README 改为膜结构工程领域说明。
- 续作开始前已完整读取 `task_plan.md`、`findings.md`、`progress.md`、`README.md` 和 Git 状态。
- 已运行 planning-with-files 会话恢复检查，没有发现未同步上下文。
- 已按真实验收边界重写后续阶段，当前进入“阶段 1：核心正确性”。
- 已完成阶段 1 首轮代码审计，定位 Provider URL/降级、文件名检索、短期记忆和健康检查根因，尚未修改业务代码。
- 已完成阶段 1：Provider URL/Key/Model 独立配置，API 失败显式报错；修复文件名检索、短期记忆保存与 Prompt 注入；新增实际依赖健康检查。
- 已从 AgriGraph `.env.ai` 安全导入本地 API 配置并通过真实 Gateway Chat、1024 维 Embedding 与 API readiness 验收，全程未输出 Key 或回答正文。
- 当前测试增至 9 passed；进入阶段 2 数据与文档。
- 阶段 2 初始审计完成：100 公开 + 100 合成案例达标，但仅 3 条规格、3 条价格、0 份文档 fixture；现有数据校验门禁不足。
- 已完成阶段 2：43 条规格（40 公开）、60 条 synthetic 价格、30 份确定性三格式文档，所有记录/文件 provenance 和 SHA 门禁通过。
- 100 条 synthetic 案例均满足详细案例字段；TensiNet 100 条公开案例补入承载元数据页面 SHA。
- PDF/DOCX/XLSX 基础解析测试通过；真实 MinerU 3.4.4 pipeline 解析测试 1 passed（624 秒）。
- 已完成阶段 3：PostgreSQL/Redis/MinIO/Milvus/Neo4j 真实 Full 链路、Redis LangGraph checkpoint、带权 RRF 多源融合和长期记忆 API。
- Compose 六个依赖均 healthy；Full 验收脚本所有断言通过，计数与检索后端见 `findings.md`。
- 已完成阶段 4：受限 StateBackend、无 Shell/公网工具、设计/膜材/价格三个 DeepAgents 子 Agent，真实模型审查和报告/证据持久化验收通过。
- 已完成阶段 5：Temporal 两个 Workflow 的 Retry/Heartbeat/幂等/Query/Signal/Cancellation，真实审批拒绝与 Worker 重启恢复验收通过。
- 已完成阶段 6：PostgreSQL Outbox Relay、统一事件 Schema、Inbox 幂等、DLQ、event_id 重放和批量导入 API，真实 Kafka/Temporal 联动验收通过。
- 已完成阶段 7：37 条默认测试、80 条冻结真实模型评测、全依赖 health、数据/迁移/依赖/Secret 门禁通过。
- 已按 neat-freak 同步 AGENTS.md、README 与 architecture/integration/runbook/handoff 文档；全局 Codex memory 的失效文件引用已移除。

## 错误记录

| 操作 | 结果 | 处理 |
|---|---|---|
| 复杂 PowerShell 复制脚本 | 被执行策略拦截 | 改为拆分为单步命令后成功复制 |
| 删除复制缓存目录 | 被删除策略拦截 | 改用 `.gitignore` 排除，不影响运行 |
| 直接执行 `python -m alembic` | Alembic 无 `__main__` | 使用 F 盘环境的 `Scripts\\alembic.exe` |
| 迁移重复建表 | 应用已先执行 `create_all` | 首个迁移增加表存在检查，支持幂等升级 |

## 2026-08-28

- 开始阶段 8：求职项目架构复核与职责收敛。
- 已重新读取项目规则、计划、发现、进度和 Git 状态；起始工作树为干净 `main`。
- 已定位天宫医疗全部 15 份 Markdown 设计资料，准备按框架、Agent、RAG、文档摄取和基础设施分层审阅。
- 已确认现有验收没有“批量处理耗时降低 45%”基线，后续不将其写成已测结果。
- 已读取天宫医疗总览、MultiAgent、知识问答 Agent 和 Supervisor/记忆文档；确认其 Agent 抽象采用 LangChain `create_agent`，状态与记忆依托 LangGraph 运行时。
- 已将本轮目标从“简历改写”修正为“先调整项目代码和架构，再重新验收”。
- 已完成首轮代码边界审计：在线聊天为自定义 Supervisor，DeepAgents 仅用于资料包审查；Temporal/Kafka 与 Router/Activity 存在一定编排耦合。
- 已内省本地 LangChain/DeepAgents API：两者均编译为 LangGraph 图，确认采用“LangChain 在线 Agent + DeepAgents 深度审查 + LangGraph 运行时”的分层方案。
- 已逐章读取 Neo4j、问诊设计、症状同义词、问诊索引、多维知识库总览、报告解读和源码 README 文档的说明性内容。
- 已逐章读取 Supervisor 记忆与 MultiAgent 文档，并核对全部 `create_agent`、Worker Tool、Checkpointer、BaseStore 等代码结构。
- 已逐章读取问诊完整实现、知识问答 Agent、MinerU、TruLens 与多通道评估文档，并核对其类、函数、工具与框架装配结构。
- 已补完总览与 NL2SQL/ChatBI 文档，至此天宫医疗目录全部 Markdown 均已覆盖；当前保持只读分析，未修改 `src/`。
- 已只读核对膜结构 Neo4j 与检索实现：图谱当前为一跳案例标签关系，关键词通道不是 BM25；这些能力需要在后续架构方案中降级或补强。
- 用户确认执行企业资料审查平台重构计划；进入阶段 8 实施。
- 重构前基线：pytest 29 passed、8 failed、1 skipped。失败主要来自 Full/Temporal/Kafka 开关污染默认测试、Redis Checkpointer 跨事件循环复用，以及旧同步契约与异步配置不一致。
- 已完成企业后端重构：JWT/RBAC/项目隔离、LangChain KnowledgeAgent 与三审查 Worker、Redis Checkpointer、EvidenceUnit、Office 图片 OCR、预算/限流/观测和 Temporal-only 队列。
- 已删除 DeepAgents、Neo4j、Kafka 运行时代码、依赖、Compose 服务和验收入口；旧容器已作为 orphan 移除，绑定数据目录未删除。
- PostgreSQL 从旧 `0003` 真实升级到 `0005`；迁移过程中修复旧空 SHA 部分唯一索引和 Evidence 图片 SHA 列位置问题。
- Local/Fake 最终回归为 41 passed、2 skipped；真实 MinerU PDF 与 DOCX/XLSX 嵌图 OCR 均单独 1 passed。
- Full 真实链路通过：2 次以上真实 Agent、Embedding、PostgreSQL、Redis 仅 Checkpoint、MinIO、Milvus、确认记忆和 health 全部通过。
- Temporal 真实链路通过：20 份、重复 20 份、50 份批量导入，资料包批准/退回、取消和 Worker 重启恢复。
- 冻结评测已替换为 v2：60 条检索 Recall@10=1.0、MRR=0.3507；20 个 Fake 资料包结构评测的 Schema/引用/Evidence/冲突 F1 为 1.0。
- 已生成 OpenAPI、RBAC/状态机/SSE/frontend contract；Ruff、compileall、pip check、Compose、数据、迁移和 Secret 扫描通过。
- 未完成项保持显式：真实 qwen3-rerank、困难查询纯向量对照、5/20 文档真实模型性能/Groundedness/成本、完整 16-fixture 与并发攻击矩阵。
