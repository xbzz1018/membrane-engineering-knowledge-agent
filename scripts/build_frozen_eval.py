"""Build the attested v3 retrieval and package-review evaluation sets."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path("data/eval")
PACKAGE_OUTPUT = ROOT / "frozen_package_review_v3.jsonl"
DIFFICULT_OUTPUT = ROOT / "frozen_difficult_retrieval_v3.jsonl"


def _read(path: str) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line]


def build_packages() -> list[dict]:
    return [
        {
            "eval_id": f"package-{index:03d}",
            "question": "审查设计、膜材和价格资料，识别厚度与版本冲突。",
            "documents": [
                f"设计资料 {index}：PTFE 膜材厚度 0.7 mm，设计版本 1，日期 2025-01。",
                f"采购价格资料 {index}：PTFE 膜材厚度 0.8 mm，版本 2，日期 2025-02，synthetic 价格。",
            ],
            "expected_conflict": True,
        }
        for index in range(1, 21)
    ]


def build_difficult_retrieval() -> list[dict]:
    materials = ["PTFE", "ETFE", "PVC/PVDF", "PTFE网格膜", "PVDF膜材"]
    applications = ["交通枢纽雨棚", "体育场看台", "商业入口", "停车棚", "景观连廊"]
    rows = []
    for index in range(1, 31):
        material = materials[(index - 1) % len(materials)]
        application = applications[(index - 1) % len(applications)]
        distractor = materials[index % len(materials)]
        code = f"MSE-{index:03d}"
        version = f"D{(index % 4) + 1}"
        thickness = round(0.5 + ((index % 6) * 0.1), 1)
        archive_alias = hashlib.sha256(f"archive-alias-{index}".encode()).hexdigest()[:10]
        filename = f"工程归档-{archive_alias}.txt"
        content = (
            f"工程编号：{code}。项目场景：{application}。采用膜材：{material}。"
            f"设计版本：{version}。名义厚度：{thickness}毫米。"
            "本记录仅用于检索评测，不构成结构安全结论或正式报价。"
        )
        common = {
            "document_key": code,
            "filename": filename,
            "content": content,
            "business_version": 5000 + index,
        }
        rows.append({
            **common,
            "eval_id": f"filename-{index:03d}",
            "difficulty": "filename_and_version",
            "query": f"请定位文件 {filename}，其中记录的设计版本是什么？",
        })
        rows.append({
            **common,
            "eval_id": f"paraphrase-{index:03d}",
            "difficulty": "paraphrase_with_distractor",
            "query": (
                f"编号 {code} 的{application}不是采用{distractor}，实际膜材、设计版次和名义厚度分别是什么？"
            ),
        })
    if len(rows) != 60:
        raise AssertionError(f"difficult retrieval set must contain 60 rows, got {len(rows)}")
    return rows


def _write(path: Path, rows: list[dict]) -> str:
    payload = "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows) + "\n"
    encoded = payload.encode("utf-8")
    path.write_bytes(encoded)
    digest = hashlib.sha256(encoded).hexdigest()
    path.with_suffix(".sha256").write_text(f"{digest}  {path.name}\n", encoding="ascii")
    return digest


def main() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    summary = {
        "package_review": {"rows": 20, "sha256": _write(PACKAGE_OUTPUT, build_packages())},
        "difficult_retrieval": {
            "rows": 60,
            "sha256": _write(DIFFICULT_OUTPUT, build_difficult_retrieval()),
        },
    }
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
