# Qwen3-0.6B双Adapter本地实验

2026年11月个人复现，使用RTX 3060 Laptop 6GB与WSL2；公司实习使用Qwen3.5-4B，此目录不代表公司原始训练或业务效果。与平台的关系见[模型适配说明](../../docs/model-adaptation.md)。

| 项目 | query_rewriter | grounded_qa |
| --- | --- | --- |
| 任务 | REWRITE多轮改写，query JSON | CMRC2018单段问答，answer/source_id JSON |
| train / validation / test | 600 / 100 / 100 | 同左 |
| 总序列长度 | 256 | 512 |
| rank / alpha / 目标模块 | 8 / 16 / q_proj、v_proj | 同左 |
| micro batch / 梯度累积 | 1 / 8 | 同左 |
| 学习率 | 2e-4 | 1e-4 |
| 正式首轮 | BF16，1 epoch，75更新步 | 同左 |

两任务分别从原始底座训练。SFT只计算Assistant答案和EOS损失，Prompt labels=-100；按累积窗口的目标Token数归一化。数据按会话/完整资料分组划分，避免组跨集合；保存后检查LoRA张量更新并重载对比logits。本轮仅归档，没有重新训练或运行GPU推理。

原记录环境：torch 2.14.0+cu132、transformers 5.20.2、peft 0.21.2、accelerate 1.15.0。训练与推理使用独立环境，平台后端不安装这些GPU依赖；迁移硬件或软件后需重新验证。

## 源码与复跑前提

- lab_common.py：模板、非思考前缀、Completion-only编码与固定底座版本。
- prepare_data.py：原始数据manifest校验、分组划分、超长过滤。
- train_lora.py / train_lora_tb.py：显式PyTorch/PEFT训练，后者记录TensorBoard。
- evaluate.py：同一留出集、生成配置下对比底座与Adapter。
- serve_adapters.sh：共享0.6B底座注册两套本地任务权重。
- monitor_run.py：整卡/WSL资源采样，与PyTorch显存分开。

权重及数据不入Git。复跑需自行准备获准的REWRITE、CMRC2018和data/raw/manifest.json（每项含relative_path、sha256）；文件为data/raw/rewrite/corpus.txt及data/raw/cmrc2018/{cmrc2018_train,cmrc2018_dev}.json。脚本拒绝覆盖实验；可用--root、--model指定原运行目录与底座。

```bash
python prepare_data.py --root /path/to/lab --model /path/to/Qwen3-0.6B
python train_lora_tb.py --root /path/to/lab --model /path/to/Qwen3-0.6B --task query_rewriter --run formal
python train_lora_tb.py --root /path/to/lab --model /path/to/Qwen3-0.6B --task grounded_qa --run formal
python evaluate.py --root /path/to/lab --model /path/to/Qwen3-0.6B --task query_rewriter
python evaluate.py --root /path/to/lab --model /path/to/Qwen3-0.6B --task grounded_qa
```

serve_adapters.sh使用同目录的adapters/formal、.venv-serve；外部--root训练应在对应实验目录部署。本地JSON协议不同于平台纯文本任务协议，不可直接替换；固定0.6B加载器也不证明Qwen3.5架构兼容。

## 已有评估

[归档清单](evidence/2026-11-10/manifest.json)包含六份原始配置/摘要的SHA-256，仓库检查核对字节。来源WSL路径仅用于追溯。

| 每组100条留出样本 | 底座 | 对应Adapter |
| --- | --- | --- |
| 改写schema合法率 | 96% | 100% |
| 改写EM / 本地字符F1 | 5% / 0.652 | 37% / 0.879 |
| 问答schema合法率 | 93% | 99% |
| 问答原文摘录比例 | 74% | 93% |
| 问答答案EM | 44% | 43% |

EM/F1为本地归一化字符指标，不是CMRC官方评分；固定D1引用不证明多文档证据选择。保留问答EM未提高这一结果，不能将格式改善说成审查可靠性提高。完整预测和实际权重仍在用户本机。
