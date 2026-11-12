# 项目初步方案生成与交付

更新日期：2026-11-03。独立工程复现增量，不追认为3月至6月实习交付。

## 已实现的范围

在知识问答页明确提出生成请求，可以受理一份膜结构停车棚初步方案。Supervisor继续动态路由普通问答；只有生成意图进入新方案业务流程。

```text
生成需求 → 检索与材料查询子Agent工具并发 → 冻结原始来源
        → 结构化方案 → ReviewAgent适配审查与规则门禁
        → 待完善 / 待人工批准 → 同版本批准 → Markdown与Word
```

复用现有项目、权限、KnowledgeAgent底层查询、两个查询角色工具、ReviewAgent和Temporal队列。没有重新实现三个完整Agent，没有新增消息队列。

Local关闭Temporal时同步执行，响应明确为`local_inline`；打开Temporal时返回受理状态，由`ProjectGenerationWorkflow`与`ProjectExportWorkflow`执行长任务。API失败没有Fake兜底。此次实际验收使用明确的Fake模式，不证明真实模型写作质量。

## 页面操作

1. 在项目选择器中选择有权限的项目，上传并索引可公开使用的历史参考和材料依据。
2. 知识问答输入：`生成800平方米PVDF-Z901停车棚初步方案，地点：合成测试场地`。材料型号必须与当前项目的实际来源一致，示例值仅用于合成演示。
3. 点击回答下方“查看方案与复核”，或页面右上角“项目方案”。抽屉读取权威状态，执行中每5秒刷新。
4. 缺少面积、地点、用途、材料偏好或有效历史/材料引用时进入待完善。点击“修改形成新版本”补充需求及正文，填写修订原因后保存并重新审查。
5. 审核人核对需求、建议与原始依据，填写说明后批准当前版本或退回。`decision_pending`表示决定已落库、尚未被Workflow执行，不可导出。
6. 当前批准版本点击“生成Markdown和Word”，完成后通过鉴权下载。关闭页面不终止已受理的Temporal任务。

已有资料包审查页面继续工作；聊天中要求审查已有资料包仍提示从原页面选定文件提交，未新增对话附件选择。

## 版本与证据

五张新增表由迁移`0017_project_plans`创建：`project_plans`、`project_plan_versions`、`project_plan_reviews`、`project_plan_decisions`、`project_plan_artifacts`。

- `plan_id`独立于已有`project_id`。需求、正文和来源变化使用不可变内容版本；`lock_version`防止并发覆盖。
- 原始来源从业务库重新读取，不采信Agent摘要。快照含Evidence ID、原文摘录、定位、文档/文本SHA、来源版本和业务元数据指纹；单条摘录最多2000字符，每角色最多6条。
- 结构化需求保留用户声明；四个正文段落标识为建议；事实使用逐字引用独立存放。生成正文限制精确数值/型号进入声明需求或原始引文，避免自由文本绕过核验。
- `ProjectReviewAdapter`将待审方案放入`draft_target`，与原始Evidence分开。复用既有ReviewAgent执行与引用门禁，不把草稿当成证明自身的Evidence。
- 确定性门禁覆盖必需需求、四类章节、角色引用范围、逐字引文、指定材料匹配、已声明版次/有效期及审查来源覆盖。自动通过不代表完整工程合规或语义蕴含已被证明。
- 审查、人工决定和导出绑定`plan_id + version + content_hash + manifest_hash`。新版本不沿用旧批准；首版只允许当前批准版本正式下载。
- 模型写作只在批准前。导出服务不调用模型，MD与DOCX共用同一内容块，批准后不能补写新正文。
- 来源撤回、重新解析、分级或业务声明变化时，后续调用/批准/导出/下载重新校验，明确阻断，不能偷偷替换快照。

Word使用仓库内固定样式，非企业提供模板。当前`preliminary-v1 / docx-v2`包含标题、需求表、四个建议章节、原始引文、批准与哈希记录、页眉页脚和页码。

## 恢复和幂等

创建、修订和人工决定分别有请求/命令ID。API先持久化业务对象，再用稳定Workflow ID提交；若启动失败，列表仍保留受理对象，可以调用同版本generate恢复提交。没有新增独立对账守护进程。

