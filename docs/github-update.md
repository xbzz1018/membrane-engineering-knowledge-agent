# GitHub 更新方案

更新：2026-11-03。已核对账号 `xbzz1018` 的现有 `membrane-engineering-knowledge-agent` 为私有仓库，默认 main 对应原始快照 `cf013d7ebf84c7141068bbe8ad32dac8b3e7395d`。本地落地版是独立副本，不直接覆盖原项目。

本次先交付部署包、说明和本地可审阅更新；没有授权变更仓库可见性或个人主页。建议在现有私有项目建立功能分支、审阅变更并运行 CI，通过后合入。准备公开作品时，应另做数据/来源/许可证清理，避免个人主页链接指向面试官不可访问的私有仓库。

本轮已在独立目录准备 `feat/resume-review-deployment` 本地分支，保留原 main，尚未推送远端。交付 ZIP 来自该分支源码，不包含 `.git`、本机 `.env` 和业务运行状态；密码需重新初始化。后端本机回归 144 通过 / 2 跳过，前端构建/检查/2 项测试通过，Compose 配置可解析；GitHub CI 与镜像构建未运行。

## 更新内容

- README 首屏：业务闭环、子 Agent 工具边界、部署入口与验证边界。
- 源码、迁移、测试、前端、合成评测集和数据来源元信息。
- `deploy/` 镜像、Compose、启动门禁，部署验收与配置生成脚本。
- GitHub Actions：本地单元测试/前端检查，手动触发完整 Compose smoke；不发布镜像、不自动上线、不读取个人模型密钥。

保留远端已有文件，不把快照缺失的 `.github/dependabot.yml` 或规划文件当成删除。排除 `.env`、上传资料、运行数据库、模型输出、缓存、依赖 Junction 与原始日志。历史结果在本机保留；公共审阅材料只描述数据分母、模式、日期和限制，不能把未跑的 CI 写成成功。

## 通过分支更新

已有独立 Git checkout 后，从其根目录检查：

```bash
git status --short
git diff --check
git diff --stat
git switch -c feat/resume-review-deployment
git add README.md docs deploy scripts src test alembic frontend requirements-runtime.txt .dockerignore .gitignore .github
git diff --cached --stat
```

提交前逐项确认 staged 文件，尤其是新数据文件；不要对含运行目录的副本盲目 `git add -f`。审阅后再 commit/push 功能分支并创建 PR，保持 main 和仓库可见性可控。生成的 `deploy/.env` 应被 `git check-ignore deploy/.env` 命中。

## 个人主页后续

如果公开一个经清理、能部署的演示仓库，可以在个人 README 增加：

> 工程资料智能审查：LangChain Supervisor 调用三个领域 Agent 工具，PostgreSQL 条件过滤与 pgvector 召回、RRF 与可选重排，Temporal 负责异步解析与审查；保留证据定位和人工复核。附 Docker Compose 部署、合成开发集评测及失败记录。

真实 Embedding、MinerU 或完整部署验收通过后，再补对应结果链接。不要写“企业已上线”“60 条内部样本达 90%”等缺少原始记录的结论，也不要把此次独立复现代码追认为历史实习团队贡献。
