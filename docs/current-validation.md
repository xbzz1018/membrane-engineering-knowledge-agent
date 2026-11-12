# 当前实现与验证证据

更新：2026-11-12。本目录是独立复现副本，不能把新增实现追认为3—6月实习贡献。按源码版本与运行模式分期记录，保留失败。业务取舍与参考MD的对应见[实现说明](implementation-and-interview-2026-11-03.md)。

## 2026-11-12 同步与任务Adapter接入

在GitHub功能分支同步动态问答和单份项目方案闭环；保留原资料包流程、CI与历史归档。新增可选查询标准化和审查整理任务接入，默认关闭；真实调用位置已有协议测试，非公开资料在调用前阻断，整理结果不改结构化问题或审批状态。公司Qwen3.5-4B经历与11月Qwen3-0.6B实验分开记录，见[模型适配](model-adaptation.md)。本轮没有训练、GPU推理或公司权重部署。

| 检查 | 本轮结果与范围 |
|---|---|
| 完整后端 | **218 passed / 2 skipped，69.40秒**；[JUnit](validation-artifacts/upload-20261112-backend-tests.xml)，Local/Fake；API模型使用测试替身 |
| 首轮失败与修复 | 214通过/1失败/2跳过；旧Temporal生命周期测试替身未适配新的异步审查方法。更新替身后，含新增调用位置测试的定向30项通过，再运行上述全量；原始失败保留在本机运行目录 |
| Ruff / pip / 数据 | 全部通过；Ruff包含本地实验脚本，GPU依赖不加入平台运行环境 |
| 前端 | Typecheck、ESLint、Vite构建、2项Vitest通过；Windows使用runner加载配置，保留Element Plus体积提示。本轮未重跑浏览器 |
| 迁移0017 | 隔离SQLite旧表基线上升/降/再升通过；[摘要](validation-artifacts/upload-20261112-migration-summary.json)，未验收PostgreSQL或SQLite从零迁移全链 |
| 规则路由 | [34/34](validation-artifacts/upload-20261112-routing-summary.json)，人工开发集，不是模型准确率或留出集 |
| 归档完整性 | 相对文档链接、冻结数据、历史验证摘要与六份本地LoRA摘要哈希检查通过 |

[本轮安全摘要](validation-artifacts/upload-20261112-summary.json)记录范围和未验收项。真实Temporal强杀恢复、Word渲染和浏览器记录为下方11月3日历史；本轮没有重跑这些实验。完整PostgreSQL/pgvector/Redis/MinIO栈、真实Embedding及新任务质量未验收；简历60条内部检索样本及提升幅度仍需原始材料。本次远端CI以PR检查为准，不能用旧的通过记录代替。

下方为2026-11-03及更早的分阶段记录，成绩不相加，也不自动覆盖本次新增功能。

## 动态问答增量（阶段A）

项目方案后续增量已完成单份闭环，详见[方案交付与限制](project-plan-delivery-2026-11-03.md)。全量回归192通过/2跳过；最后版式/渲染器保护后定向61通过。真实浏览器生成/审批/下载/修订门禁通过；真实Temporal强杀恢复、离线审批、对象写后崩溃幂等及2份历史重放通过。运行采用SQLite/Fake/合成资料；未做真实模型或Full质量验收。Word通过Microsoft Word实际渲染，2页逐页检查。摘要见[方案验收目录](validation-artifacts/README.md)。

Chat API与SSE现经ConversationSupervisor：通用概念直接回答；项目资料走检索角色，型号/规格走材料角色；两路独立则并发，材料身份依赖历史资料则顺序执行，不明确则澄清。API模式采用LangChain结构化意图与Pydantic校验，服务端覆盖漏检索/依赖错误并调度受限子Agent工具；Fake明确使用规则。普通问答不触发ReviewAgent。现有审查API保留，聊天中的审查请求不会自动创建任务；阶段A当时的方案生成意图返回未实现；后续方案闭环已接通，见本页新增记录。

工程验证：全量**178 passed / 2 skipped，121.14秒**，见[JUnit](validation-artifacts/conversation-routing-full-tests.xml)。随后修正角色调用的观测模型标识、同步OpenAPI后，问答/接口/原核心定向回归**76 passed，97.18秒**，见[最终JUnit](validation-artifacts/conversation-routing-final-tests.xml)，两者不相加。Ruff、pip依赖检查与原数据校验通过。本轮无表结构变更，消息键按租户/用户/项目/session派生；尚未做新入口的真实模型质量或新Full栈验收。

