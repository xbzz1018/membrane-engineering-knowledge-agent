"""Deterministic, paired base/LoRA evaluation on held-out public questions."""
from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from pathlib import Path

import torch
from lab_common import (
    DEFAULT_MODEL,
    TASK_LIMITS,
    get_tokenizer,
    load_base,
    normalize,
    prompt_ids,
    read_jsonl,
    seed_all,
    write_json,
)
from peft import PeftModel


def score_text(prediction, references):
    # Local character metrics, not the official CMRC evaluation script.
    p = normalize(prediction)
    best_em, best_f1 = 0.0, 0.0
    for reference in references:
        r = normalize(reference)
        em = float(p == r)
        common = sum((Counter(p) & Counter(r)).values())
        f1 = 2 * common / (len(p) + len(r)) if len(p) + len(r) else 1.0
        best_em, best_f1 = max(best_em, em), max(best_f1, f1)
    return best_em, best_f1


def score_response(task, text, row):
    schema, value, citation = False, "", False
    try:
        parsed = json.loads(text)
        if task == "query_rewriter":
            schema = isinstance(parsed, dict) and set(parsed) == {"query"} and isinstance(parsed["query"], str)
            value = parsed["query"] if schema else ""
        else:
            schema = (isinstance(parsed, dict) and set(parsed) == {"answer", "source_id"} and
                      isinstance(parsed["answer"], str) and isinstance(parsed["source_id"], str))
            value = parsed["answer"] if schema else ""
            citation = schema and parsed["source_id"] == "D1"
    except (ValueError, TypeError):
        pass
    em, f1 = score_text(value, row["references"]) if schema else (0.0, 0.0)
    result = {"schema_valid": float(schema), "exact_match": em, "character_f1": f1}
    if task == "grounded_qa":
        result["source_id_correct"] = float(citation)
        result["answer_verbatim_in_context"] = float(schema and bool(value) and value in row["metadata"]["context"])
    return result


@torch.inference_mode()
def run_model(model, tokenizer, rows, output_path):
    model.eval()
    model.config.use_cache = True
    metrics, examples = Counter(), []
    started = time.perf_counter()
    for index, row in enumerate(rows):
        ids = torch.tensor([prompt_ids(tokenizer, row["prompt"])], device="cuda")
        generated = model.generate(input_ids=ids, attention_mask=torch.ones_like(ids),
                                   max_new_tokens=96, do_sample=False, use_cache=True,
                                   eos_token_id=tokenizer.eos_token_id, pad_token_id=tokenizer.pad_token_id)
        completion = generated[0, ids.shape[1]:].tolist()
        text = tokenizer.decode(completion, skip_special_tokens=True).strip()
        scores = score_response(row["task"], text, row)
        truncated = bool(completion and completion[-1] != tokenizer.eos_token_id and len(completion) >= 96)
        scores["hit_generation_limit"] = float(truncated)
        metrics.update(scores)
        example = {"id": row["id"], "prediction": text, "references": row["references"],
                   "expected_json": row["completion"][0]["content"], "scores": scores,
                   "generated_tokens": len(completion)}
        examples.append(example)
        with output_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(example, ensure_ascii=False) + "\n")
        if (index + 1) % 20 == 0:
            print(json.dumps({"evaluation": output_path.stem, "processed": index + 1, "seconds": time.perf_counter() - started}), flush=True)
    return {"examples": len(rows), "metrics": {name: value / len(rows) for name, value in metrics.items()},
            "elapsed_seconds": time.perf_counter() - started}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--task", choices=TASK_LIMITS, required=True)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--experiment", default="formal")
    args = parser.parse_args()
    seed_all(42)
    torch.set_num_threads(4)
    dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
    if not args.experiment or Path(args.experiment).name != args.experiment:
        parser.error("--experiment must be a single directory name")
    output = args.root / "results/evaluation" / args.experiment / args.task
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite evaluation: {output}")
    output.mkdir(parents=True)
    rows = read_jsonl(args.root / "data/processed" / args.task / "test.jsonl")[:args.limit]
    tokenizer = get_tokenizer(args.model)
    model = load_base(args.model, dtype).to("cuda").eval()
    result = {"task": args.task, "dtype": str(dtype), "do_sample": False, "max_new_tokens": 96,
              "structured_decoding": False, "metric_definition": "NFKC/whitespace/case-normalized character EM and bag-of-character F1; not official CMRC scores."}
    result["base"] = run_model(model, tokenizer, rows, output / "base_predictions.jsonl")
    model = PeftModel.from_pretrained(model, args.root / "adapters" / args.experiment / args.task).eval()
    result["adapter"] = run_model(model, tokenizer, rows, output / "adapter_predictions.jsonl")
    write_json(output / "summary.json", result)
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
