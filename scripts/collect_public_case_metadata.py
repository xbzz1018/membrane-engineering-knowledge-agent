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
DETAIL_PATTERN = re.compile(
    r'<span\s+class="project-subtitle">\s*(?P<label>.*?)\s*</span>\s*'
    r'<h5[^>]*>\s*(?P<value>.*?)\s*</h5>',
    re.IGNORECASE | re.DOTALL,
)


def _text(pattern: str, body: str) -> str:
    match = re.search(pattern, body, re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    value = re.sub(r"<[^>]+>", " ", match.group(1))
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def parse_project_detail(content: str) -> dict[str, str]:
    """Extract the stable label/value pairs from a TensiNet project page."""
    fields: dict[str, str] = {}
    for match in DETAIL_PATTERN.finditer(content):
        label = re.sub(r"\s+", " ", html.unescape(match.group("label"))).strip()
        value = re.sub(
            r"\s+",
            " ",
            html.unescape(re.sub(r"<[^>]+>", " ", match.group("value"))),
        ).strip()
        if label and value and label not in fields:
            fields[label] = value
    return fields


def enrich_project(row: dict, detail: dict[str, str], detail_url: str, detail_content: str) -> dict:
    """Merge detail-page facts while retaining the original listing provenance."""
    address = detail.get("Location address", "")
    country = detail.get("Location country", "")
    if address:
        row["location_address"] = address
    if country:
        row["location_country"] = country
    if address or country:
        row["location"] = ", ".join(value for value in (address, country) if value)

    year_match = re.search(r"\b(19|20)\d{2}\b", detail.get("Year of construction", ""))
    if year_match:
        row["year"] = int(year_match.group(0))
    row["application"] = detail.get("Function of building", row.get("application", ""))
    row["structure_type"] = detail.get(
        "Cable-net/Fabric/Hybrid/Foil", row.get("structure_type", "")
    )
    material = detail.get("Material Fabric/Foil", "")
    coating = detail.get("Material coating", "")
    if material and coating:
        row["membrane_material"] = f"{material} / {coating}"
    elif material:
        row["membrane_material"] = material
    row["cover_type"] = detail.get("Type (code)", "")
    row["detail_source_url"] = detail_url
    row["detail_source_sha256"] = hashlib.sha256(detail_content.encode("utf-8")).hexdigest()
    row["detail_retrieved_at"] = datetime.now(UTC).isoformat()
    row["detail_status"] = "ok"
    return row


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


def fetch_with_retry(opener, url: str, delay: float, attempts: int = 3) -> str:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            return fetch(opener, url)
        except Exception as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(min(2.0, max(delay, 0.2) * (2**attempt)))
    raise last_error or RuntimeError("detail fetch failed")


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
    collected = list(rows.values())[:limit]
    for index, row in enumerate(collected):
        try:
            detail_content = fetch_with_retry(opener, row["source_url"], delay)
            enrich_project(row, parse_project_detail(detail_content), row["source_url"], detail_content)
        except Exception as exc:
            row["detail_status"] = "failed"
            row["detail_error"] = type(exc).__name__
        if index + 1 < len(collected):
            time.sleep(max(delay, 0))
    return collected


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
