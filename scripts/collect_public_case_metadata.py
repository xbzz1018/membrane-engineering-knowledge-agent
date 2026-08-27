"""Collect public TensiNet project metadata without downloading images or documents."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import time
from datetime import UTC, datetime
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.parse import urlencode, urljoin
from urllib.request import HTTPCookieProcessor, Request, build_opener

BASE_URL = "https://www.tensinet.com/index.php/component/tensinet/"
PROJECT_PATTERN = re.compile(
    r'<a\s+href="(?P<href>/index\.php/projects-database/projects/(?P<id>\d+))"(?P<body>.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)


def _text(pattern: str, body: str) -> str:
    match = re.search(pattern, body, re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    value = re.sub(r"<[^>]+>", " ", match.group(1))
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def parse_projects(content: str, source_page_url: str = BASE_URL, source_sha256: str = "") -> list[dict]:
    rows = []
    for match in PROJECT_PATTERN.finditer(content):
        body = match.group("body")
        rows.append({
            "case_id": f"tensinet-{match.group('id')}",
            "title": _text(r'class="project-title"[^>]*>(.*?)</h3>', body),
            "application": "",
            "structure_type": _text(r'project-info-title">Type</span>\s*<h5>(.*?)</h5>', body) or "unknown",
            "membrane_material": "",
            "location": _text(r'project-info-title">Location:\s*</span>\s*<h5>(.*?)</h5>', body) or "unknown",
            "year": None,
            "source_url": urljoin(BASE_URL, match.group("href")),
            "source_page_url": source_page_url,
            "source_type": "public_metadata",
            "license": "TensiNet site terms; metadata and source link only",
            "retrieved_at": datetime.now(UTC).isoformat(),
            "source_sha256": source_sha256 or hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "synthetic": False,
        })
    return rows


def fetch(opener, url: str, data: bytes | None = None) -> str:
    request = Request(url, headers={"User-Agent": "membrane-engineering-knowledge-agent/0.1"})
    if data is not None:
        request = Request(url, data=data, headers={"User-Agent": "membrane-engineering-knowledge-agent/0.1"})
    with opener.open(request, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


def collect(limit: int, delay: float) -> list[dict]:
    rows: dict[str, dict] = {}
    opener = build_opener(HTTPCookieProcessor(CookieJar()))
    first_page = fetch(opener, BASE_URL)
    token_match = re.search(r'<input type="hidden" name="([a-f0-9]{32})" value="1"', first_page)
    token = token_match.group(1) if token_match else ""
    for offset in range(0, max(limit, 1) + 200, 21):
        if offset == 0:
            page = first_page
        else:
            form = {
                "task": "",
                "boxchecked": "0",
                "filter_order": "Nameoftheproject",
                "filter_order_Dir": "asc",
                "limitstart": str(offset),
                "list[limitstart]": str(offset),
            }
            if token:
                form[token] = "1"
            page = fetch(opener, urljoin(BASE_URL, "/index.php/projects-database/projects"), urlencode(form).encode())
        source_page_url = BASE_URL if offset == 0 else urljoin(BASE_URL, "/index.php/projects-database/projects")
        page_rows = parse_projects(
            page,
            source_page_url=source_page_url,
            source_sha256=hashlib.sha256(page.encode("utf-8")).hexdigest(),
        )
        if not page_rows:
            break
        for row in page_rows:
            rows[row["case_id"]] = row
        if len(rows) >= limit:
            break
        time.sleep(max(delay, 0))
    return list(rows.values())[:limit]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--delay", type=float, default=0.5)
    parser.add_argument("--output", type=Path, default=Path("data/processed/public_cases.jsonl"))
    args = parser.parse_args()
    rows = collect(args.limit, args.delay)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")
    print(f"collected={len(rows)} output={args.output}")


if __name__ == "__main__":
    main()
