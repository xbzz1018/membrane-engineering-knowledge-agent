"""Check tracked documentation links and immutable evaluation/evidence artifacts."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]


def repository_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT, check=True, capture_output=True,
    )
    return sorted({ROOT / name.decode("utf-8") for name in result.stdout.split(b"\0") if name})


def markdown_errors(path: Path) -> list[str]:
    # Examples inside fenced code are not navigable documentation links.
    body = re.sub(r"^(`{3,}|~{3,}).*?^\1[^\n]*$", "", path.read_text(encoding="utf-8"),
                  flags=re.MULTILINE | re.DOTALL)
    links = re.findall(r"!?\[[^\]\n]*\]\(\s*(<[^>]+>|[^\s)]+)", body)
    links += re.findall(r"\b(?:src|srcset)=[\"']([^\"']+)[\"']", body)
    errors = []
    for link in links:
        link = link.strip("<>")
        target = urlsplit(link)
        if target.scheme or target.netloc or not target.path:
            continue
        if not (path.parent / unquote(target.path)).exists():
            errors.append(f"{path.relative_to(ROOT)}: missing local target {link}")
    return errors


def validate() -> int:
    errors = []
    files = repository_files()
    markdown = [path for path in files if path.suffix == ".md" and path.is_file()]
    for path in markdown:
        errors.extend(markdown_errors(path))

    hashes = sorted((ROOT / "data/eval").glob("*.sha256"))
    for checksum in hashes:
        targets = [path for path in checksum.parent.glob(checksum.stem + ".*") if path != checksum]
        if len(targets) != 1:
            errors.append(f"{checksum.name}: expected one dataset, got {len(targets)}")
            continue
        expected = checksum.read_text(encoding="utf-8").split()[0]
        if hashlib.sha256(targets[0].read_bytes()).hexdigest() != expected:
            errors.append(f"{targets[0].relative_to(ROOT)}: frozen dataset hash mismatch")

    archive = ROOT / "docs/validation-artifacts"
    records = json.loads((archive / "evidence-index.json").read_text(encoding="utf-8"))
    indexed = set()
    for record in records:
        name = record["archived_file"]
        indexed.add(name)
        target = archive / name
        if target.parent != archive or not target.is_file():
            errors.append(f"evidence index: missing or invalid archive {name}")
        elif hashlib.sha256(target.read_bytes()).hexdigest() != record["archived_sha256"]:
            errors.append(f"evidence index: archive hash mismatch {name}")
        if not re.fullmatch(r"[0-9a-f]{64}", record["original_sha256"]):
            errors.append(f"evidence index: invalid original hash {name}")
    archived = {path.name for path in archive.iterdir() if path.suffix in {".json", ".xml"}}
    archived.discard("evidence-index.json")
    if archived != indexed or len(indexed) != len(records):
        errors.append("evidence index: duplicate or unindexed archives")

    lab = ROOT / "experiments/local_lora/evidence/2026-11-10"
    manifest = json.loads((lab / "manifest.json").read_text(encoding="utf-8"))
    for record in manifest["files"]:
        target = (lab / record["snapshot"]).resolve()
        if not target.is_relative_to(lab.resolve()) or not target.is_file():
            errors.append("local LoRA evidence: invalid or missing snapshot")
        elif hashlib.sha256(target.read_bytes()).hexdigest() != record["sha256"]:
            errors.append(f"local LoRA evidence: hash mismatch {record['snapshot']}")

    print(f"markdown={len(markdown)} frozen_datasets={len(hashes)} evidence_archives={len(records)}")
    if errors:
        print("\n".join(errors))
        return 1
    print("repository-validation-ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(validate())
