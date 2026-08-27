# 调研与实现发现

## 基线

- 源码来自天宫医疗 day05 知识问答 Agent。
- 源码已经包含 LangGraph Checkpoint、Milvus、Neo4j、Redis、MinIO、文档摄取和长期记忆雏形。
- 原始 day05 中的 inquiry 医疗流程、药品数据和医疗 Prompt 已从独立副本删除；入口已改为工程领域模块。
- 目标项目必须支持无 Key 的 Fake 模式，真实模型通过 OpenAI 兼容接口接入。

## 运行约束

- 项目 Conda 环境放在 F 盘，不使用默认 envs 目录。
- MinerU 现成环境位于 `F:\code\homework\project\1_membrane_project_precheck\runtime\envs\mineru`，版本 3.4.4。
- Temporal、DeepAgents 和 Kafka 使用可选依赖/Profile，不阻塞普通问答启动。
- 新项目已安装并验证 `deepagents==0.7.9`、`temporalio==1.32.0`、`aiokafka==0.14.0`、`pymilvus==2.6.17`、`neo4j==5.28.4` 和 `minio==7.2.20`。

## 安全与数据

- 公开资料保存来源、许可证、下载时间和 SHA-256。
- 公司内部文件、客户信息、真实合同和真实报价不得提交。
- 合成价格只能用于测试，不能描述为市场报价。

## 已实现链路

- 默认 `RUNTIME_MODE=local` 使用 F 盘项目内 SQLite、上传目录和 fixture，不依赖 Docker 或 API Key。
- `MODEL_MODE=api` 使用 DashScope/DeepSeek/OpenAI 兼容接口，失败时返回可识别的 Fake fallback 元数据。
- DeepAgents 只处理多文档资料包；Temporal 只处理长任务；Kafka 只处理批量事件。
