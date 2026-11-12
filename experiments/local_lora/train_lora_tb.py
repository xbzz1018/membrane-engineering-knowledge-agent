"""LoRA SFT with TensorBoard metrics, configuration and training sample display."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import re
import time
from importlib.metadata import version
from pathlib import Path

import torch
from lab_common import (
    DEFAULT_MODEL,
    MODEL_REVISION,
    TASK_LIMITS,
    TASK_LR,
    encode_sample,
    get_tokenizer,
    load_base,
    read_jsonl,
    seed_all,
    write_json,
)
from peft import LoraConfig, PeftModel, TaskType, get_peft_model
from torch.utils.tensorboard import SummaryWriter
from transformers import get_cosine_schedule_with_warmup


def as_batch(sample, device):
    ids = torch.tensor([sample["input_ids"]], dtype=torch.long, device=device)
    return {"input_ids": ids, "attention_mask": torch.ones_like(ids),
            "labels": torch.tensor([sample["labels"]], dtype=torch.long, device=device)}


@torch.inference_mode()
def validation_loss(model, samples):
    model.eval()
    total, tokens = 0.0, 0
    for sample in samples:
        output = model(**as_batch(sample, "cuda"), use_cache=False)
        total += output.loss.item() * sample["completion_tokens"]
        tokens += sample["completion_tokens"]
    return total / tokens


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--task", choices=TASK_LIMITS, required=True)
    parser.add_argument("--run", choices=["smoke", "formal"], required=True)
    parser.add_argument("--name", help="Optional new experiment directory, e.g. lr1e4; never overwrite existing results.")
    parser.add_argument("--steps", type=int)
    parser.add_argument("--lr", type=float)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    if args.name and not re.fullmatch(r"[A-Za-z0-9_-]+", args.name):
        parser.error("Experiment name must contain only letters, digits, underscores or hyphens")
    if args.steps is not None and args.steps <= 0:
        parser.error("--steps must be positive")
    assert torch.cuda.is_available(), "CUDA unavailable"
    torch.set_num_threads(4)
    seed_all(args.seed)
    dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
    data_root = args.root / "data/processed" / args.task
    experiment = args.name or args.run
    run_root = args.root / "results" / experiment / args.task
    adapter_path = args.root / "adapters" / experiment / args.task
    tensorboard_path = args.root / "runs" / experiment / args.task
    if tensorboard_path.exists():
        raise FileExistsError("TensorBoard log directory exists; use a new --name")
    if run_root.exists() or adapter_path.exists():
        raise FileExistsError("Use a new run path; refusing to overwrite an experiment")
    run_root.mkdir(parents=True)
    tokenizer = get_tokenizer(args.model)
    data_path = data_root / ("smoke.jsonl" if args.run == "smoke" else "train.jsonl")
    rows = read_jsonl(data_path)
    val_rows = read_jsonl(data_root / "validation.jsonl")[:20 if args.run == "smoke" else 100]
    train = [encode_sample(tokenizer, row) for row in rows]
    validation = [encode_sample(tokenizer, row) for row in val_rows]
    for sample in train + validation:
        assert len(sample["input_ids"]) <= TASK_LIMITS[args.task]
        assert all(label == -100 for label in sample["labels"][:sample["prompt_tokens"]])
        assert sample["labels"][sample["prompt_tokens"]:] == sample["input_ids"][sample["prompt_tokens"]:]
    accumulation = 8
    steps = args.steps or (20 if args.run == "smoke" else math.ceil(len(train) / accumulation))
    lr = args.lr or TASK_LR[args.task]
    config = {"task": args.task, "run": args.run, "experiment": experiment, "model": args.model,
              "model_revision": MODEL_REVISION, "seed": args.seed, "dtype": str(dtype),
              "train_rows": len(train), "validation_rows": len(validation), "optimizer_steps": steps,
              "max_sequence_length": TASK_LIMITS[args.task], "micro_batch_size": 1,
              "gradient_accumulation": accumulation, "learning_rate": lr,
              "warmup_steps": max(1, math.ceil(steps * .05)), "scheduler": "cosine",
              "weight_decay": .01, "max_grad_norm": 1.0, "lora_r": 8, "lora_alpha": 16,
              "lora_dropout": .05, "target_modules": ["q_proj", "v_proj"],
              "completion_only": True, "loss_normalization": "supervised tokens per accumulation window",
              "gradient_checkpointing": True, "packing": False, "attn_implementation": "sdpa",
              "data_sha256": hashlib.sha256(data_path.read_bytes()).hexdigest(),
              "versions": {p: version(p) for p in ["torch", "transformers", "peft", "accelerate"]}}
    write_json(run_root / "config.json", config)
    model = load_base(args.model, dtype)
    model.config.use_cache = False
    model = get_peft_model(model, LoraConfig(task_type=TaskType.CAUSAL_LM, r=8, lora_alpha=16,
                                            lora_dropout=.05, target_modules=["q_proj", "v_proj"], bias="none"))
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    model.to("cuda")
    trainable = [parameter for parameter in model.parameters() if parameter.requires_grad]
    trainable_names = [name for name, parameter in model.named_parameters() if parameter.requires_grad]
    assert trainable_names and all("lora_" in name for name in trainable_names)
    config["trainable_parameters"] = sum(parameter.numel() for parameter in trainable)
    config["all_parameters"] = sum(parameter.numel() for parameter in model.parameters())
    print(json.dumps({"start": config}, ensure_ascii=False), flush=True)
    config["tensorboard_log_dir"] = str(tensorboard_path)
    write_json(run_root / "config.json", config)
    with SummaryWriter(log_dir=str(tensorboard_path), flush_secs=5) as writer:
        print(f"TensorBoard log directory: {tensorboard_path}", flush=True)
        writer.add_text("experiment/config", "```json\n" + json.dumps(config, ensure_ascii=False, indent=2) + "\n```", 0)
        for index, row in enumerate(rows[:3], start=1):
            sample = {"input": row["prompt"], "reference": row["completion"][0]["content"]}
            writer.add_text(f"samples/training_{index}", "```json\n" + json.dumps(sample, ensure_ascii=False, indent=2) + "\n```", 0)
        optimizer = torch.optim.AdamW(trainable, lr=lr, weight_decay=.01)
        scheduler = get_cosine_schedule_with_warmup(optimizer, config["warmup_steps"], steps)
        scaler = torch.amp.GradScaler("cuda", enabled=dtype == torch.float16)
        before = validation_loss(model, validation)
        writer.add_scalar("validation/loss", before, 0)
        writer.flush()
        initial_weights = [parameter.detach().clone() for parameter in trainable]
        torch.cuda.reset_peak_memory_stats()
        started, order, cursor = time.perf_counter(), [], 0
        rng = random.Random(args.seed)
        metrics_path = run_root / "train_metrics.jsonl"
        final_loss = None
        for step in range(steps):
            if cursor >= len(order):
                order = list(range(len(train)))
                rng.shuffle(order)
                cursor = 0
            # Formal training covers each example once; smoke deliberately repeats its small set.
            indices = order[cursor:cursor + accumulation]
            cursor += len(indices)
            window = [train[index] for index in indices]
            supervised = sum(sample["completion_tokens"] for sample in window)
            model.train()
            optimizer.zero_grad(set_to_none=True)
            weighted_loss = 0.0
            for sample in window:
                with torch.autocast("cuda", dtype=dtype):
                    output = model(**as_batch(sample, "cuda"), use_cache=False)
                    loss = output.loss * (sample["completion_tokens"] / supervised)
                if not torch.isfinite(loss):
                    raise FloatingPointError(f"Non-finite loss at step {step + 1}")
                weighted_loss += float(loss.detach())
                scaler.scale(loss).backward()
                del output, loss
            scaler.unscale_(optimizer)
            norm = torch.nn.utils.clip_grad_norm_(trainable, 1.0, error_if_nonfinite=True)
            scaler.step(optimizer)
            scaler.update()
            scheduler.step()
            final_loss = weighted_loss
            record = {"step": step + 1, "loss": weighted_loss, "gradient_norm": float(norm),
                      "lr": scheduler.get_last_lr()[0], "supervised_tokens": supervised,
                      "elapsed_seconds": time.perf_counter() - started,
                      "peak_allocated_mib": torch.cuda.max_memory_allocated() / 2**20,
                      "peak_reserved_mib": torch.cuda.max_memory_reserved() / 2**20}
            writer.add_scalar("train/loss", record["loss"], record["step"])
            writer.add_scalar("train/next_learning_rate", record["lr"], record["step"])
            writer.add_scalar("train/gradient_norm_before_clip", record["gradient_norm"], record["step"])
            writer.add_scalar("train/supervised_tokens", record["supervised_tokens"], record["step"])
            writer.add_scalar("memory/peak_allocated_mib", record["peak_allocated_mib"], record["step"])
            writer.add_scalar("memory/peak_reserved_mib", record["peak_reserved_mib"], record["step"])
            with metrics_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record) + "\n")
            if step == 0 or (step + 1) % 5 == 0 or step + 1 == steps:
                print(json.dumps(record), flush=True)
        changed = sum(not torch.equal(parameter.detach(), initial) for parameter, initial in zip(trainable, initial_weights))
        assert changed > 0, "LoRA weights did not update"
        after = validation_loss(model, validation)
        writer.add_scalar("validation/loss", after, steps)
        writer.flush()
        model.eval()
        probe = as_batch(train[0], "cuda")
        probe.pop("labels")
        with torch.inference_mode():
            expected_logits = model(**probe, use_cache=False).logits[:, -1, :].float().cpu()
        model.save_pretrained(adapter_path, safe_serialization=True)
        # Reload into the same now-unloaded base, avoiding a second copy of base weights.
        base = model.unload()
        reloaded = PeftModel.from_pretrained(base, adapter_path, is_trainable=False).eval()
        with torch.inference_mode():
            actual_logits = reloaded(**probe, use_cache=False).logits[:, -1, :].float().cpu()
        reload_delta = float((actual_logits - expected_logits).abs().max())
        assert torch.allclose(actual_logits, expected_logits, atol=.04, rtol=.01), reload_delta
        config_path = adapter_path / "adapter_config.json"
        adapter_config = json.loads(config_path.read_text())
        assert adapter_config["r"] == 8 and set(adapter_config["target_modules"]) == {"q_proj", "v_proj"}
        result = {"task": args.task, "run": args.run, "steps": steps, "validation_loss_before": before,
                  "validation_loss_after": after, "last_training_loss": final_loss,
                  "elapsed_seconds": time.perf_counter() - started,
                  "peak_allocated_mib": torch.cuda.max_memory_allocated() / 2**20,
                  "peak_reserved_mib": torch.cuda.max_memory_reserved() / 2**20,
                  "changed_lora_tensors": changed, "trainable_parameters": config["trainable_parameters"],
                  "reload_max_logit_delta": reload_delta, "adapter": str(adapter_path)}
        write_json(run_root / "summary.json", result)
        print(json.dumps({"complete": result}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
