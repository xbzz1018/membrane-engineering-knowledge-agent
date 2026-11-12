"""Convert public data to fixed, grouped SFT splits; never edit raw sources."""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import Counter, defaultdict
from pathlib import Path

from lab_common import (
    DEFAULT_MODEL,
    MODEL_REVISION,
    TASK_LIMITS,
    encode_sample,
    get_tokenizer,
    normalize,
    prompt_messages,
    stable_id,
    write_json,
)


def take_groups(rows, sizes, seed):
    groups = defaultdict(list)
    for row in rows:
        groups[row["group"]].append(row)
    keys = sorted(groups)
    rng = random.Random(seed)
    rng.shuffle(keys)
    index, splits = 0, {}
    for name, size in sizes.items():
        selected = []
        while len(selected) < size and index < len(keys):
            values = list(groups[keys[index]])
            index += 1
            rng.shuffle(values)
            # Remaining examples in this group are withheld, never reused in another split.
            selected.extend(values[:size - len(selected)])
        if len(selected) != size:
            raise ValueError(f"Insufficient grouped data for {name}: {len(selected)} < {size}")
        splits[name] = selected
    used = []
    for name, values in splits.items():
        group_set = {row["group"] for row in values}
        assert all(not group_set & previous for previous in used), f"Group leakage: {name}"
        used.append(group_set)
    return splits


def record(task, source_id, group, messages, answer, references, **metadata):
    return {"task": task, "id": source_id, "group": group, "prompt": messages,
            "completion": [{"role": "assistant", "content": json.dumps(answer, ensure_ascii=False, separators=(",", ":"))}],
            "references": references, "metadata": metadata}


def rewrite_candidates(raw, tokenizer):
    counts, inputs = Counter(), defaultdict(list)
    for number, line in enumerate((raw / "rewrite/corpus.txt").read_text(encoding="utf-8-sig").splitlines(), 1):
        counts["raw_rows"] += 1
        fields = line.split("\t\t")
        if len(fields) != 4 or any(not value.strip() for value in fields):
            counts["empty_or_malformed"] += 1
            continue
        inputs[tuple(normalize(value) for value in fields[:3])].append((number, fields))
    rows = []
    for key, items in inputs.items():
        if len({normalize(fields[3]) for _, fields in items}) > 1:
            counts["ambiguous_input_groups_withheld"] += 1
            counts["ambiguous_rows_withheld"] += len(items)
            continue
        number, fields = items[0]
        counts["duplicate_normalized_inputs_withheld"] += len(items) - 1
        a, b, question, rewritten = fields
        row = record("query_rewriter", f"REWRITE_L{number}", stable_id(key[:2]),
                     prompt_messages("query_rewriter", context1=a, context2=b, question=question),
                     {"query": rewritten}, [rewritten], line=number, source="REWRITE")
        encoded = encode_sample(tokenizer, row)
        row["tokens"] = len(encoded["input_ids"])
        if row["tokens"] <= TASK_LIMITS["query_rewriter"]:
            rows.append(row)
        else:
            counts["over_length"] += 1
    counts["eligible_rows"] = len(rows)
    return rows, dict(counts)


