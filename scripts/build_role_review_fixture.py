"""Version the explicit optional-price policy; never derive labels from predictions."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build():
    folder = ROOT / "data/eval"
    rows = [json.loads(line) for line in (folder / "business_review_v1.jsonl").read_text(encoding="utf-8").splitlines()]
    gold = json.loads((folder / "business_expectations_v2.json").read_text(encoding="utf-8"))
    row = next(row for row in rows if row["eval_id"] == "missing-price")
    row.update(expected_human_review=False, expected_issue_types=[], expected_evidence_documents=[])
    gold["cases"]["missing-price"] = []
    gold["protocol"] = "business_review_v3"
    gold["policy_change"] = "No price document is required for a design/specification review. Existing price records are still checked."
    gold["not_a_held_out_test"] = True
    outputs = {
        "business_review_v3.jsonl": "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        "business_expectations_v3.json": json.dumps(gold, ensure_ascii=False, indent=2) + "\n",
    }
    for name, content in outputs.items():
        path = folder / name
        raw = content.encode("utf-8")
        if path.exists() and path.read_bytes() != raw:
            raise ValueError("Refusing to overwrite a frozen dataset")
        path.write_bytes(raw)
        path.with_suffix(".sha256").write_text(hashlib.sha256(raw).hexdigest() + "\n", encoding="ascii")


if __name__ == "__main__":
    build()