前端已从更新的OpenAPI重新生成类型；Typecheck、ESLint、2项Vitest及Vite构建通过，Vite使用runner配置加载。只调整问答页面说明与助手称呼，未新增路由状态控件，也未重跑浏览器交互；Element Plus包体积提示保留。

新增[34条人工编写路由开发样本](../data/eval/conversation_routes_v1.jsonl)，包含否定请求、解释性提问、缺指代和上下文。初次**33/34**，样本n02被多分派检索；[失败记录](validation-artifacts/conversation-routing-before-fix.json)保留。修复后**34/34**，见[规则路由摘要](validation-artifacts/conversation-routing-summary.json)，仅为开发集意图及执行策略符合率，不是模型准确率、回答事实正确率或检索质量。冻结集合SHA为`3f6f317a1888bcb983d56c48fef6c5cade99f787e11319c9989cff5e32ae5a9f`；最终运行源码SHA为`0333ac5a7173c681c3d843373ed003498259a7707b15def0228d1688b4c374c0`，运行中未变更。

已验证单路旧route兼容、两路实际重叠、依赖等待、歧义阻断、无结果/失败/超时区分、Schema失败有限重试、路由误判的取证门禁、当前项目文档边界、鉴权前不调用模型和SSE附加元数据。协议测试中的API模型均为本机替身，没有执行新的真实Qwen模型调用。新版SSE仍是回答完成后发送，不是逐Token生成流；旧前端继续消费token/sources，新routing元数据尚未增加专门展示控件。

后续[阶段B](project-generation-design-2026-11-03.md)首版已实施，见本页项目方案增量；阶段A记录和当时成绩保留，不把后续功能追认为当时已验收。

```powershell
$python = 'F:\code\homework\conda-envs\agent-membrane\python.exe'
& $python -m scripts.run_conversation_routing_eval --mode rules
# 仅配置获准公开资料API后使用；失败不转Fake：
# & $python -m scripts.run_conversation_routing_eval --mode api
```

## 当前闭环

项目授权 → 上传 → Temporal解析/切片/索引 → 声明业务元数据 → 条件检索 → 选定并冻结Evidence → Supervisor受限规划 → 检索/材料并行取证 → 综合审查 → 结构、引用、规则与覆盖门禁 → 人工处理 → 持久化决定 → 工作流终态。

- 三个StructuredTool为`review_retrieval`、`review_material`、`review_review`。API模式full也经过受限规划，但必须全角色；focused选择review时补齐前置依赖。Fake显式为确定性计划。
- Supervisor/Review共用STRONG配置，Retrieval/Material共用LIGHT配置；模型名待用户填写。本轮未用新组合进行真实模型质量评测。
- 项目发现使用已有PostgreSQL/pgvector/RRF/Reranker服务；审查检索工具只读冻结包，明确为snapshot_lexical，不能描述成每次都查pgvector。
- 模型发现需有效引用和逐字引文；服务端补问题ID、位置和状态。按角色检查processed/skipped，最多补审一次。价格资料可选；普通设计/规格审查不因缺报价失败。
- 资料声明有来源依据与CAS；单位和适用版本受限比较，新增面密度g/m²、kg/m²归一，不推导材料可替代或工程合格。
- 资料/报告可经鉴权下载Markdown；原件与Evidence正文/位置/哈希保留，报告不会自动变成源证据。

## 工程验收

