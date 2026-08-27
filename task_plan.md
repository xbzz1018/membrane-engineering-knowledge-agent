# 膜结构工程知识助手实施计划

## 目标

在本机 Docker Compose 求职演示边界内，把现有 MVP 完成到可复现、可追溯、可故障恢复的膜结构工程知识助手。所有“完成”状态必须有真实链路或自动化测试证据；Fake 模式只用于离线开发，真实 API 模式禁止静默降级。

## 阶段

- [x] 阶段 0：独立仓库、F 盘环境、膜结构领域基线与 Fake MVP
- [x] 阶段 1：核心正确性
  - Provider 拆分 DeepSeek、Gateway、DashScope、Embedding Base URL；安全导入 AgriGraph `.env.ai` 的允许字段。
  - `MODEL_MODE=api` 配置或调用失败时显式报错，不静默 Fake 降级。
  - 修复资料包按文件名检索、短期记忆保存/注入 Prompt、依赖健康检查。
  - 为上述行为补充单元与接口测试。
- [x] 阶段 2：数据与文档
  - 至少 40 条公开可追溯膜材规格、60 条明确标记 synthetic 的价格、30 份可索引资料。
  - 保持至少 100 条公开案例元数据和 100 条合成案例；至少 50 条详细案例。
  - 每个公开来源记录 URL、许可说明、抓取时间和 SHA-256；PDF/DOCX/XLSX 与真实 MinerU fixture 通过。
- [x] 阶段 3：Full 模式多源存储、检索与记忆
  - PostgreSQL 保存业务事实；Redis 保存短期会话与 LangGraph Checkpoint；MinIO 保存文件。
  - Milvus 保存文档与长期记忆向量；Neo4j 保存项目/结构/膜材/场景关系。
  - 多源结果使用可解释融合策略，并返回页码、日期、版本；增加长期记忆查看/删除 API。
- [x] 阶段 4：DeepAgents 真实资料包审查
  - 设计、膜材、价格三个子 Agent 使用真实模型；文件系统受限，无 Shell 和任意公网权限。
  - 报告和证据持久化；增加资料包结果 API；真实链路验收通过。
- [x] 阶段 5：Temporal 长任务权威
  - 完成 DocumentIngestWorkflow 与 PackageReviewWorkflow 的超时、RetryPolicy、Heartbeat、幂等、Query、审批/拒绝 Signal、Cancellation。
  - 增加 Workflow 状态、审批/拒绝、取消 API；验证 Worker 重启恢复。
- [x] 阶段 6：Kafka 批量事件分发
  - PostgreSQL Outbox Relay、统一事件 Schema、Consumer Inbox 幂等、DLQ、按 `event_id` 重放。
  - 增加批量导入 API；Kafka 不承担长任务状态，Redis 不承担队列职责。
- [x] 阶段 7：全量评测与发布门禁
  - 至少 30 个单元/接口测试和 80 条冻结评测集。
  - 通过 pytest、Ruff、pip check、Alembic、Compose 健康检查、数据校验和 Secret 扫描。
  - README/进度与真实验收一致，最终 Git 工作树干净。

## 状态规则

未通过真实链路测试的 DeepAgents、Temporal、Kafka 能力不得写入简历。外部 API Key 只存在本地 `.env`，不得显示在终端输出、日志、测试快照或 Git 中。

## 当前执行顺序

核心正确性 -> 数据文档 -> 多源检索与记忆 -> DeepAgents -> Temporal -> Kafka -> 全量评测。

## 完成边界

- 本机 Docker Compose 求职演示版；不加入 A2A/Kubernetes。
- 不进行结构安全计算，不生成正式报价，不提交公司内部资料。

## 错误与阻塞记录

