from __future__ import annotations

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
        chunks = await storage.search_chunks(document["filename"], limit=20)
        chunks = [item for item in chunks if item["document_id"] == document["id"]]
        if not chunks:
            chunks = await storage.search_chunks(document["id"], limit=20)
            chunks = [item for item in chunks if item["document_id"] == document["id"]]
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
    try:
        from deepagents import create_deep_agent
    except Exception:
        return None
    try:
        provider = get_model_provider()
        model = provider.langchain_model()

        async def read_evidence(_: str = "") -> str:
            """Read the evidence bundle selected for this review."""
            return evidence[:18000]

        async def write_report(report: str) -> str:
            """Return a report draft for the caller to persist."""
            return report

        agent = create_deep_agent(
            model=model,
            tools=[read_evidence, write_report],
            system_prompt=(
                "你是膜结构工程资料审查 Agent。只能使用提供的文档证据，"
                "比较设计方案、膜材规格和价格记录，不做结构安全计算和正式报价。"
            ),
            subagents=[
                {
                    "name": "design_researcher",
                    "description": "分析设计方案和工程案例",
                    "system_prompt": "只分析设计方案、结构形式和应用场景，并引用输入证据。",
                    "tools": [read_evidence],
                },
                {
                    "name": "material_researcher",
                    "description": "分析膜材规格和价格资料",
                    "system_prompt": "只分析膜材规格、单位、日期和价格来源，不生成正式报价。",
                    "tools": [read_evidence],
                },
            ],
        )
        result = await agent.ainvoke({"messages": [{"role": "user", "content": request.question}]})
        messages = result.get("messages", []) if isinstance(result, dict) else []
        answer = messages[-1].content if messages and hasattr(messages[-1], "content") else str(result)
        return answer, "deepagents"
    except Exception:
        return None


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
