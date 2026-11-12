# 前端设计与业务QA

更新：2026-11-02。沿用已有Element Plus工作台的导航、密度、颜色与表格层级。本阶段用户确认增加业务信息、检索和证据能力。

## 当前实际浏览器验收

- 桌面1440px、移动390px；上传并等待真实异步索引，编辑/重载型号、版次、生效日期、来源声明。
- 调用真实条件检索API，验证PTFE-5020不被当PTFE-502、返回证据定位与原文、空结果、旧锁409及冲突后重载。
- 移动表格内部滚动，页面无横向溢出；测试page_errors为空。
- 审查页经过整套服务重启后可读取待复核示例；新任务自动从queued进入awaiting_approval；退回先decision_pending再rejected，终态隐藏操作。
- Typecheck、ESLint、Build通过；Vitest 2项通过。Element Plus vendor chunk仍有超过500KB的提示。

证据：[资料页记录](validation-artifacts/README.md)、[桌面截图](validation-artifacts/README.md)、[移动截图](validation-artifacts/README.md)、[异步审查记录](validation-artifacts/README.md)、[报告截图](validation-artifacts/README.md)。截图使用SQLite/Fake与真实Temporal开发服务，不代表模型质量或生产验收。

## 保留的早期视觉记录

最初选定参考为data/runtime/design-references/option-1-element-plus.jpg，原始视觉截图位于data/runtime/frontend-qa/。其桌面/平板/移动仪表盘与路由验收属于早期实现记录，新增功能以本页当前证据为准。
