"""Shared, explicit prompt and completion-only tokenization for the local lab."""
from __future__ import annotations

import hashlib
import json
import random
import re
import unicodedata
from pathlib import Path

MODEL_REVISION = "c1899de289a04d12100db370d81485cdf75e47ca"
DEFAULT_MODEL = str(Path.home() / ".cache/huggingface/hub/models--Qwen--Qwen3-0.6B/snapshots" / MODEL_REVISION)
TASK_LIMITS = {"query_rewriter": 256, "grounded_qa": 512}
TASK_LR = {"query_rewriter": 2e-4, "grounded_qa": 1e-4}


def normalize(text):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text)).casefold()


def stable_id(parts):
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode()).hexdigest()


def read_jsonl(path):
    with Path(path).open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def seed_all(seed):
    import numpy as np
    import torch
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def prompt_messages(task, **fields):
    if task == "query_rewriter":
        instruction = ('根据历史对话，把当前话语改写成可独立理解的完整话语，不添加对话中没有的信息。'
                       '只输出JSON：{"query":"改写结果"}。\n历史1：' + fields["context1"] +
                       '\n历史2：' + fields["context2"] + '\n当前话语：' + fields["question"])
    else:
        instruction = ('根据给定资料回答问题，答案必须摘自原文。只输出JSON：'
                       '{"answer":"答案","source_id":"D1"}。\n资料D1：' + fields["context"] +
                       '\n问题：' + fields["question"])
    return [{"role": "user", "content": instruction}]


def prompt_ids(tokenizer, messages):
    text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True,
                                         enable_thinking=False)
    return tokenizer(text, add_special_tokens=False)["input_ids"]


def encode_sample(tokenizer, row):
    prefix = prompt_ids(tokenizer, row["prompt"])
    target = row["completion"][0]["content"]
    completion = tokenizer(target + tokenizer.eos_token, add_special_tokens=False)["input_ids"]
    assert prefix and len(completion) > 1 and completion[-1] == tokenizer.eos_token_id
    return {"input_ids": prefix + completion, "labels": [-100] * len(prefix) + completion,
            "completion_tokens": len(completion), "prompt_tokens": len(prefix)}


def get_tokenizer(model):
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(model, local_files_only=True)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token_id = tokenizer.eos_token_id
    return tokenizer


def load_base(model, dtype):
    from transformers import AutoModelForCausalLM
    return AutoModelForCausalLM.from_pretrained(model, local_files_only=True,
                                               dtype=dtype, attn_implementation="sdpa")
