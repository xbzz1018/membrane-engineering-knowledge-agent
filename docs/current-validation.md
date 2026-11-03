# 当前实现与验证证据

更新：2026-11-02。本目录是独立复现副本，不能将新增实现追认为历史团队贡献。原始来源见[快照](../SOURCE_SNAPSHOT.json)。历史记录和失败保留，以下按每次运行的实际模式解释。

## 2026-11-03 部署包增量

新增完整 Compose、前后端镜像、随机凭据初始化、启动门禁及真实 HTTP/pgvector/Temporal 合成验收脚本，操作见[部署说明](deployment.md)。18 项部署门禁测试通过；全量后端 **144 passed / 2 skipped，148.82 秒**；Ruff、pip check、数据检查通过。前端 Typecheck、ESLint、Build 和 2 项 Vitest 通过，构建/测试使用 `--configLoader runner` 避免写入依赖 Junction。Compose 含 validation/MCP profile 可解析。本机 Docker Linux Engine 未运行，尚未构建或运行这些容器；这不改变下面 Full 存储、真实 Embedding、MinerU 的待验收结论。GitHub Actions 工作流仅已编写，尚未上传运行。独立 Git 更新目录不携带 `.env` 或业务运行状态；可分享的安全验证摘要另存于[归档](validation-artifacts/README.md)。

## 已实现的业务闭环

项目授权 → 上传 → Temporal解析/切片/索引 → 声明业务元数据 → 条件检索与证据定位 → Supervisor调用三个领域Agent工具 → 结构化输出、引文及规则校验 → 人工处理 → 持久化决定 → 工作流终态。

- 子Agent是review_design/material/price三个StructuredTool。full固定三领域，focused才调用规划模型；工具闭包绑定授权Evidence，模型不能选择身份、项目或其他文档。
- 模型只返回发现和引文；服务端生成问题ID、领域、版本、定位及人工状态。有限厚度/版次/价格语法由规则核验，其他发现保留为人工线索。逐领域processed/skipped覆盖检查，最多补审一次。
- 资料页已连接元数据GET/PUT与真实条件检索，支持声明依据、CAS冲突重载、型号/适用版本/业务日期及证据抽屉。未知日期不由上传时间替代。
- Temporal提交时冻结Evidence快照；机器报告仅发布一次；人工决定先事务保存为decision_pending，Activity幂等消费，Signal只唤醒。
- 解析Activity使用execution/attempt持久认领。相同执行的新尝试可以接管，旧尝试在写片段、向量、失败及完成状态前必须通过围栏，避免强杀后卡在indexing或旧执行覆盖新结果。

## 工程验收

| 检查 | 实测结果与边界 |
|---|---|
| 后端全量 | **126 passed, 2 skipped**，137.10秒；实际MinerU PDF/Office图片OCR跳过 |
| Ruff / pip / 数据 | 通过；200案例、43规格、60合成历史价格、30格式fixture |
| 数据库迁移 | 0014/0015及新增0016认领表均有隔离SQLite升/降/再升；不代替PostgreSQL迁移验收 |
| 前端 | Typecheck、ESLint、Build及Vitest 2项通过；Element Plus包体积提示仍在 |
| 资料页真实浏览器 | 上传及异步索引、元数据保存/重载、近似型号排除、证据定位、旧版本409/重载、空结果、390px移动端通过 |
| 审查页真实浏览器 | 全服务重启后待复核报告仍存在；新任务queued自动到awaiting_approval；决定先decision_pending再rejected；终态隐藏操作 |
| MCP stdio / HTTP | 5/9工具、各3资源模板；鉴权查询、401/403、无确认能力拒绝写、幂等创建与取消请求通过 |

证据：[JUnit](validation-artifacts/README.md)、[迁移](validation-artifacts/README.md)、[资料页浏览器](validation-artifacts/README.md)、[异步审查浏览器](validation-artifacts/README.md)、[MCP](validation-artifacts/README.md)。浏览器page_errors为空。MCP本轮未逐个执行HTTP批准/退回工具；取消请求的终态由下面的Temporal验收另证。

## 真实Temporal服务故障验收

实际运行官方SDK下载的Temporal CLI 1.9.1 / Server 1.32.0，使用SQLite业务库、Fake Agent和TXT基础解析；不是ActivityEnvironment模拟，也不是Full存储。

运行：20261102T114136Z-3a7a519f，[摘要](validation-artifacts/README.md)。全部通过：