| 检查 | 实测及边界 |
|---|---|
| GitHub Linux CI | **154 passed / 2 skipped，47.494秒**；[JUnit](validation-artifacts/github-linux-ci-tests.xml)；Ubuntu/Python 3.12、提交`87cdc2e`；前端Node 22 lint/2测试/类型构建亦通过 |
| GitHub发布副本全量 | **154 passed / 2 skipped，139.66秒**；[JUnit](validation-artifacts/github-publication-tests.xml)；Heartbeat修复及角色/接口同步后重新运行 |
| 角色/上下文/Markdown后端全量 | **154 passed / 2 skipped，108.01秒**；见[JUnit](validation-artifacts/README.md)；在后续Heartbeat修复之前 |
| Heartbeat修复后定向回归 | **29 passed，21.95秒**；工作流生命周期、审批与部署门禁；见[JUnit](validation-artifacts/README.md)，不与全量相加 |
| 最终API描述与类型同步后 | **54 passed，31.86秒**；接口、角色与部署门禁，见[JUnit](validation-artifacts/README.md)；有本机pytest缓存目录权限提示，不影响测试结果 |
| Ruff / pip / 数据 | 通过；200案例、43规格、60合成历史价格、30格式fixture |
| 前端 | Typecheck、ESLint、Build及2项Vitest通过；使用runner加载Vite配置；Element Plus体积提示仍在 |
| 数据库 | 本轮无表结构变更；此前0014—0016隔离SQLite升/降/再升通过，PostgreSQL迁移未验收 |
| 浏览器/MCP历史验收 | 2026-11-02资料与审查页及MCP已有记录；本轮新增Markdown按钮未重跑浏览器，不将历史截图称为当前全页面验收 |

历史记录：[资料页浏览器](validation-artifacts/README.md)、[审查页浏览器](validation-artifacts/README.md)、[MCP](validation-artifacts/README.md)、[迁移](validation-artifacts/README.md)。MCP已测stdio 5/HTTP 9工具、各3资源模板、401/403、无确认拒写、幂等创建/取消请求，未逐一执行HTTP批准/退回工具。

## 真实Temporal故障验收

官方Temporal CLI 1.9.1 / Server 1.32.0，SQLite业务存储、Fake Agent、TXT基础解析。是实际进程强杀和开发Server，不是Full存储/真实LLM/生产集群。

本轮先失败：[20261103T071827Z-40ec6036](validation-artifacts/README.md)。Worker离线审批用例超时，决定仍持久化为decision_pending；审批消费Activity缺少Heartbeat超时，强杀后需等最长2分钟执行超时。修复为15秒Heartbeat超时，保留command_id幂等事务。

修复后：[20261103T072252Z-8a8b8aef](validation-artifacts/README.md)，全部通过：

1. 解析拿到认领后强杀Worker，attempt 2接管且片段唯一。
2. 重复提交复用Workflow。
3. 报告实际提交后Activity失败重试，保留人工问题处理和提前提交的决定。
4. 裸Signal不能批准；等待期间重启并取消。
5. Worker离线提交批准，重启后消费持久命令并到approved。
6. Activity执行中取消，业务与Workflow均到终态。
7. 保存并重放**5份本次真实历史**。

源码SHA `1e26fcf0ef09ed1c59d7b5a9017ca0cb7c8c3a05ceeb40512e3582bc9d99b325`，运行中稳定。随后仅更新部分验收脚本的新角色断言与启动脚本/文档；不能把该运行称为最终全部文件哈希。未证明旧生产历史兼容、生产故障切换、terminate对账或批量吞吐。

## 当前业务回归：v3

因Agent角色和“价格可选”策略变化，新建冻结v3；旧v1/v2字节和结果保留。24条人工合成开发案例，**13正常/11需人工**，不是独立测试或内部真实项目。

[20261103T071719Z-37b2db6a](validation-artifacts/README.md)：**24/24通过，问题TP12/FP0/FN0**；运行模式为Fake，只检查规则、工具编排和系统交接，不能作为模型语义准确率。耗时p50 228.97ms / p95 324.87ms含入库，不是LLM耗时。

源码SHA `828c0e69f989869a02196b08cac86ecbf0ae1e51728c9113e7b112801d0cec3d`，运行中稳定。使用开发集迭代、有规则参与、缺少单Agent/规则消融，不能声称多Agent提升或LLM 100%准确。

## 检索：上下文开关对照

冻结[集合](../data/eval/retrieval_business_v1.json)：119份合成资料、30查询（23有答案/7无答案），固定30候选、文档去重Top10。Local SQLite词项合同模式，不用Fake向量填真实Embedding成绩。

| 模式 | Recall@10 / MRR@10 | 执行错误 / 硬过滤越界 | 语义改写 |
|---|---|---|---|
| [contextual off](validation-artifacts/README.md) | 0.869565 / 0.869565 | 0 / 0 | 3/3漏召回 |
| [contextual on](validation-artifacts/README.md) | 0.869565 / 0.869565 | 0 / 0 | 3/3漏召回 |