Temporal输入仅包含方案或产物ID、版本和队列。模型、查询、数据库和文档I/O在Activity中。Activity通过执行身份和递增attempt认领；提交前校验，迟到结果拒写。

人工决定先落库，由Workflow定时消费，不接受Signal作为批准依据。导出身份包含方案、版本、格式、模板及渲染器版本；对象写入后才事务发布。重试复用已发布产物及SHA。改版期间的旧导出不能成为正式文件。

对象写入成功但尚未发布时崩溃，可能留下未发布候选对象；首版不自动清理孤立对象，也不承诺模型调用Exactly Once。强制terminate或七天Workflow执行超时的业务对账仍需人工操作。

## 验证记录

| 验证 | 结果及边界 |
|---|---|
| 完整后端回归 | 192 passed / 2 skipped，153.84秒；后续仅补版式与渲染器版本保护，再做定向回归 |
| 最终定向回归 | 61 passed，96.49秒；包含新增方案、问答、原审查接口、审批和生命周期；不与全量相加 |
| 前端 | 类型、Lint、2项Vitest与构建通过；保留Element Plus包体积提示 |
| 浏览器 | 聊天生成、来源、同版批准、Word下载、修订v2重新审批、旧文件409、取消对话框不提交、移动端无横溢出 |
| 新Temporal故障验收 | 实际强杀/重启生成Worker；离线批准恢复；对象写后强杀，重试只发布一个文件；2份本次真实历史重放通过。SQLite/Fake/合成资料 |
| 迁移0017 | 隔离SQLite旧表基线上升/降/再升通过；不是PostgreSQL验收。历史0013依赖pgvector，SQLite从零运行全链失败记录保留 |
| Word版式 | 本机Microsoft Word 16.0实际导出PDF与PNG，2页逐页查看；修复标题蓝线及末页孤立记录。未验证长表/极限长度 |

主要摘要在`docs/validation-artifacts/project-plan-*`。完整原始记录保留于`data/runtime/project-plan-temporal`与`project-plan-browser`，包含失败，不能把规则与合成验收当作模型准确率。

第一次故障验收因材料台账同类命中掩盖指定型号而缺少依据，方案正确阻断，但未达预期；修复后增加指定型号上传资料回归。另一次测试Worker启动超时，已保留；随后放宽测试启动等待，两轮真实故障验收通过。最终源码指纹见验收摘要，运行中未变化。

文档技能自带`render_docx.py`因本机缺`pdf2image`无法运行。实际使用本机隐藏Word进程导出并以PyMuPDF生成页面PNG验收，没有把XML解压检查当作版式检查。

## 接口与复跑

Swagger `/docs`提供“项目方案与文档”分组。OpenAPI已同步，项目业务身份继续来自JWT和服务端项目授权。

```powershell
$python = 'F:\code\homework\conda-envs\agent-membrane\python.exe'
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
& $python -m pytest -q -p pytest_asyncio.plugin test/test_project_plans.py
& $python scripts/validate_project_plan_temporal.py
& $python scripts/validate_project_plan_migration.py
# 浏览器脚本可通过PLAN_ACCEPTANCE_API指向专用验收服务，默认18080；不混用旧同步验收脚本。
Push-Location frontend
node scripts/browser_project_plans.mjs
Pop-Location
```

Full部署须先`alembic upgrade head`再更新API与Worker。同一个版本的Worker需同时加载两个新Workflow和五个Activity。新流程没有改变旧资料包Workflow的命令序列；本次重放只覆盖本次新历史，未证明任意旧生产历史兼容。

## 首版限制

当前只交付一份初步方案的MD与Word，不含五份文件、PDF导出按钮、复杂图表、结构计算或正式报价。需求抽取只识别用户明示的面积、材料和“地点：”字段；多轮修改通过方案抽屉，尚未实现自然语言定向修改章节。

来源集合变更目前需新建方案重新取证，修订只复用同一冻结来源。材料数值保留为原文引用，没有声称完整BOM或通用参数蕴含校验。角色查询仍只允许public；本地Provider支持非公开资料尚未扩展。

当前方案流程未接入旧资料包预算预留/结算，也未做真实API模型、MinIO和PostgreSQL整栈验收。已有简历检索指标需要独立原始数据与实测，不由这次功能测试证明。
