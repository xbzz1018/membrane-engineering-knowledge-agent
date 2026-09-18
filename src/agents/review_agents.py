from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from collections.abc import Iterable
from typing import Any, Literal

from langchain.agents import create_agent
from langchain_core.messages import AIMessage
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.agents.prompts import get_prompt
from src.application.memory import get_memory_service
from src.core.config import get_settings
from src.core.observability import span
from src.domain.review_rules import validate_evidence
from src.domain.schemas import IssueEvidenceRef, PackageReviewRequest, ReviewIssue, SourceRef
from src.infrastructure.database import EngineeringStorage, storage
from src.infrastructure.model_provider import ModelProvider, get_review_model_provider

ReviewFinding = ReviewIssue


class WorkerReview(BaseModel):
    model_config = ConfigDict(title="领域智能体审查结果")
    worker: Literal["design", "material", "price"]
    findings: list[ReviewIssue] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    processed_evidence_ids: list[str] = Field(default_factory=list)
    skipped_evidence_ids: list[str] = Field(default_factory=list)
    skipped_reasons: dict[str, str] = Field(default_factory=dict)


class ReviewPlan(BaseModel):
    model_config = ConfigDict(title="资料审查计划")
    workers: list[Literal["design", "material", "price"]] = Field(min_length=1, max_length=3)
    rationale: str = Field(default="", max_length=1000)
    review_mode: Literal["full", "focused"] = "full"


class ReviewAgentError(RuntimeError):
    pass


