# 评测协议与可复查结果

更新：2026-11-03。所有结果以本目录生成的逐样本文件为准；原仓库的历史报告保留为来源记录，不能当成当前验证。

本轮已运行成绩、错误案例和工程验证见 [current-validation.md](current-validation.md)。旧版真实模型第二轮21/24通过宽松约定检查、2误报和1执行失败；保留作历史。当前使用business_review_v3协议，最新结果见验证记录，不报告为生产准确率。

## 数据集分层

| 数据 | 性质 | 可回答的问题 | 不能推导的结论 |
|---|---|---|---|
| `business_review_v1.jsonl` | 人工编写的24条合成开发回归，12条需要复核、12条正常 | 当前规则/工具链是否识别约定业务边界；真实模型会不会误报 | 独立测试集泛化准确率、公司真实业务表现 |
| `frozen_difficult_retrieval_v3.jsonl` | 原仓库30份合成文本、60条有答案查询 | 在同一固定语料上比较检索排序 | 简历中的60条内部回归、无答案拒答质量 |
| retrieval_business_v1.json | 119份公开合成文本、30条开发查询，含23有答案/7无答案、多相关及过滤陷阱 | 真实条件过滤和不同检索策略的分层开发表现 | 专家标注测试、内部样本或生产泛化 |
| 公开厂商7页 PDF | 本轮从公开地址下载，SHA与原来源快照一致 | 文本、页码和特定表格数值是否保留 | 任意扫描PDF的OCR质量、MinerU验收、所有厂商表格准确率 |
| 原 `frozen_package_review_v3` | 20条高度重复、全部为冲突正例 | 仅历史结构回归 | 误报率、可靠precision/F1 |

`business_review_v1`用于本轮开发，已经根据其失败调过规则和Prompt，故明确标记 `not_a_held_out_test=true`。冻结SHA只证明内容没变，不证明独立、无泄漏或标签正确。当前gold由开发者编写，未经过业务专家双人标注。

## 业务回归

```powershell
$python = 'F:\code\homework\conda-envs\agent-membrane\python.exe'
& $python scripts\run_business_eval.py
# 配好获准的公开资料模型环境变量后：
& $python scripts\run_business_eval.py --mode api
```

每次生成独立目录 `data/eval/results/business_review_v3/{run_id}/`，包含隔离SQLite、上传副本、`predictions.jsonl`和`summary.json`。每条记录保存预期、预测、问题类型、证据、完整公开/合成报告、耗时和错误；使用新项目，禁止污染默认业务项目。默认Fake不发模型请求；API失败保留错误，不降级。

除二分类“是否需要人工复核”外，逐条检查预期问题类型与支持该问题的资料ID；避免模型只说“有问题”就算正确。schema/引用有效性是工程约束，引用语义支持另行评估。

旧v1采用包含关系；v2冻结business_expectations_v2.json及SHA，v3另冻结新角色/价格可选策略标签，一对一匹配阻断问题的类型与证据文档集合，缺领域问题同时匹配领域。额外阻断发现、重复发现计FP，缺少预期问题计FN；schema检查也进入correct。非阻断说明与所有自由文本尚未逐claim标注，不能将严格通过率称为全文事实准确率。失败继续计入所有提交样本的通过率分母。

报告TP/FP/FN/TN、precision、recall、specificity、F1及完整案例正确率。分母为零返回null。失败单列，完成样本的二分类分数明确命名 `completed_only`；完整案例正确率以全部提交样本为分母，失败记错。分层记录样本数，不能用总分掩盖某领域失败。

## 检索对照

新增scripts/run_business_retrieval_eval.py默认--mode local-contract，固定SHA的数据不会被生成器覆盖。该模式独立SQLite，仅测substring词项/条件；--mode full-api要求真实Full/API/Embedding/Reranker，四策略为lexical、pure_vector、hybrid、hybrid_rerank，不能静默降级。

候选预算固定30，文档去重Top10。23条有答案用于macro Recall/MRR，失败计0；7条无答案另报空结果比例，不能当问答拒答准确率。另由独立声明式oracle检查硬过滤越界，gold不从系统预测生成。无query的精确条件查询跳过向量，所有策略使用相同条件结果，不计作语义能力。

实际Local运行20261102T113700Z-c8096dbb：30完成/0错误/0越界，Recall@10及MRR@10均0.869565，语义改写3/3漏召回，7/7无答案为空。三组重复型号家族和80份模板干扰资料仍使测试简单，数据用于开发。不得通过删语义改写或调标签把成绩凑到90%；Embedding403，Full质量尚无成绩。[逐条结果](validation-artifacts/README.md)。

