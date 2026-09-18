---
name: membrane-package-review
description: 通过膜结构工程 MCP 工具检索项目资料与证据，并在明确确认后发起、跟踪或处理资料包审查。适用于设计、膜材和价格资料的一致性审查，不用于结构安全计算、正式报价或资料修改。
---

# 膜结构资料包审查

使用平台提供的 MCP 工具组合审查流程。MCP 是外部接入层；不要绕过工具直接访问数据库、向量库、对象存储或 Temporal。

## 检索与取证

1. 明确 `project_id`、审查目标和资料范围。信息不足时先向用户确认，不猜测项目。
2. 用 `search_project_documents` 查找候选资料；需要型号或价格背景时分别调用 `query_material_specs`、`query_price_records`。
3. 用 `get_document_evidence` 找到稳定 Evidence ID，再读取 `membrane://documents/{document_id}/evidence/{evidence_id}` Resource 核对关键片段。需要核对文档版本和解析状态时读取 `membrane://documents/{document_id}`。
4. 只把工具实际返回的内容作为证据。无证据、来源冲突或资料缺失的内容标为待人工确认。

## 发起与跟踪审查

- 正式资料包审查使用 `full`，固定覆盖设计、膜材和价格三个领域；只有用户明确要求专项审查时才使用 `focused`。
- 调用 `create_review_request` 前，先向用户说明资料数量、审查模式和将产生的副作用，并取得明确确认。为每个业务请求生成稳定且不复用到其他请求的幂等键。
- MCP v2 客户端必须完成工具返回的 Multi Round-Trip Elicitation。客户端不支持确认、用户拒绝或取消时立即停止，不用其他接口绕过。
- 用 `get_review_status` 查询进度。长任务未完成时报告当前状态，不重复创建审查。
- 审查完成后读取 `membrane://reviews/{review_id}/report`，以 Resource 中的问题单和证据作为展示依据。

## 审批与退回

- 永不自动批准或退回。只有审核人明确要求后才调用相应工具。
- 操作前重新查询状态，使用最新 `lock_version`；版本冲突时重新展示现状并再次确认。
- 退回必须提供用户认可的原因。取消仅用于用户明确要求停止尚未完成的审查。
- 权限不足、跨项目、非公开资料、Elicitation 不可用或工具失败时立即停止，说明可见错误，不尝试越权或降级。

## 边界

该流程只处理 MCP 当前允许的 `public` 资料。不得上传或删除文件、修改膜材规格或价格、修改问题单、生成正式报价、执行结构安全判断，也不得收集或保存 API Key、JWT、Prompt 正文或隐藏推理。
