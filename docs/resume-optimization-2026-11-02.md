# 按简历四项完成的实现

日期：2026-11-02。独立复现副本，保留子Agent封装工具；新增代码不能追认为历史团队个人贡献。完整实测和限制见[当前验证](current-validation.md)。

| 简历项 | 实现与代码入口 | 已有支撑 |
|---|---|---|
| 多Agent审查编排 | review_agents.py、subagent_tools.py；full固定三领域、focused受限规划；模型最小Schema、引文、领域覆盖与比较门禁 | 工具并行定向测试；前阶段24条真实模型合成开发回归 |
| 精确与语义检索 | document_search.py、document_filters.py、database.py、pgvector_store.py；业务元数据CAS、相同硬过滤、RRF和Reranker接口 | 资料页实测；119文档/30查询词项回归，语义改写3条漏召回；真实向量受403阻塞 |
| 业务工具与MCP | knowledge应用服务、KnowledgeAgent工具、mcp/server.py共用条件及项目范围 | REST/Tool/MCP跨协议查询；stdio与HTTP真实验收，幂等及确认门禁 |
| Temporal长任务 | review_manifest/lifecycle/decisions、ingest_claim、activities及temporal_definitions | 真实Server强杀重启、提交后失败重试、离线决定、取消及5份历史重放 |

数据库迁移0014业务声明、0015审查快照、0016解析认领表。前端保留既有工作台，增加声明编辑、条件检索、证据抽屉与异步状态刷新。

## 可演示的业务流程

1. 项目内上传设计、规格、历史价格；Temporal异步解析索引。
2. 资料列表编辑业务信息，填写型号、适用版次、生效区间和声明依据。声明人来自服务端，版本冲突需重载。
3. 条件检索选择PTFE-502/R1/业务日期，近似型号PTFE-5020及过期资料不命中；点证据看原文定位。
4. 发起完整审查，三个领域Agent工具执行；支持比较由规则核验，缺证/不支持的判断转人工。
5. 人工解决或带原因忽略问题；提交决定后先显示decision_pending，Temporal消费后终态。未处理阻断不能批准，旧锁版本409。
6. 可停止并重启整套本地服务，待复核任务仍可继续；故障脚本另验证Activity提交窗口与强杀后恢复。

## 面试可以展开的修复

- 模型曾生成错误的服务端引用版本类型。现在只产出发现/引文，版本、定位、问题状态由服务端生成。
- 模型曾混比不同适用版本和税口径。现在支持的比较经确定性作用域规则验证，其他提议保留人工判断。
- 报告保存后Activity失败，旧代码可能在重试时覆盖人工状态。现在机器发布一次，人工决定持久化并幂等消费；已在真实Temporal服务注入提交后故障。
- Worker被杀后资料遗留indexing，单纯“已占用”检查会阻止新尝试恢复。现在按执行身份和递增attempt接管，每次持久写检查围栏；真实强杀后attempt2完成且片段不重复。

## 简历表述参考

以下用于本次复现；原实习请保持本人实际承担的“参与/开发/联调”边界：

- 多Agent审查编排：基于LangChain将设计、材料、价格Agent封装为工具，由Supervisor按受控领域计划调用；实现结构化输出、原文引用核验、领域覆盖补审与人工复核。
- 条件检索：实现型号、适用版次及业务日期的SQL硬过滤，贯通词项与pgvector召回条件、RRF及Reranker接口；建设119份合成资料、30条分层开发查询，保留逐条排序、无答案和语义漏召回记录。
- 业务工具与MCP：复用应用服务封装资料、规格与历史价格工具，联通问答Tool Calling及MCP stdio/HTTP，验证项目权限、确认门禁及幂等创建。
- 异步执行与恢复：完善Temporal解析、索引和审查流程，增加执行认领、证据快照、报告幂等发布和持久审批命令；在真实开发Server完成Worker强杀/重启、重试、取消及5份历史重放验收。

后端126 passed/2 skipped；浏览器及MCP实际链路通过。Temporal验收使用SQLite/Fake/TXT，不声称生产集群恢复；Embedding403，真实pgvector及MinerU未完成。Recall≥90%/MRR相对30%没有内部数据证据，不用这次合成成绩替代。

累计变更见[清单](validation-artifacts/README.md)和[补丁](validation-artifacts/README.md)；面试追问见[综合说明](../面试准备-膜构智审-综合版.md)。
