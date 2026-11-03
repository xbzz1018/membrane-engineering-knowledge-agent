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
    ):
        from src.agents.review_agents import WORKER_CONFIG, ReviewAgentError

        if not workers or len(set(workers)) != len(workers) or set(workers) - set(WORKER_CONFIG):
            raise ReviewAgentError("领域工具计划无效")
        self.outputs: dict[str, tuple[WorkerReview, dict[str, Any]]] = {}
        self.events: list[dict[str, Any]] = []
        self.tools = []
        for worker in workers:
            self.tools.append(self._build_tool(service, worker, question, evidence, memories))

    def _build_tool(self, service, worker, question, evidence, memories) -> StructuredTool:
        lock = asyncio.Lock()

        async def invoke(focus: str = "") -> str:
            async with lock:
                if worker in self.outputs:
                    self.events.append({"tool": f"review_{worker}", "status": "reused"})
                else:
                    started = time.perf_counter()
                    self.events.append({"tool": f"review_{worker}", "status": "started"})
                    task = question + (f"\n本领域重点：{focus}" if focus else "")
                    review, usage = await service.run_worker(worker, task, evidence, memories)
                    from src.agents.review_agents import ReviewAgentError

                    known = {str(item["evidence_id"]) for item in evidence}
                    cited = {
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
            "design": "调用设计审查子Agent，核验设计方案、节点与版本，返回带Evidence ID的结构化问题。",
            "material": "调用膜材审查子Agent，核验型号、厚度、性能、单位与版本，返回结构化问题。",
            "price": "调用价格审查子Agent，核验历史价格币种、面积单位、日期与来源，返回结构化问题。",
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
    if fake:
        model = ScriptedSupervisorModel(responses=[
            AIMessage(content="", tool_calls=[
                {"name": item.name, "args": {}, "id": f"domain-{index}"}
                for index, item in enumerate(boundary.tools)
            ]),
            AIMessage(content="领域工具执行结束；报告由服务端校验证据后汇总。"),
        ])
    else:
        model = service.provider.langchain_model(enable_thinking=False)
    agent = create_agent(
        model=model,
        tools=boundary.tools,
        system_prompt=get_prompt("review-delegator").text,
        name="review_supervisor_tool_agent",
    )
    result = await agent.ainvoke(
        {"messages": [{
            "role": "user",
            "content": f"审查任务：{question}\n必须完成的领域：{', '.join(plan.workers)}。请调用全部所列领域工具。",
        }]},
        config={"recursion_limit": 12},
    )
    missing = set(plan.workers) - set(boundary.outputs)
    if missing:
        raise ReviewAgentError(f"Supervisor 未完成必要领域工具: {sorted(missing)}")
    messages = result.get("messages", [])
    tool_messages = [item for item in messages if isinstance(item, ToolMessage)]
    if any(item.status == "error" for item in tool_messages):
        raise ReviewAgentError("Supervisor 领域工具调用失败")
    model_messages = [item for item in messages if isinstance(item, AIMessage)]
    return [boundary.outputs[worker] for worker in plan.workers], {
        "mode": "scripted-tool-calling" if fake else "llm-tool-calling",
        "calls": 0 if fake else len(model_messages),
        "input_tokens": sum(int((item.usage_metadata or {}).get("input_tokens", 0)) for item in model_messages),
        "output_tokens": sum(int((item.usage_metadata or {}).get("output_tokens", 0)) for item in model_messages),
        "tool_calls": len(tool_messages),
        "tool_names": [item.name for item in boundary.tools],
        "events": boundary.events,
    }
