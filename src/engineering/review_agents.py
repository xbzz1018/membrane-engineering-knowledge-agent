from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Iterable
from typing import Any, Literal

from langchain.agents import create_agent
from langchain_core.messages import AIMessage
from pydantic import BaseModel, Field, ValidationError

from src.core.config import get_settings
from src.core.observability import span
from src.engineering.memory import get_memory_service
from src.engineering.provider import ModelProvider, get_model_provider
from src.engineering.schemas import PackageReviewRequest, SourceRef
from src.engineering.storage import EngineeringStorage, storage


class ReviewFinding(BaseModel):
    summary: str = Field(min_length=1, max_length=1000)
    severity: Literal["info", "warning", "conflict"] = "info"
    evidence_ids: list[str] = Field(default_factory=list)
    requires_human: bool = False


class WorkerReview(BaseModel):
    worker: Literal["design", "material", "price"]
    findings: list[ReviewFinding] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    processed_evidence_ids: list[str] = Field(default_factory=list)
    skipped_evidence_ids: list[str] = Field(default_factory=list)


class ReviewAgentError(RuntimeError):
    pass


WORKER_CONFIG = {
    "design": {
        "keywords": ("设计", "方案", "结构", "场景", "节点", "版本"),
        "prompt": "审查方案适用场景、结构形式、设计版本与跨文档冲突；不得做结构安全计算。",
    },
    "material": {
        "keywords": ("膜材", "材料", "型号", "规格", "厚度", "重量", "透光", "抗拉", "单位"),
        "prompt": "审查膜材型号、规格、单位、日期与版本一致性。",
    },
    "price": {
        "keywords": ("价格", "成本", "报价", "币种", "单价", "元/", "日期", "区域"),
        "prompt": "审查历史价格的单位、币种、日期、区域、来源和可比性；不得生成正式报价。",
    },
}


def _conflicts(text: str) -> list[str]:
    conflicts = []
    if "0.7" in text and "0.8" in text and "厚度" in text:
        conflicts.append("不同资料出现0.7与0.8的厚度值，需要核对资料版本")
    if text.count("价格") > 1 and ("元/平方米" in text or "元/m2" in text or "CNY/m2" in text):
        conflicts.append("价格资料存在多个日期或区间，需要确认可比口径")
    return conflicts