| 日期 | 问题 | 处理 |
|---|---|---|
| 2026-08-27 | 原计划将 facade/骨架标记为完成，缺少真实验收 | 重新拆分阶段，真实链路测试作为完成门禁 |
| 2026-08-27 | Ruff `UP035`：`Awaitable`/`Callable` 导入位置 | 改从 `collections.abc` 导入 |
| 2026-08-27 | 文件名检索测试命中片段但来源列表未出现文档 | 上传文档证据调整到融合结果前列，避免被 12 条上限截断 |
| 2026-08-27 | AgriGraph 使用 `EMBEDDING_PROVIDER=local`，首轮配置验收不识别 | 将 `local/custom/openai` 归一化为独立 Embedding 端点 |
| 2026-08-27 | PowerShell 内联 Python 的嵌套引号导致真实调用脚本语法错误，未发出请求 | 改为通过标准输入执行短脚本 |
| 2026-08-27 | Windows GBK 终端无法打印 PDF 中的 Unicode 连字 | 调研输出与采集脚本统一使用 UTF-8/Unicode 规范化 |
| 2026-08-27 | 数据校验脚本新增 import 未按 Ruff 顺序排列 | 调整为标准库字母顺序 |
| 2026-08-27 | 首次 import 修复补丁包含错误文件上下文，被完整拒绝 | 拆为两个精确文件补丁后应用 |
| 2026-08-27 | 文档 fixture 重建时 10 个 PDF SHA 变化，DOCX/XLSX 稳定 | 调查 PDF 内部随机 ID 并改为确定性生成后复验 |
| 2026-08-27 | Full 适配器首轮 Ruff 报 Checkpoint 类型导入顺序 | 按 Ruff 建议调整，Local 回归未受影响 |
| 2026-08-27 | Compose MinIO 绑定宿主 9000 失败，Redis 6379 也被其他容器占用 | 改用项目专属 19000/19001 与 16379/18001，不停止外部容器 |
| 2026-08-27 | Full 验收脚本直接执行时找不到 `src`，未触发后端操作 | 按现有脚本模式加入仓库根目录到 `sys.path` |
| 2026-08-27 | 首次入口修复补丁误带计划表上下文，被完整拒绝 | 拆分为精确文件上下文后应用 |
| 2026-08-27 | DeepAgents 权限类型首次内省使用了不存在的 `.filesystem.types` 路径 | 改从实际 `deepagents.middleware.filesystem` 模块读取 |
| 2026-08-27 | Temporal 文件替换补丁同时 Delete/Add 同一路径，被工具拒绝 | 改为单个 Update hunk 完整替换 |
| 2026-08-27 | Temporal Router queued 字典误用 `key=value` 语法，静态审阅发现 | 在编译前改为标准字符串键字典 |
| 2026-08-27 | Temporal 1.29 拒绝 Compose 的 `DB=postgresql` | 改用受支持的 `postgres12` 并等待数据库 healthy |
| 2026-08-27 | Temporal 动态配置路径在 1.29 镜像中不存在 | 删除非必需 `DYNAMIC_CONFIG_FILE_PATH`，使用镜像默认配置 |
| 2026-08-27 | 动态配置修复补丁误带跨文件上下文，被完整拒绝 | 按 Compose/计划两个文件精确应用 |
| 2026-08-27 | Temporal 容器内 `127.0.0.1:7233` 健康探测拒绝连接 | 改用容器服务地址 `temporal:7233`，实测返回 SERVING |
| 2026-08-27 | Temporal SDK 1.32 不从 `temporalio.client` 导出 AlreadyStarted 异常 | 改从 `temporalio.exceptions` 导入 |
| 2026-08-27 | Temporal Worker 因 Activity 缺少 `@activity.defn` 在注册阶段退出 | 为三个 Activity 加装饰器，并让验收脚本检测 Worker 早退 |
| 2026-08-27 | Worker 早退检查首次补丁打断 `try/except`，compileall 拦截 | 恢复完整停止函数后再定义检查函数 |
| 2026-08-27 | Temporal 默认允许复用已完成 workflow_id，重复索引重开执行 | 显式设置 `WorkflowIDReusePolicy.REJECT_DUPLICATE` |
| 2026-08-27 | WAIT_CANCELLATION_COMPLETED 竞态下取消请求后 Activity 完成、Workflow 也完成 | 改用 TRY_CANCEL，并把取消测试 Activity 延长到 30 秒 |
| 2026-08-27 | Temporal execution 已 CANCELED，但 Query state 被通用异常分支写成 failed | 将 SDK Cancelled/CanceledError 映射为 `cancelled` 并加强断言 |
| 2026-08-27 | TRY_CANCEL 时 Workflow 收到的是 ActivityError，按异常名仍误判 failed | 使用确定性的 `workflow.cancellation_reason() is not None` 判断外部取消 |
| 2026-08-27 | 取消 Query 已 cancelled 时 execution 短暂仍为 running，轮询过早返回 | 取消验收要求 Query cancelled 与 Temporal canceled 同时成立 |
| 2026-08-27 | Kafka Consumer 在 topic 自动创建前分配到 0 partitions，Outbox 发布但 Inbox 为空 | 启动前显式建 topic；验收使用 latest 并确保取消 Consumer task |
| 2026-08-27 | Kafka Admin `list_topics()` 返回 list，集合差运算 TypeError | 显式转换为 set 后计算缺失 topic |
| 2026-08-27 | Windows 文本换行转换导致冻结集写入后 SHA 与内存摘要不一致 | 直接写固定 UTF-8 bytes 后计算摘要 |
| 2026-08-27 | 冻结评测首轮 74/80 路由、79/80 来源，复合材料成本问题被 design 截获 | 扩充材料/成本词并在 design 分支前判复合意图，保留原评测集 |
| 2026-08-27 | 冻结评测第二轮路由/来源 80/80，但 1 条模型 content 为空 | Provider 对空响应/网络错误重试 2 次，耗尽后显式失败且不 Fake 降级 |
| 2026-08-27 | Git 将 ASCII PDF 识别为文本，xref 尾空格触发 diff-check 且有 CRLF 风险 | `.gitattributes` 将 PDF/DOCX/XLSX/XLSM 标为 binary |

## 最终验收

- pytest：37 passed，1 skipped（真实 MinerU 测试默认 opt-in；已单独 1 passed）。
- Ruff、compileall、pip check、Alembic 0003、Compose config、九个容器 health、数据校验均通过。
- Full readiness 为 ok；DeepAgents、Temporal、Kafka 真实链路通过。
- 80 条 SHA 锁定真实模型评测：80/80 route，80/80 source，0 errors。
- Secret 扫描通过；`.env` 未跟踪且被忽略。
| 2026-08-27 | DeepAgents 大补丁重复更新同一 Router 文件，被工具完整拒绝 | 拆为数据库、执行器、Router 三组补丁 |
| 2026-08-27 | Ruff 扩展到 Alembic 后发现 3 个 import 排序问题 | 机械调整 env 和两份 migration 的 import 分组 |
| 2026-08-27 | 手工调整后 Ruff 仍要求 Alembic 第三方 import 合并分组 | 使用 Ruff `--fix` 做确定性排序并复核 diff |
