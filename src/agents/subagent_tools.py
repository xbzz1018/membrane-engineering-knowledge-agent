"""Expose request-scoped domain Agents as LangChain tools to a Supervisor."""

from __future__ import annotations

import asyncio
import json
import time
from typing import TYPE_CHECKING, Any

from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict, Field

from src.agents.prompts import get_prompt

if TYPE_CHECKING:
    from src.agents.review_agents import PackageReviewService, ReviewPlan, WorkerReview


class DomainReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    focus: str = Field(default="", max_length=2000, description="本领域需重点核验的问题；资料范围由服务端绑定。")


class ScriptedSupervisorModel(FakeMessagesListChatModel):
    """Explicit offline demo model; still exercises real LangChain tool dispatch."""

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        return self


class DomainAgentTools:
    """Evidence, identity scope and memory come only from the authorized caller."""

    def __init__(
        self,
        service: PackageReviewService,
        workers: list[str],
        question: str,
        evidence: list[dict[str, Any]],
        memories: list[str],
        upstream_results: list[dict[str, Any]] | None = None,
    ):
        from src.agents.review_agents import WORKER_CONFIG, ReviewAgentError

        if not workers or len(set(workers)) != len(workers) or set(workers) - set(WORKER_CONFIG):
            raise ReviewAgentError("领域工具计划无效")
        self.outputs: dict[str, tuple[WorkerReview, dict[str, Any]]] = {}
        self.upstream_results = upstream_results or []
        self.events: list[dict[str, Any]] = []
        self.tools = []
        for worker in workers:
            self.tools.append(self._build_tool(service, worker, question, evidence, memories))

    def _build_tool(self, service, worker, question, evidence, memories) -> StructuredTool:
        lock = asyncio.Lock()

        async def invoke(focus: str = "") -> str:
            from src.agents.review_agents import ReviewAgentError

            async with lock:
                if worker in self.outputs:
                    self.events.append({"tool": f"review_{worker}", "status": "reused"})
                else:
                    started = time.perf_counter()
                    self.events.append({"tool": f"review_{worker}", "status": "started"})
                    task = question + (f"\n本领域重点：{focus}" if focus else "")
                    if worker == "review":
                        from src.agents.review_agents import WorkerReview

                        upstream = {item["worker"]: item for item in self.upstream_results}
                        upstream.update({name: value[0].model_dump() for name, value in self.outputs.items()})
                        if not {"retrieval", "material"} <= upstream.keys():
                            raise ReviewAgentError("综合审查须等待检索和材料结果")
                        known = {str(item["evidence_id"]) for item in evidence}
                        summaries = []
                        for name in ("retrieval", "material"):
                            result = WorkerReview.model_validate(upstream[name])
                            cited = set(result.selected_evidence_ids) | {
                                value for issue in result.findings for value in issue.evidence_ids
                            }
                            # Coverage repairs may pass only a subset. Filter
                            # advisory references; raw snapshot remains authority.
                            summaries.append({
                                "worker": name, "summary_only": True,
                                "selected_evidence_ids": [value for value in result.selected_evidence_ids if value in known][:20],
                                "finding_count": len(result.findings),
                                "findings": [{"summary": issue.summary[:300], "evidence_ids": issue.evidence_ids}
                                             for issue in result.findings if set(issue.evidence_ids) <= known][:20],
                                "has_out_of_batch_references": bool(cited - known),
                            })
                        # Upstream is a proposal, never additional source evidence.
                        task += "\n上游结果（须以原始Evidence核验，不能视为事实）：" + json.dumps(
                            summaries, ensure_ascii=False,
                        )
                    review, usage = await service.run_worker(worker, task, evidence, memories)

                    known = {str(item["evidence_id"]) for item in evidence}
                    cited = set(review.selected_evidence_ids) | {
                        item for finding in review.findings for item in finding.evidence_ids
                    } | set(review.processed_evidence_ids) | set(review.skipped_evidence_ids)
                    if review.worker != worker or cited - known:
                        raise ReviewAgentError("领域工具返回越界的领域或证据")
                    self.outputs[worker] = (review, usage)
                    self.events.append({
                        "tool": f"review_{worker}",
                        "status": "completed",
                        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                        "finding_count": len(review.findings),
                    })
                review, _usage = self.outputs[worker]
                return json.dumps(review.model_dump(), ensure_ascii=False)

        descriptions = {
            "retrieval": "调用资料检索子Agent，在冻结包内调用证据查询工具，整理出处和选中片段；不作工程结论。",
            "material": "调用材料子Agent核验型号、参数、单位和适用版本，返回带证据的核验结果。",
            "review": "在检索与材料结果齐备后调用综合审查子Agent，核查原文、缺项和跨文档冲突。",
        }
        return StructuredTool.from_function(
            coroutine=invoke,
            name=f"review_{worker}",
            description=descriptions[worker],
            args_schema=DomainReviewInput,
        )


async def run_subagents_as_tools(
    service: PackageReviewService,
    plan: ReviewPlan,
    question: str,
    evidence: list[dict[str, Any]],
    memories: list[str],
) -> tuple[list[tuple[WorkerReview, dict[str, Any]]], dict[str, Any]]:
    from src.agents.review_agents import ReviewAgentError

    boundary = DomainAgentTools(service, plan.workers, question, evidence, memories)
    fake = service.provider.metadata.get("mode") != "api"
    all_messages = []
    # Stages are enforced by the application; the model cannot bypass dependencies.
    stages = [[worker for worker in plan.workers if worker != "review"]]
    if "review" in plan.workers:
        stages.append(["review"])
    for names in (stage for stage in stages if stage):
        tools = [tool for tool in boundary.tools if tool.name in {f"review_{name}" for name in names}]
        if fake:
            model = ScriptedSupervisorModel(responses=[
                AIMessage(content="", tool_calls=[
                    {"name": item.name, "args": {}, "id": f"domain-{item.name}"}
                    for item in tools
                ]),
                AIMessage(content="本阶段工具已完成。"),
            ])
        else:
            model = service.provider.langchain_model(enable_thinking=False)
        agent = create_agent(
            model=model, tools=tools, system_prompt=get_prompt("review-delegator").text,
            name="review_supervisor_tool_agent",
        )
        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": (
                f"审查任务：{question}\n本阶段必须完成的领域：{', '.join(names)}。请调用全部所列领域工具。"
            )}]}, config={"recursion_limit": 12},
        )
        missing = set(names) - set(boundary.outputs)
        if missing:
            raise ReviewAgentError(f"Supervisor 未完成必要领域工具: {sorted(missing)}")
        all_messages.extend(result.get("messages", []))
    tool_messages = [item for item in all_messages if isinstance(item, ToolMessage)]
    if any(item.status == "error" for item in tool_messages):
        raise ReviewAgentError("Supervisor 领域工具调用失败")
    model_messages = [item for item in all_messages if isinstance(item, AIMessage)]
    return [boundary.outputs[worker] for worker in plan.workers], {
        "mode": "scripted-tool-calling" if fake else "llm-tool-calling",
        "provider": service.provider.metadata.get("provider"),
        "model": service.provider.metadata.get("model"), "model_tier": "strong",
        "execution_graph": "retrieval || material -> review",
        "calls": 0 if fake else len(model_messages),
        "input_tokens": sum(int((item.usage_metadata or {}).get("input_tokens", 0)) for item in model_messages),
        "output_tokens": sum(int((item.usage_metadata or {}).get("output_tokens", 0)) for item in model_messages),
        "tool_calls": len(tool_messages), "tool_names": [item.name for item in boundary.tools],
        "events": boundary.events,
    }