1. Activity拿到解析锁后强杀Worker；重启后attempt 2接管，最终indexed且仅1个片段。
2. 重复Workflow提交复用原工作流。
3. 真实报告提交后注入Activity失败；期间人工解决问题并退回；重试保留人工记录并消费提前提交的决定。
4. 裸approve Signal不能审批；等待期间重启后取消，业务库与Workflow均终态。
5. Worker离线期间提交批准，重启后消费持久命令并approved。
6. 审查Activity运行中取消，业务库与Workflow同步cancelled。
7. 保存并重放5份本次真实历史。

运行中src/scripts代码稳定，SHA为2c5508ec95fefdc82d943f27548e5e4c03f02152ab8e8cc9240ae48be92d9f0c。之后新增启动/MCP脚本与前端，不能把该SHA称为最终全部代码的运行记录。早先20261102T112516Z-c6b52eca的验收脚本过早检查取消终态而失败，记录保留；随后改为同时等Temporal CANCELED。

未证明生产集群故障切换、旧生产历史迁移、强制terminate后的自动对账或20/50份批量吞吐。

## 扩展检索开发回归

冻结[数据](../data/eval/retrieval_business_v1.json)含**119份合成资料、30条查询（23有答案、7无答案）**：近似型号、版次、历史/未来/未知日期、多相关、纯条件、跨项目/分级陷阱和语义改写。三组重复型号家族及80份模板干扰资料，开发者标签，非独立测试或公司内部样本。

运行20261102T113700Z-c8096dbb，[摘要](validation-artifacts/README.md)、[逐条预测](validation-artifacts/README.md)：

- Local SQLite词项通道，固定30候选，文档去重Top10。
- 30/30完成，0执行错误、0硬过滤越界。
- 有答案23条的macro Recall@10和MRR@10均**0.869565**；失败按0计入分母。
- **3/3语义改写全部漏召回**；保留该缺陷，不调标签凑分。
- 7/7无答案查询返回空。这是返回空比例，不是问答拒答准确率。
- 运行中源码稳定，SHA为2944cddd05c61b51e4f2d08ead71d803f0a6c88d6e174f218c666987337487e8。

[Embedding探测](validation-artifacts/README.md)中配置的两个端点均403，因此本轮没有真实向量/RRF质量成绩。Full四策略评测入口已实现，未用Fake向量填补缺失结果。

## 前阶段真实模型开发回归

运行20261102T094647Z-9d724049，qwen3.7-flash，24条人工合成开发案例（12正常/12需复核）。严格阻断问题类型与证据集合一对一匹配：24/24完成并通过，问题TP13/FP0/FN0；p50 7.69秒/p95 12.71秒，含上传索引。

[摘要](validation-artifacts/README.md)、[预测](validation-artifacts/README.md)、[配置](validation-artifacts/README.md)。这是本阶段新增认领/启动/UI前的代码，运行SHA为bd1a41f11df0297a4c4b78ace3b52a47ed037654ae5bedbdb26559313c482b62，不能称当前最终源码真实模型回归。旧v1的21/24、2误报和1结构失败及运行中改源码的探索记录均保留。

规则参与系统输出，样本已用于开发，自由文本未逐句专家核验，没有单Agent/规则消融；不能称LLM 100%准确、真实业务性能或多Agent更优。

## 尚未验证

Docker Linux引擎未能启动，PostgreSQL/pgvector、Redis、MinIO完整栈未在本轮验收；SQL谓词/参数契约不等于真实HNSW性能。MinerU、独立Groundedness裁判、专家标签和独立真实项目测试尚未完成。单文档仅声明一个主要型号/适用版次；人工审计存在报告JSON，并非不可篡改审计服务。

简历原称“60条内部样本、Recall≥90%、MRR相对提升30%”没有对应内部样本和原始记录，暂不保留这些数字。

## 复跑与演示

```powershell
$python = 'F:\code\homework\conda-envs\agent-membrane\python.exe'
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
& $python -m pytest -q -p pytest_asyncio.plugin
& $python scripts\validate_temporal_local.py
& $python scripts\run_business_retrieval_eval.py --mode local-contract
# 独立持久演示；端口需空闲
& .\scripts\start_demo.ps1 -Temporal -Mcp
& $python scripts\seed_temporal_demo.py
```

当前演示入口http://127.0.0.1:5173，开发账号admin / admin-change-me。停止脚本核对PID及启动时间。详细模式/复跑见[运行手册](operator-runbook.md)。旧demo_acceptance.py和validate_resume_slice.py面向同步模式，不要直接运行在当前异步演示服务上。
