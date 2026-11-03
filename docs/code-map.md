# 代码导览

按“业务请求→数据→执行→结果”阅读，先看应用服务，再看协议适配与基础设施。

| 要理解的问题 | 代码入口 |
| --- | --- |
| 审查如何提交、授权并冻结证据 | [application/reviews.py](../src/application/reviews.py)、[review_manifest.py](../src/infrastructure/review_manifest.py) |
| Supervisor怎样调用子Agent工具 | [subagent_tools.py](../src/agents/subagent_tools.py)、[review_agents.py](../src/agents/review_agents.py) |
| 子Agent查到了什么，是否保留单位 | [evidence_tools.py](../src/agents/evidence_tools.py)、[review_roles.py](../src/domain/review_roles.py) |
| 强弱模型怎样选择 | [model_provider.py](../src/infrastructure/model_provider.py)、[config.py](../src/core/config.py) |
| 条件检索、向量、融合与重排 | [retrieval.py](../src/infrastructure/retrieval.py)、[pgvector_store.py](../src/infrastructure/pgvector_store.py)、[database.py](../src/infrastructure/database.py) |
| 单位/版本规则与引用门禁 | [review_rules.py](../src/domain/review_rules.py)、[material_mass.py](../src/domain/material_mass.py)、[model_finding_gate.py](../src/domain/model_finding_gate.py) |
| Workflow与Activity分别做什么 | [temporal_definitions.py](../src/workflows/temporal_definitions.py)、[activities.py](../src/workflows/activities.py) |
| 重启、重复执行和审批如何保护 | [ingest_claim.py](../src/infrastructure/ingest_claim.py)、[review_decisions.py](../src/infrastructure/review_decisions.py) |
| Markdown与检索增强如何分离 | [representations.py](../src/documents/representations.py) |
| 前端声明、检索与复核怎么联调 | [前后端合同](frontend-contract.md)、[views](../frontend/src/views) |
| MCP是不是内部编排链路 | [mcp/server.py](../src/mcp/server.py)、[架构说明](architecture.md) |
| 评测与故障怎样复跑 | [run_business_eval.py](../scripts/run_business_eval.py)、[run_business_retrieval_eval.py](../scripts/run_business_retrieval_eval.py)、[validate_temporal_local.py](../scripts/validate_temporal_local.py) |

项目检索与冻结包内查询是两个范围；LLM输出与人工问题状态是两种产物；业务库与向量索引职责不同。阅读时先明确这些边界，再展开具体算法。
