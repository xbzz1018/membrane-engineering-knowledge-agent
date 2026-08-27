"""Add reproducible provenance fields to the small hand-authored case fixture."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

PATH = Path("data/processed/cases.jsonl")


def main() -> None:
    rows = [json.loads(line) for line in PATH.read_text(encoding="utf-8").splitlines() if line]
    enriched = []
    for original in rows:
        row = {
            **original,
            "license": original.get("license") or "Project-generated synthetic fixture; repository LICENSE applies.",
            "retrieved_at": original.get("retrieved_at") or "2026-08-27T00:00:00+00:00",
        }
        payload = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        row["source_sha256"] = original.get("source_sha256") or hashlib.sha256(payload.encode("utf-8")).hexdigest()
        enriched.append(row)
    PATH.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in enriched) + "\n",
        encoding="utf-8",
    )
    print(f"enriched={len(enriched)} output={PATH}")


if __name__ == "__main__":
    main()
