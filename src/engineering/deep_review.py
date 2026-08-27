from __future__ import annotations

import asyncio
import uuid
from typing import Any

from src.core.config import get_settings
from src.engineering.provider import get_model_provider
from src.engineering.schemas import PackageReviewRequest, SourceRef
from src.engineering.storage import storage


async def _collect_evidence(document_ids: list[str]) -> tuple[str, list[dict[str, Any]]]:
    documents = await storage.list_documents(document_ids)
    if len(documents) != len(set(document_ids)):
        known = {item["id"] for item in documents}
        missing = sorted(set(document_ids) - known)
        raise ValueError(f"文档不存在: {', '.join(missing)}")
    parts: list[str] = []
    sources: list[dict[str, Any]] = []
    for document in documents:
        chunks = await storage.list_document_chunks(document["id"], limit=20)
        sources.append(SourceRef(
            source_id=f"doc:{document['id']}",
            title=document["filename"],
            source_type="uploaded_document",
            location="",
        ).model_dump())
        for chunk in chunks[:8]:
            sources.append(SourceRef(
                source_id=f"doc:{document['id']}:{chunk['chunk_index']}",
                title=document["filename"],
                source_type="document_fragment",
                location=f"第{chunk['page_number']}页",
                excerpt=chunk["text"][:400],
            ).model_dump())
            parts.append(f"[{document['filename']} 第{chunk['page_number']}页]\n{chunk['text']}")
    return "\n\n---\n\n".join(parts), sources


def _find_conflicts(evidence: str) -> list[str]:
    # Lightweight deterministic checks keep the example useful without claiming engineering validation.
    conflicts: list[str] = []
    if evidence.count("厚度") > 1 and "厚度" in evidence and ("0.7" in evidence and "0.8" in evidence):
        conflicts.append("不同资料出现不同厚度值，需要核对文档版本")
    if evidence.count("价格") > 1 and ("元/平方米" in evidence or "元/m²" in evidence):
        conflicts.append("不同资料可能包含不同日期的价格区间，需要确认生效日期")
    return conflicts


async def _run_deepagents(request: PackageReviewRequest, evidence: str) -> tuple[str, str] | None:
    settings = get_settings()
    if not settings.DEEPAGENTS_ENABLED:
        return None
    if len(request.document_ids) < 2:
        raise ValueError("DeepAgents 资料包审查至少需要两个文档")
    from deepagents import (
        GeneralPurposeSubagentProfile,
        HarnessProfile,
        create_deep_agent,
        register_harness_profile,
    )
    from deepagents.backends import StateBackend
    from deepagents.middleware.filesystem import FilesystemMiddleware, FilesystemPermission

    provider = get_model_provider()
    model = provider.langchain_model()
    backend = StateBackend()
    permissions = [
        FilesystemPermission(operations=["read"], paths=["/evidence/**"], mode="allow"),
        FilesystemPermission(operations=["read", "write"], paths=["/**"], mode="deny"),
    ]

    def restricted_filesystem() -> FilesystemMiddleware:
        return FilesystemMiddleware(
            backend=backend,
            tools=["ls", "read_file"],
            _permissions=permissions,
        )

    register_harness_profile(
        "openai",
        HarnessProfile(
            excluded_tools=frozenset({"execute", "write_file", "edit_file", "delete", "glob", "grep"}),
            general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
        ),
    )
    subagents = [
        {
            "name": "design_reviewer",
            "description": "审查设计方案、结构形式、适用场景和版本冲突",
            "system_prompt": (
                "只读取 /evidence/package.md，审查设计方案、结构形式、适用场景和版本冲突。"
                "每个结论必须引用文件名和页码；不做结构安全计算。"
            ),
            "tools": [],
            "middleware": [restricted_filesystem()],
            "permissions": permissions,
        },
        {
            "name": "material_reviewer",
            "description": "审查膜材型号、规格、单位、日期和版本",
            "system_prompt": (
                "只读取 /evidence/package.md，审查膜材型号、规格、单位、日期和版本。"
                "每个结论必须引用文件名和页码；证据不足时明确说明。"
            ),
            "tools": [],
            "middleware": [restricted_filesystem()],
            "permissions": permissions,
        },
        {
            "name": "price_reviewer",
            "description": "审查价格记录的单位、日期、来源和可比性",
            "system_prompt": (
                "只读取 /evidence/package.md，审查价格记录的单位、日期、来源和可比性。"
                "不得生成正式报价；每个结论必须引用文件名和页码。"
            ),
            "tools": [],
            "middleware": [restricted_filesystem()],
            "permissions": permissions,
        },
    ]
    agent = create_deep_agent(
        model=model,
        tools=[],
        backend=backend,
        permissions=permissions,
        middleware=[restricted_filesystem()],
        system_prompt=(
            "你是膜结构工程资料包主审 Agent。必须分别委派 design_reviewer、material_reviewer、"
            "price_reviewer，然后仅依据 /evidence/package.md 汇总。报告包含方案、膜材、价格、冲突、"
            "证据不足和待人工确认；不得进行结构安全计算或生成正式报价。"
        ),
        subagents=subagents,
    )
    state = {
        "messages": [{"role": "user", "content": request.question}],
        "files": {
            "/evidence/package.md": {
                "content": evidence[:50000],
                "encoding": "utf-8",
            }
        },
    }
    result = await asyncio.wait_for(
        agent.ainvoke(state),
        timeout=settings.DEEPAGENTS_TIMEOUT_SECONDS,
    )
    messages = result.get("messages", []) if isinstance(result, dict) else []
    answer = messages[-1].content if messages and hasattr(messages[-1], "content") else str(result)
    if not isinstance(answer, str) or not answer.strip():
        raise RuntimeError("DeepAgents returned an empty report")
    return answer, "deepagents"


async def run_package_review(request: PackageReviewRequest) -> dict[str, Any]:
    evidence, sources = await _collect_evidence(request.document_ids)
    conflicts = _find_conflicts(evidence)
    deep_result = await _run_deepagents(request, evidence)
    if deep_result:
        report, engine_name = deep_result
    else:
        provider = get_model_provider()
        prompt = (
            f"任务：{request.question}\n资料证据：\n{evidence or '没有可用证据'}\n"
            f"已发现的确定性冲突：{conflicts or '无'}\n"
            "请输出简短的方案比较摘要、规格差异、价格资料日期和待人工确认事项。"
        )
        report, _ = await provider.chat(
            "你是膜结构工程资料审查助手，只能依据证据回答，不得生成正式报价或安全结论。",
            prompt,
        )
        engine_name = "local-fallback"
    if conflicts:
        report = f"{report}\n\n待人工确认：\n" + "\n".join(f"- {item}" for item in conflicts)
    return {
        "review_id": uuid.uuid4().hex,
        "status": "completed",
        "engine": engine_name,
        "report": report,
        "sources": sources[:20],
        "conflicts": conflicts,
    }