WORKER_CONFIG = {
    "design": {
        "keywords": ("设计", "方案", "结构", "场景", "节点", "版本"),
        "prompt": get_prompt("design-review").text,
    },
    "material": {
        "keywords": ("膜材", "材料", "型号", "规格", "厚度", "重量", "透光", "抗拉", "单位"),
        "prompt": get_prompt("material-review").text,
    },
    "price": {
        "keywords": ("价格", "成本", "报价", "币种", "单价", "元/", "日期", "区域"),
        "prompt": get_prompt("price-review").text,
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
        self.provider = provider or get_review_model_provider()
        self.memory = get_memory_service(store)

    async def plan_review(
        self,
        question: str,
        evidence: list[dict[str, Any]],
        review_mode: Literal["full", "focused"] = "full",
    ) -> tuple[ReviewPlan, dict[str, Any]]:
        """Use one restricted LLM supervisor to select domain workers."""
        all_workers = ["design", "material", "price"]
        if (
            self.provider.metadata.get("mode") != "api"
            or not get_settings().REVIEW_SUPERVISOR_ENABLED
        ):
            if review_mode == "full":
                selected_workers = all_workers
            else:
                haystack = question.lower()
                selected_workers = [
                    worker
                    for worker, config in WORKER_CONFIG.items()
                    if any(keyword.lower() in haystack for keyword in config["keywords"])
                ] or all_workers
            return ReviewPlan(
                workers=selected_workers,
                rationale="Fake/disabled mode uses deterministic domain selection.",
                review_mode=review_mode,
            ), {
                "enabled": False,
                "mode": "deterministic",
                "review_mode": review_mode,
                "workers": selected_workers,
                "calls": 0,
                "input_tokens": 0,
                "output_tokens": 0,
            }

        catalog = [
            {
                "evidence_id": item["evidence_id"],
                "filename": item["filename"],
                "location": item["location"],
                "text": item["text"][:500],
            }
            for item in evidence[:80]
        ]
        agent = create_agent(
            model=self.provider.langchain_model(json_mode=True, enable_thinking=False),
            tools=[],
            system_prompt=(
                get_prompt("review-supervisor").text
                +
                "可选 Worker 只有 design、material、price；至少选择一个。"
                "涉及方案/结构时选 design，涉及膜材/规格时选 material，涉及价格/成本时选 price；"
                "问题要求比较完整资料或无法明确归类时选择全部三个。"
                "只输出 JSON：{workers:[...], rationale: \"...\", review_mode: \"full或focused\"}。"
            ),
            name="review_supervisor_agent",
        )
        prompt = (
            f"审查问题：{question}\n"
            f"审查模式：{review_mode}\n"
            f"证据目录：{json.dumps(catalog, ensure_ascii=False)}\n"
            "请输出审查计划 JSON。"
        )
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                result = await agent.ainvoke({"messages": [{"role": "user", "content": prompt}]})
                messages = result.get("messages", [])
                final_message = next(
                    (message for message in reversed(messages) if isinstance(message, AIMessage)),
                    None,
                )
                content = final_message.content if final_message is not None else ""
                if not isinstance(content, str) or not content.strip():
                    raise ReviewAgentError("ReviewSupervisorAgent 返回空计划")
                metadata = getattr(final_message, "usage_metadata", None) or {}
                response_metadata = getattr(final_message, "response_metadata", None) or {}
                normalized = content.strip()
                if normalized.startswith("```"):
                    normalized = normalized.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
                plan = ReviewPlan.model_validate_json(normalized)
                workers = list(dict.fromkeys(plan.workers))
                if review_mode == "full":
                    workers = all_workers
                plan.workers = workers
                plan.review_mode = review_mode
                if not workers:
                    raise ReviewAgentError("ReviewSupervisorAgent 未选择 Worker")
                return plan, {
                    "enabled": True,
                    "mode": "llm",
                    "review_mode": review_mode,
                    "provider": self.provider.metadata.get("provider"),
                    "model": self.provider.metadata.get("model"),
                    "workers": workers,
                    "calls": 1,
                    "rationale": plan.rationale,
                    "input_tokens": int(metadata.get("input_tokens", 0) or 0),
                    "output_tokens": int(metadata.get("output_tokens", 0) or 0),
                    "finish_reason": str(response_metadata.get("finish_reason", "")),
                    "attempts": attempt + 1,
                }
            except (ValidationError, ReviewAgentError, ValueError) as exc:
                last_error = exc
                if attempt == 0:
                    prompt += "\n上次输出无效，请严格按ReviewPlan字段输出JSON。"
        raise ReviewAgentError("ReviewSupervisorAgent 审查计划无效") from last_error

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
    def _matching_workers(item: dict[str, Any]) -> set[str]:
        text = str(item.get("text", "")).lower()
        return {
            worker
            for worker, config in WORKER_CONFIG.items()
            if any(keyword.lower() in text for keyword in config["keywords"])
        }

    @classmethod
    def route_evidence(
        cls,
        workers: Iterable[str],
        evidence: list[dict[str, Any]],
    ) -> dict[str, list[dict[str, Any]]]:
        """Route Evidence as multi-label data and share unclassified units."""
        selected_workers = list(dict.fromkeys(worker for worker in workers if worker in WORKER_CONFIG))
        routes = {worker: [] for worker in selected_workers}
        for item in evidence:
            matched_workers = cls._matching_workers(item)
            targets = [worker for worker in selected_workers if worker in matched_workers]
            if not matched_workers:
                targets = selected_workers
            for worker in targets:
                routes[worker].append(item)
        for worker in selected_workers:
            if not routes[worker]:
                routes[worker] = list(evidence)
        return routes

    @classmethod
    def _worker_evidence(cls, worker: str, evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return cls.route_evidence([worker], evidence).get(worker, [])

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
                issue_id=f"fake-{worker}-{index}",
                domain=worker,
                issue_type="deterministic_conflict",
                summary=conflict,
                severity="conflict",
                evidence_ids=list(evidence_map)[:4],
                recommendation="核对对应文件和业务版本后再形成结论。",
                status="pending_human",
                requires_human=True,
            ) for index, conflict in enumerate(_conflicts(text), 1)]
            if not findings and batch:
                findings.append(ReviewFinding(
                    issue_id=f"fake-{worker}-complete",
                    domain=worker,
                    issue_type="review_completed",
                    summary=f"{worker}审查已完成，未发现确定性冲突",
                    evidence_ids=list(evidence_map)[:2],
                ))
            return WorkerReview(
                worker=worker,
                findings=findings,
                processed_evidence_ids=list(evidence_map),
            ), {"provider": "fake", "input_tokens": sum(item["token_count"] for item in batch)}

        agent = create_agent(
            model=self.provider.langchain_model(json_mode=True, enable_thinking=False),
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
                    for index, finding in enumerate(structured.findings, 1):
                        if not finding.summary.strip():
                            raise ReviewAgentError(f"{worker} Worker问题摘要为空")
                        finding.domain = worker
                        if finding.evidence_refs:
                            ref_ids = {ref.evidence_id for ref in finding.evidence_refs}
                            finding.evidence_ids = list(dict.fromkeys([*finding.evidence_ids, *ref_ids]))
                        if not finding.issue_id:
                            digest = hashlib.sha256(
                                f"{worker}|{finding.summary}|{','.join(finding.evidence_ids)}".encode()
                            ).hexdigest()[:16]
                            finding.issue_id = f"{worker}-{digest}"
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
        for finding in structured.findings:
            finding.evidence_refs = [
                IssueEvidenceRef(
                    evidence_id=evidence_id,
                    filename=str(evidence_map[evidence_id].get("filename", "")),
                    location=str(evidence_map[evidence_id].get("location", "")),
                    version=str(evidence_map[evidence_id].get("version", "")),
                )
                for evidence_id in finding.evidence_ids
            ]
        invalid_status_ids = (
            set(structured.processed_evidence_ids) | set(structured.skipped_evidence_ids)
        ) - set(evidence_map)
        if invalid_status_ids:
            raise ReviewAgentError(f"{worker} Worker返回无效Evidence状态: {sorted(invalid_status_ids)}")
        skipped = set(structured.skipped_evidence_ids)
        structured.processed_evidence_ids = [item for item in evidence_map if item not in skipped]
        structured.skipped_evidence_ids = [item for item in evidence_map if item in skipped]
        structured.skipped_reasons = {
            item: structured.skipped_reasons.get(item, "智能体明确标记为未使用")
            for item in structured.skipped_evidence_ids
        }
        usage["finish_reason"] = finish_reasons[-1] if finish_reasons else ""
        return structured, usage

    @staticmethod
    def _reduce_worker(worker: str, parts: Iterable[WorkerReview]) -> WorkerReview:
        findings: list[ReviewFinding] = []
        uncertainties: list[str] = []
        processed: list[str] = []
        skipped: list[str] = []
        skipped_reasons: dict[str, str] = {}
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
            skipped_reasons.update(part.skipped_reasons)
        skipped = [item for item in skipped if item not in processed]
        skipped_reasons = {item: skipped_reasons[item] for item in skipped if item in skipped_reasons}
        return WorkerReview(
            worker=worker,
            findings=findings,
            uncertainties=uncertainties,
            processed_evidence_ids=processed,
            skipped_evidence_ids=skipped,
            skipped_reasons=skipped_reasons,
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

    async def repair_evidence_coverage(
        self,
        workers: Iterable[str],
        question: str,
        evidence: list[dict[str, Any]],
        memories: list[str],
        worker_outputs: Iterable[tuple[WorkerReview, dict[str, Any]]],
    ) -> tuple[list[tuple[WorkerReview, dict[str, Any]]], dict[str, Any]]:
        """Run one bounded repair pass for Evidence skipped by every routed Worker."""
        selected_workers = list(dict.fromkeys(worker for worker in workers if worker in WORKER_CONFIG))
        outputs = list(worker_outputs)
        routes = self.route_evidence(selected_workers, evidence)
        expected_ids = {
            str(item["evidence_id"])
            for worker in selected_workers
            for item in routes.get(worker, [])
        }
        processed_ids = {
            evidence_id
            for review, _ in outputs
            for evidence_id in review.processed_evidence_ids
        }
        uncovered_ids = sorted(expected_ids - processed_ids)
        coverage = {
            "attempted": bool(uncovered_ids),
            "passes": 1 if uncovered_ids else 0,
            "expected_count": len(expected_ids),
            "initial_uncovered_ids": uncovered_ids,
            "remaining_uncovered_ids": [],
            "rerouted_workers": [],
        }
        if not uncovered_ids:
            return outputs, coverage

        uncovered = [item for item in evidence if str(item["evidence_id"]) in set(uncovered_ids)]
        repair_outputs = await asyncio.gather(*(
            self.run_worker(worker, question, uncovered, memories)
            for worker in selected_workers
        ))
        coverage["rerouted_workers"] = selected_workers

        existing = {review.worker: (review, usage) for review, usage in outputs}
        for repair_review, repair_usage in repair_outputs:
            current_review, current_usage = existing[repair_review.worker]
            merged_review = self._reduce_worker(repair_review.worker, [current_review, repair_review])
            merged_usage = {
                "calls": int(current_usage.get("calls", 0)) + int(repair_usage.get("calls", 0)),
                "input_tokens": (
                    int(current_usage.get("input_tokens", 0))
                    + int(repair_usage.get("input_tokens", 0))
                ),
                "output_tokens": (
                    int(current_usage.get("output_tokens", 0))
                    + int(repair_usage.get("output_tokens", 0))
                ),
                "finish_reasons": [
                    *list(current_usage.get("finish_reasons", [])),
                    *list(repair_usage.get("finish_reasons", [])),
                ],
                "coverage_repair_calls": int(repair_usage.get("calls", 0)),
            }
            existing[repair_review.worker] = (merged_review, merged_usage)

        repaired = [existing[worker] for worker in selected_workers]
        repaired_processed = {
            evidence_id
            for review, _ in repaired
            for evidence_id in review.processed_evidence_ids
        }
        coverage["remaining_uncovered_ids"] = sorted(expected_ids - repaired_processed)
        return repaired, coverage

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
        plan, supervisor_usage = await self.plan_review(request.question, evidence, request.review_mode)
        rule_issues = validate_evidence(evidence, plan.workers)
        worker_outputs = await asyncio.gather(*(
            self.run_worker(worker, request.question, evidence, memories)
            for worker in plan.workers
        ))
        worker_outputs, coverage = await self.repair_evidence_coverage(
            plan.workers,
            request.question,
            evidence,
            memories,
            worker_outputs,
        )
        return self.compose(
            worker_outputs,
            sources,
            plan=plan,
            supervisor_usage=supervisor_usage,
            rule_issues=rule_issues,
            evidence=evidence,
            coverage=coverage,
        )

    def compose(
        self,
        worker_outputs: Iterable[tuple[WorkerReview, dict[str, Any]]],
        sources: list[dict[str, Any]],
        *,
        plan: ReviewPlan | None = None,
        supervisor_usage: dict[str, Any] | None = None,
        rule_issues: list[ReviewIssue] | None = None,
        evidence: list[dict[str, Any]] | None = None,
        coverage: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        outputs = list(worker_outputs)
        workers = {review.worker: review for review, _ in outputs}
        if rule_issues is None and evidence is not None:
            rule_issues = validate_evidence(
                evidence,
                plan.workers if plan else workers.keys(),
            )
        for issue in rule_issues or []:
            if issue.domain in workers and issue.issue_id not in {item.issue_id for item in workers[issue.domain].findings}:
                workers[issue.domain].findings.insert(0, issue)
        remaining_uncovered = list((coverage or {}).get("remaining_uncovered_ids", []))
        if remaining_uncovered:
            rule_issues = [
                *(rule_issues or []),
                ReviewIssue(
                    issue_id=(
                        "coverage-"
                        + hashlib.sha256("|".join(remaining_uncovered).encode()).hexdigest()[:16]
                    ),
                    domain="cross_domain",
                    issue_type="evidence_coverage_gap",
                    summary="二次领域路由后仍有Evidence未被处理",
                    severity="warning",
                    evidence_ids=remaining_uncovered,
                    recommendation="由审核人确认Evidence领域，补充规则后重新发起审查。",
                    status="pending_human",
                    requires_human=True,
                ),
            ]
        evidence_by_id = {str(item["evidence_id"]): item for item in (evidence or [])}

        def hydrate_refs(issue: ReviewIssue) -> None:
            issue.evidence_refs = [
                IssueEvidenceRef(
                    evidence_id=evidence_id,
                    filename=str(evidence_by_id[evidence_id].get("filename", "")),
                    location=str(evidence_by_id[evidence_id].get("location", "")),
                    version=str(evidence_by_id[evidence_id].get("version", "")),
                )
                for evidence_id in issue.evidence_ids
                if evidence_id in evidence_by_id
            ]

        for issue in (rule_issues or []):
            hydrate_refs(issue)
        for review in workers.values():
            for issue in review.findings:
                hydrate_refs(issue)
        usage = {review.worker: worker_usage for review, worker_usage in outputs}
        usage["supervisor"] = supervisor_usage or {
            "enabled": False,
            "mode": "deterministic",
            "workers": list(workers),
            "calls": 0,
        }
        usage["coverage"] = coverage or {
            "attempted": False,
            "passes": 0,
            "expected_count": 0,
            "initial_uncovered_ids": [],
            "remaining_uncovered_ids": [],
            "rerouted_workers": [],
        }
        issues: list[ReviewIssue] = []
        seen_issues: set[str] = set()
        for issue in (rule_issues or []):
            if issue.issue_id not in seen_issues:
                issues.append(issue)
                seen_issues.add(issue.issue_id)
        for review in workers.values():
            for finding in review.findings:
                if finding.issue_id not in seen_issues:
                    issues.append(finding)
                    seen_issues.add(finding.issue_id)
        conflicts = [
            issue.summary
            for issue in issues
            if issue.severity == "conflict" or issue.requires_human
        ]
        lines = ["膜结构工程资料包审查报告"]
        for worker in ("design", "material", "price"):
            if worker not in workers:
                continue
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
            "engine": "langchain-supervisor-multi-agent" if self.provider.metadata.get("mode") == "api" else "deterministic-fake",
            "report": "\n".join(lines),
            "sources": sources[:100],
            "conflicts": conflicts,
            "issues": [issue.model_dump() for issue in issues],
            "worker_results": {key: value.model_dump() for key, value in workers.items()},
            "agents_used": [
                "ReviewSupervisorAgent",
                *[f"{worker.title()}ReviewAgent" for worker in workers],
            ],
            "orchestrator": "ReviewSupervisorAgent",
            "review_plan": {
                "workers": list(plan.workers) if plan else list(workers),
                "rationale": plan.rationale if plan else "",
                "review_mode": plan.review_mode if plan else "full",
                "planner_mode": (supervisor_usage or {}).get("mode", "deterministic"),
                "coverage": coverage or {},
            },
            "usage": usage,
            "human_review_required": bool(conflicts),
            "lock_version": 1,
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