def cmrc_candidates(raw, split, tokenizer):
    filename = "cmrc2018_train.json" if split == "train" else "cmrc2018_dev.json"
    content = json.loads((raw / "cmrc2018" / filename).read_text(encoding="utf-8-sig"))
    counts, rows, seen = Counter(), [], set()
    all_groups = set()
    for article in content["data"]:
        for paragraph in article["paragraphs"]:
            context = paragraph["context"]
            group = stable_id([normalize(context)])
            all_groups.add(group)
            for question in paragraph["qas"]:
                counts["raw_questions"] += 1
                key = (normalize(context), normalize(question["question"]))
                if key in seen:
                    counts["duplicate_input"] += 1
                    continue
                seen.add(key)
                valid, offsets = [], []
                for answer in question.get("answers", []):
                    text, start = answer["text"], answer["answer_start"]
                    if not text.strip():
                        continue
                    if start >= 0 and context[start:start + len(text)] == text:
                        position, method = start, "original_python_offset"
                    else:
                        raw16, text16 = context.encode("utf-16-le"), text.encode("utf-16-le")
                        if start >= 0 and raw16[start * 2:start * 2 + len(text16)] == text16:
                            position = len(raw16[:start * 2].decode("utf-16-le"))
                            method = "utf16_to_python"
                            counts["utf16_reference_offsets_converted"] += 1
                        elif text in context:
                            position, method = context.index(text), "text_presence_only"
                        else:
                            counts["non_extractable_reference_answers"] += 1
                            continue
                    assert context[position:position + len(text)] == text
                    valid.append(text)
                    offsets.append({"text": text, "raw_start": start, "python_start": position, "method": method})
                if not valid:
                    counts["no_extractable_answer"] += 1
                    continue
                # All original references are retained for reference-answer QA scoring;
                # exact-extraction checks use only the verified alternatives.
                references = list(dict.fromkeys(answer["text"] for answer in question["answers"] if answer["text"].strip()))
                row = record("grounded_qa", question["id"], group,
                             prompt_messages("grounded_qa", context=context, question=question["question"]),
                             {"answer": valid[0], "source_id": "D1"}, references,
                             source=f"CMRC2018/{split}", title=article.get("title", ""),
                             extractable_references=list(dict.fromkeys(valid)), answer_offsets=offsets,
                             context=context, question=question["question"])
                row["tokens"] = len(encode_sample(tokenizer, row)["input_ids"])
                if row["tokens"] <= TASK_LIMITS["grounded_qa"]:
                    rows.append(row)
                else:
                    counts["over_length"] += 1
    counts["eligible_questions"] = len(rows)
    return rows, dict(counts), all_groups


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    raw = args.root / "data/raw"
    output = args.root / "data/processed"
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"Refusing to overwrite prepared splits: {output}")
    manifest = json.loads((raw / "manifest.json").read_text(encoding="utf-8-sig"))
    for item in manifest["files"]:
        assert hashlib.sha256((raw / item["relative_path"]).read_bytes()).hexdigest() == item["sha256"]
    tokenizer = get_tokenizer(args.model)
    rewrite, rewrite_stats = rewrite_candidates(raw, tokenizer)
    train, train_stats, train_groups = cmrc_candidates(raw, "train", tokenizer)
    dev, dev_stats, dev_groups = cmrc_candidates(raw, "dev", tokenizer)
    assert not train_groups & dev_groups, "CMRC train/dev context overlap"
    tasks = {"query_rewriter": take_groups(rewrite, {"test": 100, "validation": 100, "train": 600}, args.seed),
             "grounded_qa": {**take_groups(train, {"validation": 100, "train": 600}, args.seed),
                             **take_groups(dev, {"test": 100}, args.seed)}}
    summary = {"seed": args.seed, "model": args.model, "model_revision": MODEL_REVISION,
               "thinking": False, "completion_only_loss": True, "raw_sources": manifest,
               "filtering": {"rewrite": rewrite_stats, "cmrc_train": train_stats, "cmrc_dev": dev_stats},
               "splits": {}}
    for task, splits in tasks.items():
        summary["splits"][task] = {}
        for split, rows in splits.items():
            path = output / task / f"{split}.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
            summary["splits"][task][split] = {"rows": len(rows), "groups": len({row["group"] for row in rows}),
                                              "max_tokens": max(row["tokens"] for row in rows),
                                              "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                                              "ids": [row["id"] for row in rows]}
        for a, b in [("train", "validation"), ("train", "test"), ("validation", "test")]:
            assert not {row["group"] for row in splits[a]} & {row["group"] for row in splits[b]}
        smoke = splits["train"][:100]
        (output / task / "smoke.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in smoke), encoding="utf-8")
    write_json(output / "preparation_manifest.json", summary)
    print(json.dumps({"filtering": summary["filtering"], "splits": {
        task: {split: {k:v for k,v in info.items() if k != "ids"} for split,info in splits.items()}
        for task,splits in summary["splits"].items()}}, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