两次源码SHA同上且稳定；无答案7/7返回空只是空返回率，不是问答拒答准确率。metadata-v1只增加来源/章节等元信息，本数据主要为TXT，未证明质量增益；无LLM摘要或指代消解。单独功能测试覆盖标题命中且返回原文。开关默认关闭，改变向量命名空间，启用须重建。

此前[Embedding端点探测](validation-artifacts/README.md)两个端点403。本轮没有真实纯向量、混合或Reranker质量增益，不支持简历“60条内部、Recall≥90%、MRR相对+30%”；该历史数字仍需原始样本、标签和逐条运行证明。

## 公开资料落地检查

来源与哈希见[清单](../data/manifests/public-references-v1.json)。从Birdair官方目录取得2012年的ETFE/PVC-PVDF历史资料2份，PDF目视核对厚度/面密度，以及总厚度与涂层厚度区别。basic解析分别2/5个片段，哈希、页码字面和Markdown导出通过，见[记录](validation-artifacts/README.md)。PTFE目录下载失败保留；不证明MinerU、复杂表格全部正确或新项目适用性。原件与全文MD不进Git/部署ZIP。

## 历史真实模型回归

[20261102T094647Z-9d724049](validation-artifacts/README.md)，qwen3.7-flash，旧角色/旧价格必选策略v2、24条开发案例（12正常/12需人工），24/24、问题TP13/FP0/FN0，p50 7.69s / p95 12.71s含入库。对应SHA `bd1a41f11df0297a4c4b78ace3b52a47ed037654ae5bedbdb26559313c482b62`。不能搬作当前新角色/强弱路由成绩；旧v1的21/24及探索失败仍保留。

## 部署和未完成项

已提供Compose、前后端Dockerfile、随机凭据初始化、启动门禁及真实HTTP/pgvector/Temporal验收入口，见[部署说明](deployment.md)。18项部署门禁已测，Compose可解析；本机Linux Engine未运行，容器镜像和完整栈没有成功记录。[GitHub Actions](https://github.com/xbzz1018/membrane-engineering-knowledge-agent/actions/runs/41604101091)已通过后端和前端检查，Compose smoke此次跳过。首次CI在提交`27e8d14`因缺少greenlet失败，修复依赖声明为`sqlalchemy[asyncio]`后通过；[失败记录](https://github.com/xbzz1018/membrane-engineering-knowledge-agent/actions/runs/41603661769)保留。可分享记录另见[安全摘要](validation-artifacts/README.md)。

真实PostgreSQL/pgvector、Redis、MinIO整栈，真实Embedding/新强弱模型对照，MinerU/OCR，专家独立标注与实际业务试用均待验收。该阶段模型通过API接入，尚未归档微调材料；11月12日已补本地实验与可选任务接入，公司LoRA权重及其GPU部署仍未在本仓库核实。

## 新演示HTTP验收

已保留v2进程记录与数据，启动隔离v3演示并通过真实HTTP创建新资料/待复核报告。[记录](validation-artifacts/README.md)验证admin登录、新角色拓扑/结果、两种Markdown下载和no-store、OpenAPI快照及前端HTTP。并核对已保存3份审查历史，均在检索/材料完成后才调度审查。此检查没有浏览器交互，也未使用真实模型。

## 复跑

```powershell
$python = 'F:\code\homework\conda-envs\agent-membrane\python.exe'
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
& $python -m pytest -q -p pytest_asyncio.plugin
& $python scripts\validate_temporal_local.py
& $python scripts\run_business_eval.py --mode fake
& $python scripts\run_business_retrieval_eval.py --mode local-contract --contextual off
& $python scripts\run_business_retrieval_eval.py --mode local-contract --contextual on
& .\scripts\start_demo.ps1 -Temporal -Mcp
& $python scripts\seed_temporal_demo.py
```

演示使用隔离v3数据库/队列，旧v2保留。开发入口http://127.0.0.1:5173，账号admin / admin-change-me。同步旧验收脚本不得用于异步演示。详细操作见[运行手册](operator-runbook.md)。
