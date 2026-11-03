# 简历优化前验证证据（历史快照）

> 保留102项测试阶段事实与失败，不代表当前实现。最新证据见[current-validation.md](current-validation.md)。

验证日期：2026-11-02。此记录对应独立副本，原项目位置与提交见 [来源快照](../SOURCE_SNAPSHOT.json)。本轮新实现应作为个人复现/补充验证介绍，不能反推为历史团队成果。原项目没有被修改。

## 已落地的业务链路

项目授权 → 上传与索引 → 冻结选定证据范围 → Supervisor 调用三个领域 Agent 工具 → 结构、引用与逐领域覆盖检查 → 规则核对和问题单 → 人工处理 → 按版本批准或退回。

- 厚度只按同型号、同适用版本比较，用 Decimal 归一单位；未知适用性、缺单位、多型号转人工。独立文件版次不同不直接判冲突。
- 区分设计要求、独立规格与价格证据；缺证不能自动通过。价格比较明确地区、税、币种和历史日期。
- `review_design/material/price` 是 LangChain StructuredTool。证据与身份范围由服务端绑定，模型不能选择其他项目；领域归属、问题 ID 和处理状态由服务端控制。
- 每个领域显式报告 processed/skipped，最多一次补审；引用必须可见且已处理。证据与原件保留 SHA，超出包/批次预算显式拒绝，不静默截去资料。
- 人工修改以事务和 lock_version 防覆盖。未处理阻断问题不能批准；忽略和退回必须写原因；最终报告禁止再改问题。操作元数据保存在报告 JSON，尚非独立不可篡改审计系统。

规则实现与业务假设详见 [业务范围](business-boundaries.md)，模型和回归口径详见 [评测协议](evaluation-protocol.md)。

## 工程验证

| 检查 | 本轮实际结果 |
|---|---|
| 后端全量 | **102 passed, 2 skipped**，102.87 秒；跳过的是实际MinerU PDF与Office图片OCR，不作为通过证据 |
| Ruff / pip check / 数据校验 | 通过；200 案例、43 规格、60 合成价格、30 格式 fixture |
| 前端 | OpenAPI 类型生成、Typecheck、Build、ESLint 通过，Vitest 2 条通过；Element Plus 包体积仍有构建提示 |
| 运行中的 HTTP | 上传、解析索引、重复复用、问答、三个子工具、冲突、持久化、旧锁 409、阻断批准、处理后批准、终态保护通过 |
| 真浏览器 | 登录、证据页、阻断批准 409、填写忽略原因、批准、终态隐藏操作通过，无 pageerror |
| MCP stdio | 官方客户端发现 5 个工具、3 个 Resource Template，规格查询成功；不代表 HTTP 写工具验收 |
| 公开 PDF | 7 页、11 片段、6 项具体页码/事实检查通过；基础解析，未使用 LLM |

接口与浏览器记录：[HTTP/MCP](validation-artifacts/README.md)、[浏览器](validation-artifacts/README.md)、[报告截图](validation-artifacts/README.md)。两种记录均使用合成资料、Local/Fake/Basic，真实模型质量另列如下。

可审阅变更：[文件与SHA清单](validation-artifacts/README.md)、[相对原提交的diff](validation-artifacts/README.md)。清单覆盖独立复现及本轮完善；原仓库已确认无已跟踪文件修改，新文件的完整内容保存在本副本中。

后端测试采用现有 Python 3.12.13 环境；隔离第三方 pytest 自动插件，显式加载 pytest_asyncio。当前源码校验串为：

```text
64d2a5e316bfd850a5d6a9127e6402fa8b6ff422771966075a0a9306cf332efe
```

它由排序后的 `src/**/*.py` 和 `scripts/**/*.py` 路径及内容计算，包含代码中的动态 Prompt；不包含前端、文档、模型服务端实现与秘密配置。API 第二轮、Reranker 对照和最后 Fake 回归的运行前后此值未改变。API manifest 另保存非秘密配置、静态 Prompt SHA 与运行版本。单一哈希不能替代完整实验环境归档。

## 业务开发回归：保留成功和失败

固定数据 [business_review_v1](../data/eval/business_review_v1.jsonl)：24 条人工合成开发案例，12 条正常、12 条需要复核；已用于开发调参，**不是独立测试集，也不是专家标注的内部资料**。数据 SHA：`2427446d8e39d0bafb06029ec04a3acbae5ee245068632760e33d16c1e95fb10`。

| 运行 | 完成 / 总数 | 约定检查通过 / 总数 | 误报 | 执行失败 | p50 / p95（含上传索引） |
|---|---:|---:|---:|---:|---:|
| 第一轮完整真实模型 | 21/24 | 20/24，83.33% | 1 | 3 | 12.25 / 16.76 秒 |
| 第二轮完整真实模型 | 23/24 | **21/24，87.50%** | **2** | **1** | **9.66 / 15.45 秒** |
| 最后 Fake 规则与工具回归 | 24/24 | 24/24 | 0 | 0 | 仅用于功能检查 |

真实模型为 `qwen3.7-flash`；运行元数据 provider 为 dashscope。第一轮后修了领域归属与结构提示、价格比较约束。第二轮完成率提高，但误报增加；两轮不能证明稳定统计提升。第一轮哈希在运行末计算，属于探索记录，第二轮起才有运行前 manifest 和变更检测。

