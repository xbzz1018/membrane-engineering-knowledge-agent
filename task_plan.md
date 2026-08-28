# 膜结构企业资料审查平台实施计划

## 目标与边界

单公司内部 Docker Compose 演示平台，按项目隔离设计、膜材、价格和审查资料。不进行结构安全计算，不生成正式报价，不加入 A2A/Kubernetes，不提交企业内部资料或密钥。

## 已完成

- [x] 企业基础：JWT、管理员/设计/膜材采购/审核人、项目成员与服务端 ProjectScope。
- [x] 架构收敛：删除 DeepAgents、Neo4j、Kafka；LangChain Agent + LangGraph Checkpointer + Temporal。
- [x] 数据模型：PostgreSQL 业务事实/权限/审查/记忆/预算/运行摘要，迁移到 `0005`。
- [x] 文档智能：PDF MinerU auto/text/ocr；DOCX/XLSX 原生解析和嵌图 OCR；EvidenceUnit、SHA、版本和显式失败。
- [x] 存储：MinIO 原件/派生图片、Milvus 文档/确认记忆向量、Redis Checkpoint/限流。
- [x] RAG：项目过滤、PostgreSQL 规范化字段、Milvus、通道轮询、带权 RRF、可选 Reranker。
- [x] Agent：KnowledgeAgent、Design/Material/Price Review Worker、JSON Schema 校验、Evidence ID 校验、Map-Reduce。
- [x] 记忆：pending 候选、确认/拒绝/更新/删除；更新后重新确认，记忆不作为证据。
- [x] Temporal：单文档、20/50 批量、资料包审查、Retry/Heartbeat/Query/Signal/Cancellation、Worker 重启恢复。
- [x] 工程控制：文档条件锁、审批首决定、Token/成本周期预算、Redis 令牌桶、GET+SSE、OTel 安全元数据。
- [x] 合同：OpenAPI、RBAC、状态机、错误码、SSE 和 frontend contract。

## 当前验收证据

- Local/Fake pytest：41 passed，2 个真实 MinerU opt-in 测试默认跳过。
- 真实 MinerU：PDF 1 passed；DOCX/XLSX 嵌图 OCR 1 passed。
- Full：真实模型、Embedding、PostgreSQL、Redis Checkpoint、MinIO、Milvus、确认记忆与 health 通过。
- Temporal：20 份、重复 20 份、50 份批量，批准/退回、取消和 Worker 重启恢复通过。
- 冻结检索 v2：60 条，Recall@10=1.0、MRR=0.3507；这是精确 ID 集，不代表泛化准确率。
- 冻结资料包 v2：20 个 Fake 结构评测，Worker Schema/引用/Evidence/冲突 F1 均为 1.0。
- Ruff、compileall、pip check、Compose config、7 个服务 health、数据校验、Alembic 和 Secret 扫描通过。

## 尚未完成

- [ ] 配置并真实验收 qwen3-rerank；当前本地安全配置没有 Reranker endpoint/key。
- [ ] 建立“困难查询纯向量基线 vs 混合检索”对照，验证 Recall@10 至少提升 5 个百分点。
- [ ] 对短/长单文档、5/20 文档真实模型资料包记录 Token、成本、p50/p95 和无静默 Evidence 丢失。
- [ ] 对真实模型报告执行 Groundedness、引用覆盖率和冲突 F1；当前 20 包指标是 Fake 结构门禁。
- [ ] 扩充扫描/混合 PDF 与 Office 图片标准 Fixture 到明确的 16 份 Gate 1 子集并保存逐份结果。
- [ ] 完成更全面的角色越权、记忆隔离、预算并发和受限资料零云请求集成攻击测试。

## 完成规则

未通过当前架构真实链路的能力不得写入简历。不能把精确冻结集的 1.0 包装成“系统准确率 100%”，也不能预设批量耗时降低 45%。外部 API Key 只存在被 Git 忽略的本地 `.env`，任何日志、结果和提交都不得包含密钥或模型正文。
