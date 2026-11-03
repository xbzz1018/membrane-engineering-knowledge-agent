"""Derived search text and Markdown; original evidence bodies remain immutable."""

import hashlib
import json
import re

CONTEXT_VERSION = "metadata-v1"


def contextual_text(document: dict, chunk: dict) -> str:
    # Only parser/source metadata, no model-invented entities or engineering facts.
    context = {key: str(value) for key, value in {
        "文件": document.get("filename"), "上传版本": document.get("version"),
        "章节": chunk.get("heading_path"), "工作表": chunk.get("sheet_name"),
        "位置": chunk.get("location"),
    }.items() if value not in (None, "")}
    return "检索上下文（非原文）：" + json.dumps(context, ensure_ascii=False) + "\n原文：\n" + chunk["text"]


def document_index_model(provider, settings) -> str:
    name = provider.embedding_model
    if settings.CONTEXTUAL_RETRIEVAL_ENABLED:
        suffix = ":ctx-" + CONTEXT_VERSION
        if len(name + suffix) > 128:
            raise ValueError("Embedding model namespace exceeds 128 characters")
        return name + suffix
    return name


def _plain(value) -> str:
    return " ".join(str(value).splitlines()).replace("`", "'")


def _fenced(text: str) -> str:
    # Retain literal source text without letting embedded Markdown close a fence.
    longest = max((len(part) for part in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}text\n{text}\n{fence}"


def document_markdown(document: dict, chunks: list[dict]) -> str:
    lines = [
        f"# {_plain(document['filename'])}", "",
        "类型：原始资料的派生文本；原件及 Evidence 记录为追溯依据。", "",
        f"- 文档 ID：`{_plain(document['id'])}`",
        f"- 上传版本：{document['version']}",
        f"- 原件 SHA-256：`{document.get('sha256', '')}`",
        f"- 解析器：{_plain(document.get('parser', ''))}",
        "- 此导出不包含检索增强前缀，不保证重建原件版式。", "",
    ]
    for row in chunks:
        digest = hashlib.sha256(row["text"].encode()).hexdigest()
        lines.extend([
            f"## Evidence `{_plain(row['id'])}`", "",
            f"位置：{_plain(row.get('location') or row.get('page_number', ''))}；"
            f"章节：{_plain(row.get('heading_path', ''))}", "",
            f"原文 SHA-256：`{digest}`", "", _fenced(row["text"]), "",
        ])
    return "\n".join(lines)


def review_markdown(review: dict) -> str:
    lines = [
        "# 资料包审查报告", "", "类型：模型与规则生成的待复核产物，不能自动作为原始证据入库。", "",
        f"- 审查 ID：`{_plain(review['review_id'])}`",
        f"- 当前状态：{_plain(review['status'])}",
        f"- 报告锁版本：{review.get('lock_version', 1)}", "",
        "## 生成时报告正文", "", _fenced(review.get("report", "")), "",
        "## 当前问题处理", "",
    ]
    for issue in review.get("issues", []):
        lines.extend([
            f"### {_plain(issue['issue_id'])}", "",
            f"状态：{_plain(issue['status'])}；领域：{_plain(issue['domain'])}", "",
            _fenced(issue.get("summary", "")), "",
            "证据：" + ", ".join(f"`{_plain(item)}`" for item in issue.get("evidence_ids", [])), "",
        ])
    lines.extend(["## 来源定位", ""])
    for source in review.get("sources", []):
        lines.extend([
            f"- `{_plain(source['source_id'])}`：{_plain(source['title'])}；"
            f"{_plain(source.get('location', ''))}；上传版本 {_plain(source.get('version', ''))}；"
            f"原件 SHA `{_plain(source.get('document_sha256', ''))}`", "",
        ])
    return "\n".join(lines)
