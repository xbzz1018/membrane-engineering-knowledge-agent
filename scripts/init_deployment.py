"""Generate an isolated Compose .env; never overwrite an existing deployment."""

from __future__ import annotations

import argparse
import os
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SECRET_KEYS = {
    "POSTGRES_PASSWORD", "TEMPORAL_DB_PASSWORD", "REDIS_PASSWORD",
    "MINIO_ROOT_PASSWORD", "JWT_SECRET", "BOOTSTRAP_ADMIN_PASSWORD",
}


def initialize(target: Path, template: Path | None = None) -> Path:
    template = template or ROOT / "deploy/.env.example"
    replacements = {key: secrets.token_hex(24) for key in SECRET_KEYS}
    lines = []
    for line in template.read_text(encoding="utf-8").splitlines():
        key, separator, _ = line.partition("=")
        lines.append(f"{key}={replacements[key]}" if separator and key in replacements else line)
    target.parent.mkdir(parents=True, exist_ok=True)
    # O_EXCL protects a previously generated deployment even during concurrent invocations.
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
        stream.write("\n".join(lines) + "\n")
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "deploy/.env")
    args = parser.parse_args()
    try:
        target = initialize(args.output)
    except FileExistsError:
        raise SystemExit("Existing deployment configuration preserved; edit it directly or use another --output") from None
    print(f"Created {target.resolve()}. Admin password is BOOTSTRAP_ADMIN_PASSWORD in that file.")
    print("Default: Full storage + Fake models, TXT/native Office. See docs/deployment.md for API models and PDF/OCR.")


if __name__ == "__main__":
    main()