第二轮完成样本的“需人工复核”检测：TP=11、FP=2、FN=0、TN=10，Precision=84.62%、Recall=100%、F1=91.67%。**这些指标排除了 1 条执行失败**；失败样本恰为应复核正例，不能以 Recall=100% 宣称无漏检。对所有提交样本，预期需复核的 12 条只有 11 条成功给出复核结果。主要成绩使用含失败的 21/24。

逐样本归档：[第一轮](validation-artifacts/README.md)、[第二轮摘要](validation-artifacts/README.md)、[第二轮明细](validation-artifacts/README.md)、[最后 Fake](validation-artifacts/README.md)。更早两次四样本探测也保存在 results 中，不能挑选某次小样本当最终成绩。

“约定检查通过”检查复核标识、预期问题类型是否出现、目标资料是否被引用以及引用 ID 合法，**不检查所有额外文字的语义正确性，也不要求问题集完全等于 gold**。例如 `unclear-applicability` 通过了当前协议，但模型仍把未知适用性的厚度差异写成确定冲突；`ok-price-region` 虽未阻断，仍多写了不必要的币种差异提示。因此 87.50% 不能称为工程结论准确率或 Groundedness。

第二轮剩余三条失败都保留：

| 案例 | 观察 | 下一步可验收修复 |
|---|---|---|
| `ok-other-applicability` | 跨适用版本比较厚度，并混淆文件版次 | 将比较主体/适用性作为结构化前提；新增独立项目测试，不能只改该例 |
| `ok-price-tax` | 把含税/未税分组差异升级为阻断冲突 | 服务端验证模型的比较分组，保留无可比记录的正常路径 |
| `bad-unit-converted` | 两次输出的 evidence_refs.version 类型不符，HTTP 422 | 将模型发现 Schema 与服务端引用定位 Schema 拆开；用真实模型验证有限修复与失败可见性 |

目前没有给这三条做特判，也没有删除失败。跨领域重复问题、非阻断误提示、Prompt 注入对抗和引用语义支持仍需要独立标注评估。

## 真 Reranker 对照

`run_reranker_eval.py` 实际调用 `qwen3-rerank`，60/60 完成。固定合成语料只有 30 份文档，每查询单一相关答案；本次 **60 个查询都把全部 30 份文档放进候选**。

| 策略 | Recall@10 | MRR@10 |
|---|---:|---:|
| 词项排序 | 0.8333 | 0.5637 |
| 相同候选 + 真 Reranker | 1.0000 | 1.0000 |

Rerank 调用 p50=277.5ms，p95=332.8ms，n=60，不包含上传、解析与网络外的业务处理。30 条文件名/版本查询原来已为 1.0；改善来自另 30 条改写/干扰查询。这个小语料全候选实验非常有利于重排，不能推导大规模检索召回、无答案拒答或生产质量，也没有纯向量基线。

证据：[摘要](validation-artifacts/README.md)、[逐查询排序](validation-artifacts/README.md)。该成绩不能替代简历的“60 条内部样本、Recall≥90%、相对纯向量 MRR 提升约30%”。

## 公开原始资料与未完成能力

[公开 PDF 检查](validation-artifacts/README.md)保留来源 URL、SHA、页码和小段事实核验。厂商 PDF 为历史公开快照，不宣称当前规格；160 微米描述涂层保护区，不能当膜材总名义厚度。该实验不证明任意复杂表格或扫描 OCR 的正确率。

- Embedding 端点 `text-embedding-v4` 实际返回 403；[离线向量尝试](validation-artifacts/README.md)未产生质量分数。当前只证明词项/Reranker 对照，不证明 pgvector/RRF 实测效果。
- Docker 引擎未连通，PostgreSQL/pgvector、Redis、MinIO 与真实 Temporal 恢复尚未做本轮完整栈验收。Temporal Activity 测试不能替代 Server/Worker 故障恢复。
- MinerU 未验收；MCP HTTP 写能力、独立 Groundedness 裁判、单 Agent 对照未验收。
- 当前词项通道是作用域内片段读取后在 Python 计分，不是 BM25，也没有完整的工程型号/业务生效日期索引过滤。Temporal 与数据库之间的并发审批原子性仍需补强。

下一阶段先做业务人员独立标注及比较前提校验，再验证真实基础设施和故障注入。接入更多 Agent 不会自动解决这些问题。

## 复跑入口

```powershell
cd 'F:\工作\04项目资料\简历项目\资料智能审查落地版'
$python = 'F:\code\homework\conda-envs\agent-membrane\python.exe'
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
& $python -m pytest -q -p pytest_asyncio.plugin
& $python scripts\run_business_eval.py
& $python scripts\demo_acceptance.py
```

真实模型须配置获准的公开资料端点后运行 `run_business_eval.py --mode api`；Reranker 对照为 `run_reranker_eval.py`。API 回归有任一约定检查失败会返回非零退出码，结果仍保留；这是测试失败，不能写成全部验收通过。当前演示服务已启动，数据和依赖均在本机，迁移时依照运行手册重建环境。
