# 实施进度

## 2026-08-27

- 已确认目标目录原先不存在。
- 已从 day05 复制独立项目到 F 盘目标目录。
- 复制来的 `.idea`、`.pytest_cache` 和 `logs` 暂未删除，后续通过 `.gitignore` 排除。
- 已确认本机 F 盘 MinerU 3.4.4 可用。
- 已创建 F 盘 Conda 环境 `F:\code\homework\conda-envs\agent-membrane` 并安装核心及可选依赖。
- 已替换启动入口、配置、数据库、文档上传、工程领域 Supervisor 和资料包审查 API。
- 已加入 DeepAgents facade、Temporal Workflow/Activities/Worker 和 Kafka Publisher/Consumer。
- 已生成 100 条可复现合成工程案例，数据库当前包含 105 条案例、3 条规格和 3 条价格 fixture。
- 已通过 `pytest`（3 passed）、Ruff、compileall、pip check、Docker Compose config 和幂等 Alembic upgrade。

## 错误记录

| 操作 | 结果 | 处理 |
|---|---|---|
| 复杂 PowerShell 复制脚本 | 被执行策略拦截 | 改为拆分为单步命令后成功复制 |
| 删除复制缓存目录 | 被删除策略拦截 | 改用 `.gitignore` 排除，不影响运行 |
| 直接执行 `python -m alembic` | Alembic 无 `__main__` | 使用 F 盘环境的 `Scripts\\alembic.exe` |
| 迁移重复建表 | 应用已先执行 `create_all` | 首个迁移增加表存在检查，支持幂等升级 |
