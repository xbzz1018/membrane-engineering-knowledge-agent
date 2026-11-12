# 模型适配与实验范围

更新：2026-11-12。公司实习、后续本地训练和当前平台接入分别记录。

| 范围 | 模型与任务 | 依据与限制 |
| --- | --- | --- |
| 用户陈述的公司实习 | Qwen3.5-4B；查询标准化、审查结果整理 | 用户确认参与训练，提供rank=16、BF16、学习率2e-4；公司权重、原始日志、数据规模、确切batch/epoch/target_modules尚未在本仓库核实 |
| 11月本地复现 | Qwen3-0.6B；query_rewriter、grounded_qa | 每任务600训练/100验证/100测试，rank=8；已有配置和评估摘要。证据问答不等于审查结果整理 |
| 当前平台接入 | 可配置的user、shencha任务别名 | 实现查询前改写和审查后的辅助整理；协议测试通过不表示Qwen3.5 GPU部署或质量验证通过 |

## 平台中的两个任务

授权、意图路由之后，API模式的查询Agent可调用查询标准化Adapter。输入输出为纯文本；型号、日期、版次的字面标识不一致时标记rejected_original_query并保留原查询。检查通过也同时保留原问题。该检查不能保证所有语义约束等价，效果仍需独立业务样本验证。通用问答不使用此Adapter。

领域审查与规则校验形成问题单后，审查整理Adapter根据问题单和对应原始证据输出辅助说明。后端核对问题ID、实际/要求值、引用与新增数字；说明附于报告，不改变结构化问题、严重性、状态或批准权限。字面检查不等于完整语义验证，仍交人工复核。无问题不调用，模型失败或输出非法显式失败。Temporal在Activity内调用模型并持续Heartbeat。

入口：[model_tasks.py](../src/application/model_tasks.py)、[knowledge_agent.py](../src/agents/knowledge_agent.py)、[review_agents.py](../src/agents/review_agents.py)。

## 配置、启动与核验

以下是当前接入协议的配置示例，不是公司部署记录。两个权重必须为同一底座、相应任务及提示词协议训练；不能将grounded_qa改名为shencha后直接用于工程审查。

```dotenv
MODEL_MODE=api
LORA_TASKS_ENABLED=true
LORA_API_BASE=http://127.0.0.1:8000/v1
LORA_API_KEY=replace-with-your-local-server-token
LORA_QUERY_MODEL=user
LORA_REVIEW_MODEL=shencha
```

Supervisor及普通Agent继续使用已有通用/STRONG/LIGHT配置；任务服务按model字段选择上述别名。功能默认关闭，Fake不提供LoRA推理，资料分级门禁保持生效。

```bash
python scripts/serve_task_adapters.py --base /models/the-exact-base \
  --query-adapter /models/query-normalization --review-adapter /models/review-organization
# 默认只预检并输出命令；确认架构、版本与资源后显式加 --execute 启动。
python scripts/validate_lora_routes.py
```

预检核对Adapter类型、底座标识、rank和权重文件存在性；注册验证只GET /models，不进行推理。不证明权重有效、目标模块受vLLM版本支持或GPU容量充足。本轮未启动Qwen3.5-4B/vLLM，未编造吞吐或延迟。

## 本地复现与历史指标

[本地实验目录](../experiments/local_lora/README.md)归档现有训练、评估、部署脚本和六份原始摘要，保留SHA-256；不上传公司资料、模型权重或完整预测。查询改写的格式及字符指标改善；证据问答格式和摘录比例改善，但答案EM从44%到43%。这些是0.6B公开数据实验成绩，不能套用为公司4B或当前新任务的成绩。

简历中的60条内部检索样本、Recall@10超过90%及MRR相对提升约30%，仍需原始标签、基线和逐条结果支持；本地合成集合不替代它们。
