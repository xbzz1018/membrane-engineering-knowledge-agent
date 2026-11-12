#!/usr/bin/env bash
set -euo pipefail
LAB_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
LAB_MODEL_PATH="${LAB_MODEL_PATH:-$HOME/.cache/huggingface/hub/models--Qwen--Qwen3-0.6B/snapshots/c1899de289a04d12100db370d81485cdf75e47ca}"
export VLLM_USE_FLASHINFER_SAMPLER="${VLLM_USE_FLASHINFER_SAMPLER:-0}"
for task in query_rewriter grounded_qa; do
  test -f "$LAB_ROOT/adapters/formal/$task/adapter_model.safetensors"
done
exec "$LAB_ROOT/.venv-serve/bin/vllm" serve "$LAB_MODEL_PATH" \
  --served-model-name qwen06b --host 127.0.0.1 --port 8000 \
  --dtype bfloat16 --max-model-len 1024 --max-num-seqs 1 \
  --max-num-batched-tokens 1024 --gpu-memory-utilization 0.65 --enforce-eager \
  --enable-lora --max-lora-rank 8 --max-loras 2 --max-cpu-loras 2 \
  --lora-modules "query_rewriter=$LAB_ROOT/adapters/formal/query_rewriter" \
                 "grounded_qa=$LAB_ROOT/adapters/formal/grounded_qa"
