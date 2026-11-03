# 可分享的验证摘要

这里保存经过内容检查的合成开发验收摘要，不包含密钥、业务数据库、原始上传、完整模型响应或用户资料。它们是历史运行证据，不表示当前所有源码均重新运行了同一实验；各次源码 SHA 与模式以记录为准。部署镜像构建及整栈验收尚未完成，GitHub Actions 尚未运行。

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
