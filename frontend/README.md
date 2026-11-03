# 膜构智审前端

Vue 3 + TypeScript + Vite + Element Plus工程资料工作台，只调用FastAPI REST/SSE。

## 本机运行

项目路径：F:\工作\04项目资料\简历项目\资料智能审查落地版\frontend。优先从项目根运行scripts/start_demo.ps1 -Temporal -Mcp，同时启动API、前端、真实Temporal开发服务、Worker和MCP。默认入口http://127.0.0.1:5173，开发账号admin / admin-change-me。

当前node_modules是复用原项目依赖的Junction，**不要通过它执行npm ci/install或升级**。迁移到新目录后使用独立node_modules执行npm ci，再npm run dev。Vite缓存和dist写在本副本；VITE_API_BASE_URL默认http://127.0.0.1:8080。

容器部署见[部署说明](../docs/deployment.md)。Docker 构建时显式设置空 `VITE_API_BASE_URL`，REST/SSE 使用同源 Nginx；独立 checkout 可按上面的常规 npm 命令安装。本机 Junction 下构建/测试可加 `--configLoader runner`，避免 Vite 将临时配置写回原依赖目录。

## 功能与校验

资料页业务信息声明含型号、适用版次、生效区间和声明依据；保存携带expected_lock_version，409后重载再提交。条件检索和证据抽屉连接实际API，未知日期不猜测。审查页每6秒刷新进行中的任务，decision_pending不显示为已批准，终态隐藏操作。

```powershell
npm run typecheck
npm run lint
npm run test -- --run
npm run build
# 已运行异步演示及seed后
node scripts/browser_documents.mjs
node scripts/browser_temporal.mjs
```

浏览器脚本会创建合成测试资料/报告。前端不保存API Key、Prompt、隐藏推理或MCP长期密钥；服务不可用显示错误。当前验收与截图见[设计QA](../docs/design-qa.md)。