`run_retrieval_comparison.py`只接受Full/API与真实Reranker；为每次评测建新项目，使用固定30候选预算，保存逐查询各策略的完整文档排序。先按文档ID去重再取Top10，macro Recall@10为命中相关文档数/该查询全部相关文档数，MRR@10为Top10内第一个相关文档排名倒数的查询平均，超过10记0。支持多个相关文档标签，不把Hit@10冒充多相关Recall。

`run_offline_retrieval_eval.py`是基础设施不可用时的另一个明确实验：真实Embedding + 内存精确cosine + 原词项/RRF + 真Reranker。它不证明pgvector/HNSW部署效果。当前Embedding端点返回403，脚本留下失败记录，没有生成向量检索质量数字。

`run_reranker_eval.py`另做词项与真实神经网络Reranker对照，不依赖Embedding。本轮60条合成查询均完成，词项Recall@10=0.8333、MRR@10=0.5637，重排均为1.0。每条查询的30候选实际等于整个小语料，设置对重排非常有利；它只证明这份固定语料中的排序效果，不是向量/RRF评测，也没有无答案测试。摘要、分层和逐条排序均保存，不借用历史“内部样本”名称。

不强制“混合必须比向量好X%”后才保存结果。提升既报绝对值，也在基线非0时计算相对值 `(new-old)/old`。不得重新挑样本以凑到简历数字。

## 延迟、成本与裁判

p95统一为nearest-rank：排序后取 `ceil(0.95*n)-1`，同时报告n、min、max和小样本标识。3次观测的p95就是最大值，不能宣称稳定的生产尾延迟。业务回归延迟包含上传、索引与审查；不与仅模型推理耗时混比。Token来自真实响应，Fake的调用数/Token不能伪造；成本只是配置费率估算，不能当供应商账单。

原“真实资料包评测”实际使用模板合成TXT。该旧入口现在转到真实模型+明确标记的合成业务集，不再输出不可信的Groundedness=1.0。新的 `src/evaluation/groundedness.py`要求逐claim返回唯一ID、严格布尔supported和reason，分母由程序固定，缺失/重复/越界ID直接失败，空claim返回null。它目前仅通过契约测试，尚未运行独立裁判或专家蕴含判断，不能报Groundedness分数。

## 如何建立可信的后续测试集

1. 先写标注指南：审查对象、适用版本、型号归一、单位、容差、价格口径、证据跨度；区分“确定冲突”“需补证”“正常”“超出范围”。
2. 用公开或获准脱敏材料，由业务人员独立标注。按真实项目/文档家族分开发与测试；冻结后不看测试错误调Prompt。保留双人分歧和仲裁结果。
3. 检索按精确型号、版次、日期、语义改写、多相关、无答案分层；审查按领域、正负、缺证、错版、多格式分层。每层报告数量。
4. 至少保留纯向量、词项、RRF、RRF+Reranker的相同预算对照；所有配置、模型名、语料hash、逐条排序及失败均归档。小样本用按项目聚类的bootstrap区间，未执行就不写区间。
5. 对关键问题做人工语义支持核验。引用ID存在、裁判认为支持、业务人员判定正确是三种不同指标。

## 新口径的限制

v2标签由开发者从既定24条情境逐项标注，没有使用模型预测自动生成gold；数据和标签仍用于开发，不能叫独立测试。该任务支持的厚度、版次、币种比较有规则门禁，24/24系统成绩包含规则贡献，不能推导LLM自身100%准确或多Agent优于单Agent。当前未完成规则/模型/单Agent消融，亦无真实项目分层置信区间。

保留所有运行：若manifest报告source_changed_during_run=true，该次作为探索记录；最后正式回归应在固定源码下重跑，不能删掉该记录或改成false。代码hash包括src与scripts中的全部Python文件，因此新增验收脚本也会触发变化标记。

## 2026-11-03 新角色协议

当前run_business_eval.py默认使用business_review_v3.jsonl与business_expectations_v3.json，24条开发案例，13正常/11需人工。仅因明确业务策略变化，将“无价格资料”改为普通设计/规格审查的正常包；新标签由脚本显式变更，未从预测生成，旧数据及SHA完全保留。Fake 24/24仅证明规则/工具/状态；不将新版成绩与旧真实模型运行混比。

检索脚本现支持--contextual off|on，使用相同119资料/30查询和条件。metadata-v1主要补章节/工作表/位置；TXT集合没有充分章节信号，当前开关前后macro Recall/MRR均0.869565，3条改写仍全部未召回。该结果不支持“增强已提升质量”。新公开2份PDF的页码/字面值烟测仅验解析与MD，不计入这30查询，更不能凑作60条内部样本。上下文的下一轮质量集合需包含真实标题、表格、指代与跨段检索，由独立标签先定义目标。
