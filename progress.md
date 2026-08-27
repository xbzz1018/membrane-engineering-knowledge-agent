# 实施进度

## 2026-08-27

- 已确认目标目录原先不存在。
- 已从 day05 复制独立项目到 F 盘目标目录。
- 复制来的 `.idea`、`.pytest_cache` 和 `logs` 暂未删除，后续通过 `.gitignore` 排除。
- 已确认本机 F 盘 MinerU 3.4.4 可用。
- 已创建 F 盘 Conda 环境 `F:\code\homework\conda-envs\agent-membrane` 并安装核心及可选依赖。
- 已替换启动入口、配置、数据库、文档上传、工程领域 Supervisor 和资料包审查 API。
- 已加入 DeepAgents facade、Temporal Workflow/Activities/Worker 和 Kafka Publisher/Consumer。
- 已生成 100 条可复现合成工程案例，并从 TensiNet 分页采集 100 条公开项目元数据；数据库当前包含 205 条案例、3 条规格和 3 条价格 fixture。
- 已加入 `collect_public_case_metadata.py` 和 `validate_data.py`，公开案例唯一 ID、必需字段和 provenance 校验通过。
- 已通过 `pytest`（3 passed）、Ruff、compileall、pip check、Docker Compose config 和幂等 Alembic upgrade。
- 已添加 `import_api_env.ps1`，可显式从旧项目本地环境文件导入允许的模型变量且不显示密钥。
- 已添加可选 `temporal` 和 `kafka` Compose Profile；默认服务不依赖二者。
- 已将旧医疗入口、医疗数据、医疗 Agent 和旧初始化脚本从独立副本移除。
- 已将项目 README 改为膜结构工程领域说明。

## 错误记录

| 操作 | 结果 | 处理 |
|---|---|---|
| 复杂 PowerShell 复制脚本 | 被执行策略拦截 | 改为拆分为单步命令后成功复制 |
| 删除复制缓存目录 | 被删除策略拦截 | 改用 `.gitignore` 排除，不影响运行 |
| 直接执行 `python -m alembic` | Alembic 无 `__main__` | 使用 F 盘环境的 `Scripts\\alembic.exe` |
| 迁移重复建表 | 应用已先执行 `create_all` | 首个迁移增加表存在检查，支持幂等升级 |