class PackageReviewService:
    def __init__(
        self,
        store: EngineeringStorage = storage,
        provider: ModelProvider | None = None,
    ):
        self.store = store
        self.provider = provider or get_model_provider()
        self.memory = get_memory_service(store)

    async def collect_evidence(
        self,
        request: PackageReviewRequest,
        tenant_id: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        documents = await self.store.list_documents(
            request.document_ids, project_id=request.project_id, tenant_id=tenant_id,
        )
        if len(documents) != len(set(request.document_ids)):
            known = {item["id"] for item in documents}
            missing = sorted(set(request.document_ids) - known)
            raise ValueError(f"文档不存在或不属于当前项目: {', '.join(missing)}")
        if self.provider.metadata.get("mode") == "api" and any(
            item["data_classification"] != "public" for item in documents
        ):
            raise ReviewAgentError("资料包包含非公开资料，未配置本地模型时禁止云端审查")
        evidence: list[dict[str, Any]] = []
        sources: list[dict[str, Any]] = []
        for document in documents:
            chunks = await self.store.list_document_chunks(document["id"], limit=5000)
            for chunk in chunks:
                evidence_id = str(chunk["id"])
                evidence.append({
                    "evidence_id": evidence_id,
                    "document_id": document["id"],
                    "filename": document["filename"],
                    "version": document["version"],
                    "location": chunk.get("location") or f"第{chunk['page_number']}页",
                    "text": chunk["text"],
                    "token_count": int(chunk.get("token_count") or max(1, len(chunk["text"]) // 3)),
                })
                sources.append(SourceRef(
                    source_id=evidence_id,
                    title=document["filename"],
                    source_type="document_fragment",
                    location=chunk.get("location") or f"第{chunk['page_number']}页",
                    excerpt=chunk["text"][:300],
                    date=document["created_at"].isoformat(),
                    version=str(document["version"]),
                ).model_dump())
        return documents, evidence, sources

    @staticmethod
    def _worker_evidence(worker: str, evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
        keywords = WORKER_CONFIG[worker]["keywords"]
        matched = [item for item in evidence if any(word in item["text"].lower() for word in keywords)]
        return matched or evidence

    @staticmethod
    def _batches(evidence: list[dict[str, Any]], token_budget: int) -> list[list[dict[str, Any]]]:
        batches: list[list[dict[str, Any]]] = []
        current: list[dict[str, Any]] = []
        current_tokens = 0
        for item in evidence:
            tokens = max(1, int(item.get("token_count", 1)))
            if current and current_tokens + tokens > token_budget:
                batches.append(current)
                current = []
                current_tokens = 0
            current.append(item)
            current_tokens += tokens
        if current:
            batches.append(current)
        return batches or [[]]

    async def _run_worker_batch(
        self,
        worker: str,
        question: str,
        batch: list[dict[str, Any]],
        memories: list[str],
    ) -> tuple[WorkerReview, dict[str, Any]]:
        evidence_map = {item["evidence_id"]: item for item in batch}
        if self.provider.metadata.get("mode") != "api":
            text = "\n".join(item["text"] for item in batch)
            findings = [ReviewFinding(
                summary=conflict,
                severity="conflict",
                evidence_ids=list(evidence_map)[:4],
                requires_human=True,
            ) for conflict in _conflicts(text)]
            if not findings and batch:
                findings.append(ReviewFinding(
                    summary=f"{worker}审查已完成，未发现确定性冲突",
                    evidence_ids=list(evidence_map)[:2],
                ))
            return WorkerReview(
                worker=worker,
                findings=findings,
                processed_evidence_ids=list(evidence_map),
            ), {"provider": "fake", "input_tokens": sum(item["token_count"] for item in batch)}

        agent = create_agent(
            model=self.provider.langchain_model(),
            tools=[],
            system_prompt=(
                f"你是膜结构{worker}审查Worker。{WORKER_CONFIG[worker]['prompt']}"
                "只能读取用户消息提供的Evidence，每条发现必须引用evidence_id。"
                "项目记忆不是证据；证据不足写入uncertainties。仅输出符合WorkerReview字段的JSON对象，禁止Markdown。"
            ),
            name=f"{worker}_review_agent",
        )
        schema = json.dumps(WorkerReview.model_json_schema(), ensure_ascii=False)
        base_content = (
            f"审查问题：{question}\n"
            f"Evidence：{json.dumps(list(evidence_map.values()), ensure_ascii=False)}\n"
            f"已确认项目记忆（仅作上下文）：{json.dumps(memories, ensure_ascii=False)}\n"
            f"worker字段必须是：{worker}\n"
            f"JSON Schema：{schema}\n"
            "findings示例：[{\"summary\":\"发现说明\",\"severity\":\"conflict\","
            "\"evidence_ids\":[\"文档ID:片段序号\"],\"requires_human\":true}]。"
        )
        structured: WorkerReview | None = None
        messages: list[Any] = []
        usage = {"input_tokens": 0, "output_tokens": 0}
        finish_reasons: list[str] = []
        correction = ""
        with span("gen_ai.invoke_agent", {
            "gen_ai.agent.name": f"{worker.title()}ReviewAgent",
            "gen_ai.provider.name": str(self.provider.metadata.get("provider", "")),
            "gen_ai.request.model": str(self.provider.metadata.get("model", "")),
            "review.evidence_count": len(evidence_map),
        }):
            for attempt in range(2):
                result = await agent.ainvoke({
                    "messages": [{"role": "user", "content": base_content + correction}]
                })
                messages = result.get("messages", [])
                final_message = next(
                    (message for message in reversed(messages) if isinstance(message, AIMessage)),
                    None,
                )
                content = final_message.content if final_message is not None else ""
                if not isinstance(content, str):
                    raise ReviewAgentError(f"{worker} Worker结构化输出无效")
                response_metadata = getattr(final_message, "response_metadata", None) or {}
                finish_reason = str(response_metadata.get("finish_reason", ""))
                finish_reasons.append(finish_reason)
                if finish_reason == "length":
                    raise ReviewAgentError(f"{worker} Worker输出被截断")
                metadata = getattr(final_message, "usage_metadata", None) or {}
                usage["input_tokens"] += int(metadata.get("input_tokens", 0) or 0)
                usage["output_tokens"] += int(metadata.get("output_tokens", 0) or 0)
                normalized = content.strip()
                if normalized.startswith("```"):
                    normalized = normalized.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
                try:
                    structured = WorkerReview.model_validate_json(normalized)
                    break
                except ValidationError as exc:
                    if attempt == 1:
                        raise ReviewAgentError(f"{worker} Worker结构化输出无效") from exc
                    fields = [".".join(str(part) for part in item["loc"]) for item in exc.errors()]
                    correction = (
                        f"\n上次输出未通过Schema，错误字段：{fields}。"
                        "必须改用上面示例的summary、severity、evidence_ids数组和requires_human字段后重新输出。"
                    )
        if structured is None:
            raise ReviewAgentError(f"{worker} Worker结构化输出无效")
        invalid = {
            evidence_id
            for finding in structured.findings
            for evidence_id in finding.evidence_ids
            if evidence_id not in evidence_map
        }
        if invalid:
            raise ReviewAgentError(f"{worker} Worker引用无效证据: {sorted(invalid)}")
        usage["finish_reason"] = finish_reasons[-1] if finish_reasons else ""
        return structured, usage

    @staticmethod
    def _reduce_worker(worker: str, parts: Iterable[WorkerReview]) -> WorkerReview:
        findings: list[ReviewFinding] = []
        uncertainties: list[str] = []
        processed: list[str] = []
        skipped: list[str] = []
        seen = set()
        for part in parts:
            for finding in part.findings:
                key = (finding.summary, tuple(sorted(finding.evidence_ids)))
                if key not in seen:
                    seen.add(key)
                    findings.append(finding)
            uncertainties.extend(item for item in part.uncertainties if item not in uncertainties)
            processed.extend(item for item in part.processed_evidence_ids if item not in processed)
            skipped.extend(item for item in part.skipped_evidence_ids if item not in skipped)
        return WorkerReview(
            worker=worker,
            findings=findings,
            uncertainties=uncertainties,
            processed_evidence_ids=processed,
            skipped_evidence_ids=skipped,
        )

    async def run_worker(
        self,
        worker: str,
        question: str,
        evidence: list[dict[str, Any]],
        memories: list[str],
    ) -> tuple[WorkerReview, dict[str, Any]]:
        selected = self._worker_evidence(worker, evidence)
        evidence_budget = max(2000, int(get_settings().MODEL_CONTEXT_WINDOW * 0.60))
        parts = []
        usages = []
        for batch in self._batches(selected, evidence_budget):
            part, usage = await self._run_worker_batch(worker, question, batch, memories)
            parts.append(part)
            usages.append(usage)
        merged_usage = {
            "calls": len(usages),
            "input_tokens": sum(int(item.get("input_tokens", 0)) for item in usages),
            "output_tokens": sum(int(item.get("output_tokens", 0)) for item in usages),
            "finish_reasons": [item.get("finish_reason", "") for item in usages],
        }
        return self._reduce_worker(worker, parts), merged_usage

    async def run(
        self,
        request: PackageReviewRequest,
        *,
        tenant_id: str,
        user_id: str,
    ) -> dict[str, Any]:
        _, evidence, sources = await self.collect_evidence(request, tenant_id)
        if not evidence:
            raise ValueError("资料包尚未产生可审查Evidence")
        memories = await self.memory.search(
            tenant_id=tenant_id, user_id=user_id, project_id=request.project_id, query=request.question,
        )
        worker_outputs = await asyncio.gather(*(
            self.run_worker(worker, request.question, evidence, memories)
            for worker in ("design", "material", "price")
        ))
        return self.compose(worker_outputs, sources)

    def compose(
        self,
        worker_outputs: Iterable[tuple[WorkerReview, dict[str, Any]]],
        sources: list[dict[str, Any]],
    ) -> dict[str, Any]:
        outputs = list(worker_outputs)
        workers = {review.worker: review for review, _ in outputs}
        usage = {review.worker: worker_usage for review, worker_usage in outputs}
        conflicts = [
            finding.summary
            for review in workers.values()
            for finding in review.findings
            if finding.severity == "conflict" or finding.requires_human
        ]
        lines = ["膜结构工程资料包审查报告"]
        for worker in ("design", "material", "price"):
            lines.append(f"\n{worker}审查：")
            review = workers[worker]
            if review.findings:
                lines.extend(
                    f"- {item.summary}（证据：{', '.join(item.evidence_ids) or '不足'}）"
                    for item in review.findings
                )
            else:
                lines.append("- 未形成可证实结论")
        if conflicts:
            lines.append("\n待人工确认：")
            lines.extend(f"- {item}" for item in conflicts)
        return {
            "review_id": uuid.uuid4().hex,
            "status": "awaiting_approval" if conflicts else "completed",
            "engine": "langchain-multi-agent" if self.provider.metadata.get("mode") == "api" else "deterministic-fake",
            "report": "\n".join(lines),
            "sources": sources[:100],
            "conflicts": conflicts,
            "worker_results": {key: value.model_dump() for key, value in workers.items()},
            "usage": usage,
            "human_review_required": bool(conflicts),
        }


_review_service: PackageReviewService | None = None


def get_package_review_service() -> PackageReviewService:
    global _review_service
    if _review_service is None:
        _review_service = PackageReviewService()
    return _review_service


async def run_package_review(
    request: PackageReviewRequest,
    *,
    tenant_id: str | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    return await get_package_review_service().run(
        request,
        tenant_id=tenant_id or settings.DEFAULT_TENANT_ID,
        user_id=user_id or request.user_id or "temporal-worker",
    )
