# 第一阶段独立复现验证：2026-11-02（历史快照）

> 以下保留第一阶段87项测试时的历史记录，不代表当前状态。后续实现、真实模型/检索/Temporal与浏览器实测及失败请阅读[current-validation.md](current-validation.md)。下文“真实模型未复验”“本地无法报告级批准”等仅是当时限制。

本记录对应当前目录 `资料智能审查落地版`，不沿用原仓库历史验收结论。

## 最终执行结果

| 检查 | 本轮结果 |
| --- | --- |
| 后端全量 pytest | **87 passed, 2 skipped**，67.27 秒 |
| Ruff：`src scripts test alembic` | 通过 |
| `pip check` | No broken requirements found |
| `scripts/validate_data.py` | 通过；业务案例 200、规格 43、合成价格 60、解析 fixture 30 |
| 前端 typecheck + build | 通过；保留 Element Plus bundle 大小提示，不影响构建 |
| 前端 ESLint | 通过；本副本新增的 `.vite-cache` 已排除 |
| 前端 Vitest | 2 tests passed |
| 前端 Playwright 原有 E2E | 1 passed |
| 浏览器实际登录与报告页联调 | 通过；报告、文件证据可见，无 pageerror |
| 实际 HTTP 链路 | 上传、基础解析、索引、重复上传复用、问答检索、三领域工具调用、厚度冲突、报告持久化、人工问题处理和旧锁版本 409 通过 |
| MCP stdio | 官方客户端实际发现 5 个查询工具、3 个 Resource Template，规格查询成功 |
| Temporal Activity 工具接入 | ActivityEnvironment 定向测试通过，不依赖真实 Temporal Server |
| 启动/停止/重启脚本 | 已停止本轮进程并重新启动，重启后 HTTP/MCP 和浏览器再次通过 |

后端命令使用已有 Python 3.12.13 环境 `F:\code\homework\conda-envs\agent-membrane\python.exe`。为隔离第三方 pytest 插件，设置 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` 并显式加载 `-p pytest_asyncio.plugin`；本机回环网络执行需要运行环境允许本地连接。没有修改 Python 全局网络实现来绕过限制。

## 与简历四项工作的对应

| 简历内容 | 已找到的实现和本轮状态 |
| --- | --- |
| 多 Agent 审查编排 | 原项目有 Supervisor 计划和三个领域 Agent。本副本新增 `StructuredTool` 封装与真实 LangChain 工具调度循环；已验证 Fake 模式，真实模型未复验。 |
| 精确条件与语义检索 | 原项目有 PostgreSQL/pgvector、RRF 和 Reranker 相关代码与评测脚本。本轮只验证本地检索接口，没有复验向量与神经网络重排质量。 |
| 业务工具和 MCP | 保留资料、规格和价格工具；MCP stdio 查询已实际通过。HTTP MCP 的鉴权、写工具和确认流程未做本轮整体验收。 |
| 长任务执行与恢复 | 保留 Temporal 的解析、批量、审查、审批、取消和恢复实现。领域 Activity 接入同一工具封装并有测试；真实 Worker 重启恢复未复验。 |

## 当前可查看的产物

- `data/runtime/demo-acceptance.json`：实际 HTTP 和 MCP 结果、工具调用名称与时间摘要、未验证范围。
- `data/runtime/browser-acceptance.json`：实际浏览器检查结果。
- `data/runtime/demo-review.png`：实际报告页截图。
- `data/demo/*.txt`：三份明确标记 SYNTHETIC 的演示资料。
- `data/runtime/demo.db`：本副本的 SQLite 运行数据。
- `data/runtime/demo-processes.json`：本次启动的 API/前端进程与启动时间；停止脚本据此核验身份。

## 尚未完成的完整栈验证

已检查 Docker CLI，并尝试启动已有 Docker Desktop；最终仍无法连接 `dockerDesktopLinuxEngine`。因此，本轮没有运行 PostgreSQL/pgvector、Redis、MinIO 和 Temporal 的 Compose 服务，也没有接入真实模型、神经网络 Reranker 或 MinerU。

原仓库发现了 2026-09-03 的 `data/eval/results/difficult_retrieval_v3.json`：60 条合成困难检索样本，纯向量 Recall@10=0.5、MRR=0.4625，混合加重排 Recall@10=1.0、MRR=0.7083。该历史记录与简历中“内部样本、90% 以上、相对提升约 30%”不是同一组证据，不能混用。本轮未重新跑这些数值。

当前本地模式支持人工修改问题单；报告级批准/退回与任务取消仍依赖 Temporal，不属于本轮可演示闭环。
