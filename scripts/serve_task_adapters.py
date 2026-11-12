"""Validate two local PEFT adapters and print a vLLM command; execution is opt-in."""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from pathlib import Path


def base_identity(value: str) -> str:
    path = Path(value)
    return str(path.resolve()) if path.exists() else value.rstrip("/")


def adapter_rank(path: Path, base: str) -> int:
    config = json.loads((path / "adapter_config.json").read_text(encoding="utf-8"))
    if config.get("peft_type") != "LORA" or config.get("task_type") != "CAUSAL_LM":
        raise ValueError("Expected a causal language model LoRA adapter")
    if base_identity(str(config.get("base_model_name_or_path", ""))) != base_identity(base):
        raise ValueError("Both adapters must match the specified base model")
    if not (path / "adapter_model.safetensors").is_file():
        raise ValueError("Missing safetensors adapter weights")
    rank = config.get("r")
    if not isinstance(rank, int) or isinstance(rank, bool) or rank < 1:
        raise ValueError("Invalid LoRA rank")
    return max([rank, *config.get("rank_pattern", {}).values()])


def build_command(args) -> list[str]:
    if args.query_name == args.review_name or any(
        not name or not all(char.isalnum() or char in "_-" for char in name)
        for name in (args.query_name, args.review_name, args.base_name)
    ):
        raise ValueError("Use distinct adapter aliases and simple model names")
    rank = max(adapter_rank(args.query_adapter, args.base), adapter_rank(args.review_adapter, args.base))
    supported_ranks = [8, 16, 32, 64, 128, 256, 512]
    max_rank = next((value for value in supported_ranks if value >= rank), None)
    if max_rank is None:
        raise ValueError("Adapter rank exceeds this launch profile")
    return [sys.executable, "-m", "vllm.entrypoints.openai.api_server", "--model", args.base,
            "--served-model-name", args.base_name, "--host", "127.0.0.1", "--port", str(args.port),
            "--dtype", "bfloat16", "--max-model-len", str(args.max_model_len),
            "--max-num-seqs", str(args.max_num_seqs), "--gpu-memory-utilization", str(args.gpu_memory_utilization),
            "--enable-lora", "--max-loras", "2", "--max-lora-rank", str(max_rank),
            "--lora-modules", f"{args.query_name}={args.query_adapter.resolve()}",
            f"{args.review_name}={args.review_adapter.resolve()}"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, help="Exact base_model_name_or_path used by both adapters")
    parser.add_argument("--base-name", default="membrane-base")
    parser.add_argument("--query-adapter", type=Path, required=True)
    parser.add_argument("--review-adapter", type=Path, required=True)
    parser.add_argument("--query-name", default="user")
    parser.add_argument("--review-name", default="shencha")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--max-model-len", type=int, default=4096)
    parser.add_argument("--max-num-seqs", type=int, default=2)
    parser.add_argument("--gpu-memory-utilization", type=float, default=0.8)
    parser.add_argument("--execute", action="store_true", help="Actually start the GPU server instead of printing")
    args = parser.parse_args()
    if (not 1 <= args.port <= 65535 or args.max_model_len < 1 or args.max_num_seqs < 1
            or not 0 < args.gpu_memory_utilization < 1):
        parser.error("Invalid port, context, concurrency or memory setting")
    command = build_command(args)
    if args.execute:
        return subprocess.run(command, check=False).returncode
    print(shlex.join(command))
    print("Preflight only: model architecture, vLLM compatibility and GPU capacity require an actual deployment.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
