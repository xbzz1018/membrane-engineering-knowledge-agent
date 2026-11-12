# 可分享的验证摘要

这里保存经过内容检查的合成开发验收摘要，不包含密钥、业务数据库、原始上传、完整模型响应或用户资料。它们是历史运行证据，不表示当前所有源码均重新运行了同一实验；各次源码 SHA 与模式以记录为准。部署镜像构建及整栈验收尚未完成；[11月3日GitHub Actions](https://github.com/xbzz1018/membrane-engineering-knowledge-agent/actions/runs/41604101091)通过后端及前端，未运行Compose smoke。

## 2026-11-12 上传副本

| 记录 | 实际范围 |
|---|---|
| [后端JUnit](upload-20261112-backend-tests.xml) | 218通过/2跳过，69.40秒；Local/Fake、API协议替身 |
| [安全摘要](upload-20261112-summary.json) | 修复前失败、最终检查和未验收项；不是真实模型质量报告 |
| [迁移](upload-20261112-migration-summary.json) | 隔离SQLite旧表基线，0017升/降/再升 |
| [规则路由](upload-20261112-routing-summary.json) | 34条人工开发样本，34通过；非留出集或模型成绩 |

公司4B与本地0.6B实验分开，六份本地训练/评估摘要的独立清单见[本地实验](../../experiments/local_lora/README.md)。本轮没有重跑下方真实Temporal、浏览器或Word渲染历史验收。

## 2026-11-03 动态问答入口

| 记录 | 实际范围 |
|---|---|
| [动态问答全量JUnit](conversation-routing-full-tests.xml) | 178通过/2跳过；角色观测标签最后修正之前 |
| [最后定向JUnit](conversation-routing-final-tests.xml) | 76通过；问答/接口/原核心，不与全量相加 |
| [规则路由首轮](conversation-routing-before-fix.json) | 34条人工开发样本，33通过；否定审查语句多分派一路检索 |
| [修复后规则路由](conversation-routing-summary.json) | 相同样本34通过，记录源码及数据SHA；不是API模型或回答质量成绩 |

此处阶段A记录对应当时实现；后续单份方案闭环见下方新增记录。真实模型与Full部署未在本增量中验收。

## 2026-11-03 项目初步方案

本地生成、审查、同版审批和MD/Word导出记录：[全量](project-plan-full-tests.xml)、[最终定向](project-plan-final-tests.xml)、[Temporal](project-plan-temporal-summary.json)、[浏览器](project-plan-browser-summary.json)、[迁移](project-plan-migration-summary.json)、[Word渲染](project-plan-word-render.json)。均为Local/Fake；保留[取证失败](project-plan-temporal-before-fix.json)及[启动失败](project-plan-temporal-startup-failure.json)。

## 2026-11-03 新角色与上下文增量

| 记录 | 实际范围 |
|---|---|
| [GitHub Linux CI JUnit](github-linux-ci-tests.xml) | 提交87cdc2e，Ubuntu/Python 3.12，154通过/2跳过，47.494秒；前端lint/2测试/类型构建亦通过 |
| [GitHub发布全量JUnit](github-publication-tests.xml) | 154通过/2跳过，修复及接口同步后的发布副本重新运行，139.66秒 |
| [新角色全量JUnit](role-context-markdown-tests.xml) | 154通过/2跳过，Heartbeat修复前 |
| [恢复修复定向JUnit](role-recovery-followup-tests.xml) | 29通过，不与全量相加 |
| [最终接口/角色门禁JUnit](role-final-contract-tests.xml) | 54通过，API角色说明及类型同步后；pytest缓存目录权限提示保留 |
| [Temporal失败](role-temporal-before-fix.json) / [修复后](role-temporal-summary.json) | 保留离线审批超时；15秒Heartbeat修复后全通过，5份历史replay |
| [v3业务回归](role-business-v3-summary.json) | Fake、24开发案例（13正常/11人工）、24通过，不代表新模型质量 |
| [上下文off](contextual-off-summary.json) / [on](contextual-on-summary.json) | 同一119资料/30查询，SQLite词项；Recall/MRR均0.869565，3条改写漏召回，无增益结论 |
| [公开2PDF](public-references-basic.json) | basic页码/字面/MD烟测；非MinerU或准确率评测 |
| [新演示HTTP](role-demo-http.json) | 新角色、两种MD下载、OpenAPI、前端HTTP；3份历史依赖检查；未重跑浏览器 |

本轮模型名待填，强弱组合真实模型与完整容器栈尚未验收。下面记录是前阶段历史，不覆盖本轮新角色行为。

| 记录 | 范围 |
|---|---|
| [部署包阶段 JUnit](deployment-package-tests.xml) | 2026-11-03 后端 144 通过 / 2 跳过；不是容器验收 |
| [部署配置门禁 JUnit](deployment-preflight-tests.xml) | 18 项随机凭据/覆盖保护/模式/维度校验 |
| [Temporal 摘要](temporal-local-summary.json) | 真实开发 Server + SQLite/Fake/TXT，强杀、恢复、取消、离线决定和 5 份历史重放 |
| [检索开发集摘要](retrieval-business-summary.json) | 合成 119 文档/30 查询，词项模式，3 条语义改写漏召回 |
| [审查开发集摘要](business-review-summary.json) | 24 条合成开发案例，前阶段真实模型；不证明生产质量 |
| [资料页](documents-browser.json) / [审查页](temporal-browser.json) | 本机真实浏览器和 API 验收 |
| [MCP](mcp-summary.json) | 本机 Local/Fake、真实协议握手及鉴权 |
| [迁移](ingest-migration.json) | 隔离 SQLite 0016 升降；未测 PostgreSQL |
| [Embedding 失败](embedding-probe.json) | 两个配置端点 403，无语义成绩 |

旧文档里的运行目录、截图、完整逐条预测和历史 patch 仅保存在原本地交付副本。Git 更新副本中的相关链接统一指向本页，保留标签以便识别原记录；这不意味着完整原始材料已上传。复跑方法见[评测协议](../evaluation-protocol.md)及[当前验证](../current-validation.md)。原始材料摘要 SHA 见 `evidence-index.json`，只用于核对本机归档，不代表独立第三方认证。
