# 后端验收记录

> 以下为原仓库的历史记录，复制于2026-11-02，未在本轮重新复验。当前复现结果见[current-validation.md](current-validation.md)。这些历史合成评测值不能直接证明简历中的内部回归成绩。

本记录只描述已实际执行的本机 Docker Compose 验收，不将合成回归结果包装为结构工程结论或泛化准确率。

## 当前链路

- Full 依赖：PostgreSQL/pgvector、Redis、MinIO、Temporal、MinerU 和模型端点均已启动并通过健康检查。
- PDF Full 模式实际走 MinerU；DOCX/XLSX 嵌图 OCR 真实测试通过。
- 审查链路为 `ReviewSupervisorAgent -> Design/Material/PriceReviewAgent -> 确定性规则 -> 结构化问题单 -> 人工审批`。
- Temporal 验证通过：单文档、20/重复20/50 批量、批准、退回、取消和 Worker 重启恢复。
- 公开案例：100 条详情页采集成功；业务数据为 200 条案例（100 条公开、100 条 synthetic），另有 5 条测试 Fixture；规格 43 条、synthetic 价格 60 条、解析 Fixture 30 份。

## 困难检索 v3

同一机器、同一资料和同一查询集共 60 条：

| 策略 | Recall@10 | MRR |
|---|---:|---:|
| 纯向量 | 0.5000 | 0.4625 |
| 混合检索 | 0.5000 | 0.2783 |
| 混合检索 + qwen3-rerank | 1.0000 | 0.7083 |

相对纯向量的 Recall@10 提升为 `50.00` 个百分点，MRR 提升约 `53.15%`。该结果于 2026-09-03 在 pgvector 迁移和全量索引重建后重新生成；评测资料使用 SHA 归档别名和语义干扰项，用于检索回归，不代表真实工程问答准确率。

## 真实资料包评测 v3

模型：审查 Worker 与 Supervisor 使用阿里 Workspace `qwen3.7-flash`；Groundedness 裁判使用 `qwen3.8-max`。每个规模 3 轮，结果来自 `data/eval/results/real_package_benchmark_v3.json`。

| 资料数 | Groundedness | 引用覆盖 | 有效引用率 | 冲突召回 | p50 | p95 | 平均模型调用 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 5 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 12.52s | 12.52s | 4 |
| 20 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 21.39s | 21.39s | 4 |

5 份资料平均输入/输出 Token 为 `8435/3256`；20 份资料为 `58001/7594`。成本字段是本地估算，不是供应商账单。评测资料为合成工程文本，结论仅用于链路回归。

## 范围与后续扩展

- 当前验收重点覆盖资料解析、证据检索、跨文档一致性审查、历史成本参考和人工复核链路。
- 冲突识别当前记录的是合成评测集上的召回，不宣称真实工程冲突识别 F1。
- 扫描/混合 PDF 的真实 MinerU 矩阵仍需继续扩充；现有真实 PDF、DOCX/XLSX OCR 通过，损坏/空 PDF 有显式失败回归测试。
- Vue 3 + Element Plus 前端工程台已实现并完成真实 FastAPI 联调；前端独立运行，不纳入 Docker Compose。

## 2026-08-29 复验结果

- 以下为 Milvus 迁移前的历史验收记录；当前向量后端以 2026-09-03 pgvector 复验为准。
- 默认回归：`76 passed, 2 skipped`；真实 MinerU opt-in：`11 passed`。
- Temporal：单文档、20/重复20/50 批量、批准/退回、取消和 Worker 重启恢复全部通过。
- 当前 Full 服务 `/health/deps` 的数据库、模型、上传存储、MinerU、Redis、MinIO、Milvus 和 Temporal 检查均为 `healthy`。
- MCP 官方客户端复验：stdio 发现 5 个查询工具，Streamable HTTP 发现 9 个工具；无令牌 401、无确认能力安全拒绝、确认后创建/幂等重放/取消均通过。
- 目录整合后冷启动 Full 复验通过：真实 MinerU、PostgreSQL、Redis Checkpoint、MinIO、Milvus 和 KnowledgeAgent Function Calling 均成功。
- 最终门禁：`pytest 76 passed, 2 skipped`；Ruff、compileall、pip check、Alembic `0011_mcp_gateway`、Compose 配置、数据校验和 Secret 扫描通过。API/MCP/Temporal Worker 重启后健康检查通过。

## 2026-08-30 最终交付复验

- 后端契约已升级到 `0012_frontend_contract`；项目总览、批次列表、预算乐观锁、膜材规格和历史价格台账接口可用。
- MCP 已升级到 Python SDK `2.1.1`，协议版本 `2026-07-28`；Streamable HTTP 与 stdio 双传输验证通过，分别发现 9/5 个工具和 3 个 Resource Template，覆盖 Origin、401、MRTR Elicitation、幂等和取消。
- 前端为 Vue 3 + TypeScript + Vite + Element Plus，已完成登录、项目上下文、资料、台账、问答、资料包审查、批次、记忆、运行轨迹和管理页面。
- 前端真实浏览器联调通过桌面、1024px 和 390px 视口检查；页面级横向溢出已修复，API 错误不生成演示数据。
- 前端门禁：`npm run typecheck`、`npm run lint`、`npm run test`、`npm run build` 和 `npm run test:e2e` 均通过。
- 本报告中的性能、Groundedness 和成本数字仅来自当前合成评测资料与本机环境；不包装为真实工程安全结论或供应商账单。

## 2026-09-03 pgvector 迁移复验

- PostgreSQL 镜像切换为 `pgvector/pgvector:0.8.6-pg17`，Alembic 升级到 `0013_pgvector_embeddings`，vector 扩展版本为 `0.8.6`。
- `document_embeddings` 已覆盖 751 份已索引资料，共 966 条 Evidence 向量；`memory_embeddings` 包含 12 条已确认记忆向量。
- 真实 cosine 查询返回 `pgvector` 检索来源；`/health/deps` 中 PostgreSQL、pgvector、Redis、MinIO、Temporal、MinerU 和模型端点均为 `healthy`。
- Local/Fake 全量回归为 `81 passed, 2 skipped`；Ruff、compileall、pip check、Compose config 和 Alembic head 检查通过。
- 困难检索 v3 已在 pgvector 上重跑，结果文件为 `data/eval/results/difficult_retrieval_v3.json`，指标见本报告“困难检索 v3”。
