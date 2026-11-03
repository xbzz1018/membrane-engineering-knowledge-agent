# GitHub 更新记录

更新：2026-11-03。项目使用现有私有仓库 `xbzz1018/membrane-engineering-knowledge-agent`，默认分支为 `main`。本次从原快照 `cf013d7ebf84c7141068bbe8ad32dac8b3e7395d` 建立 `feat/resume-review-deployment`，通过 PR 提供实现与文档供审阅。

## 本次更新

- 项目首页按业务流程、代码入口、部署方法和验证记录组织；补充代码导览与 PR 模板。
- 同步检索/材料/审查三个工具化 Agent、强弱模型配置路由、上下文元信息、Markdown 下载及审批恢复修复。
- 保留部署包、随机凭据生成、后端/前端 CI 和手动 Compose smoke 入口。
- 增加仓库检查：Markdown 相对链接、冻结评测数据 SHA-256 与验证归档完整性。
- 个人主页采用精选项目、代表性贡献和完整贡献记录的结构，提供中英文版本及原创明暗 SVG 横幅。工程审查项目只作简要介绍并标注“私有”。

项目可见性保持私有。主页内容仅包含经核验的公开项目、本人已合并 PR 及用户授权的私有项目概要。没有把复现新增代码追认为历史实习贡献，也没有使用未经原始记录支持的内部评测数字。

## 发布与检查

项目代码通过功能分支与 PR 更新；个人主页发布到其专用公开仓库 `xbzz1018/xbzz1018`。不强制推送、不覆盖远端独立文件，不关闭或合并现有 Dependabot PR。

发布副本后端重新运行 **154 passed / 2 skipped**；Ruff、依赖检查、数据检查与仓库检查通过。JUnit 已归档并脱敏主机名。GitHub Actions 状态以远端实际运行记录为准；完整容器栈及新强弱模型验收另行记录，不以单元测试替代。

提交范围排除 `.env`、密钥、上传资料、运行数据库、完整模型响应、缓存及依赖目录。保留原 `.github/dependabot.yml` 和规划文件。评测数据与验证归档按原始字节保存，避免跨平台换行改变冻结哈希。详细模式、分母、失败记录和当前限制见[当前验证](current-validation.md)。

## 远端结果

- [个人主页](https://github.com/xbzz1018)经[PR #1](https://github.com/xbzz1018/xbzz1018/pull/1)合并到main，中英文与横幅已发布，发布后的[检查](https://github.com/xbzz1018/xbzz1018/actions/runs/41603952361)通过。
- [项目PR #22](https://github.com/xbzz1018/membrane-engineering-knowledge-agent/pull/22)已推送，保留供审阅，项目main未合并。
- 提交`87cdc2e`的[项目CI](https://github.com/xbzz1018/membrane-engineering-knowledge-agent/actions/runs/41604101091)前后端通过；Ubuntu/Python 3.12后端154通过/2跳过，Node 22前端lint/2测试/类型构建通过。首次CI缺少greenlet，已通过`sqlalchemy[asyncio]`声明修复，不删除失败记录。
- 仓库简介与技术topics已更新，可见性保持私有；完整Compose smoke此次跳过，新模型组合尚待验收。
