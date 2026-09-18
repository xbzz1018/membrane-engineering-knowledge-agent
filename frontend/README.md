# 膜构智审前端

Vue 3 + TypeScript + Vite + Element Plus 企业工程资料审查工作台。前端只调用 FastAPI REST/SSE，不直接调用 PostgreSQL/pgvector、MinIO、Temporal 或 MCP。

## 启动

```powershell
cd F:\code\homework\project\membrane-engineering-knowledge-agent\frontend
npm install --registry=https://registry.npmmirror.com
npm run dev
```

默认地址：`http://127.0.0.1:5173`，后端地址由 `VITE_API_BASE_URL` 配置，默认 `http://127.0.0.1:8080`。

## 门禁

```powershell
npm run typecheck
npm run lint
npm run test
npm run build
npm run test:e2e
```

前端只使用真实接口；后端不可用时显示错误，不自动填充演示数据。页面不保存 API Key、Prompt、隐藏推理或 MCP 长期密钥。
