"""Validated chat intents; execution privileges are derived by the application."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

ChatIntent = Literal[
    "direct_chat", "knowledge_search", "material_query", "combined_query",
    "review_package", "generate_project", "clarify",
]
QueryRole = Literal["retrieval", "material"]
ExecutionMode = Literal["direct", "single", "parallel", "sequential", "action", "clarify"]

MATERIAL_MODEL = re.compile(r"(?<![A-Z0-9])(?:PTFE|PVDF|PVC|ETFE)(?:[-_ ]?[A-Z]?\d[A-Z0-9_-]*)?(?![A-Z0-9])", re.I)
PRECISE = re.compile(r"型号|规格|参数|厚度|克重|面密度|强度|尺寸|版次|版本|生效|价格|报价|单价|多少钱|specification", re.I)
PROJECT = re.compile(r"公司|企业|我们|本项目|项目资料|历史|去年|今年|文档|文件|附件|原文|案例|合同|资料|20\d{2}|project|document", re.I)
MATERIAL = re.compile(r"膜材|材料|器材|型号|规格|厚度|克重|面密度|PTFE|PVDF|PVC|ETFE|material", re.I)
PRICE = re.compile(r"价格|报价|单价|多少钱|price", re.I)
FOLLOW_UP = re.compile(r"它|其规格|该型号|那个|这个型号|上个项目|上一个|刚才|上述|前面|它们")
DEPENDENCY = re.compile(r"所用|使用的|采用的|对应|其|它|上个|上一个|那个")
EXPLANATION = re.compile(r"什么是|如何|怎么|流程|步骤|原理|解释|介绍|区别|what is|how to", re.I)
NEGATED_ACTION = re.compile(r"(?:不要|别|不必|无需|暂不|先不|不用).{0,8}(?:生成|编写|起草|审查|审核|检查)")
GENERATE = re.compile(r"(?:生成|编写|起草|制作|做).{0,50}(?:项目书|项目方案|初步方案|方案书)")
REVIEW = re.compile(r"(?:审查|审核|检查|复核).{0,40}(?:资料|文件|文档|附件|资料包)")


class ChatRoutingDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: ChatIntent
    retrieval_query: str = Field(default="", max_length=4000)
    material_query: str = Field(default="", max_length=4000)
    material_depends_on_retrieval: StrictBool = False
    clarification_question: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def valid_dependencies(self):
        if self.material_depends_on_retrieval and self.intent != "combined_query":
            raise ValueError("only combined_query may declare a retrieval dependency")
        if self.intent == "clarify" and not (self.clarification_question or "").strip():
            raise ValueError("clarify requires a question")
        return self

    @property
    def roles(self) -> list[QueryRole]:
        return {
            "knowledge_search": ["retrieval"], "material_query": ["material"],
            "combined_query": ["retrieval", "material"],
        }.get(self.intent, [])

    @property
    def execution_mode(self) -> ExecutionMode:
        if self.intent == "combined_query":
            return "sequential" if self.material_depends_on_retrieval else "parallel"
        if self.roles:
            return "single"
        if self.intent in {"review_package", "generate_project"}:
            return "action"
        return "clarify" if self.intent == "clarify" else "direct"


class ChatRoutingInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: ChatIntent
    execution_mode: ExecutionMode
    agents_planned: list[str] = Field(default_factory=list)
    needs_review: bool = False
    decision_source: Literal["rules", "model", "server_guard"]
    outcomes: dict[str, Literal["ok", "no_results", "failed", "timeout", "blocked"]] = Field(default_factory=dict)
    action_status: Literal["not_started", "existing_api_required", "not_implemented", "accepted"] | None = None


def rule_decision(query: str, history: list[dict] | None = None) -> ChatRoutingDecision:
    """Conservative offline classifier and minimum evidence requirements."""
    history = history or []
    text = query.strip()
    # Exclude a negated operation clause from topic detection. Keep its text
    # out of authorization, but preserve the original request in query inputs.
    text = re.sub(
        r"(?:不要|别|不必|无需|暂不|先不|不用)(?:生成|编写|起草|审查|审核|检查)[^，,；;。]{0,30}[，,；;。]",
        "", text,
    ).strip()
    if not NEGATED_ACTION.search(text) and not EXPLANATION.search(text):
        if GENERATE.search(text):
            return ChatRoutingDecision(intent="generate_project")
        if REVIEW.search(text):
            return ChatRoutingDecision(intent="review_package")
    previous = next((item["content"] for item in reversed(history) if item["role"] == "user"), "")
    contextual = text
    if FOLLOW_UP.search(text):
        if not previous:
            return ChatRoutingDecision(intent="clarify", clarification_question="请说明具体项目、资料或材料型号。")
        contextual = previous + "\n追问：" + text
    project = bool(PROJECT.search(contextual))
    material = bool(MATERIAL.search(contextual))
    precise = bool(PRECISE.search(contextual))
    exact_model = bool(re.search(r"(?:PTFE|PVDF|PVC|ETFE)[-_ ]?[A-Z]?\d", contextual, re.I))
    if (GENERATE.search(text) or REVIEW.search(text)) and EXPLANATION.search(text):
        # Asking how an operation works must not submit that operation.
        return ChatRoutingDecision(intent="direct_chat")
    if PRICE.search(contextual):
        intent = "knowledge_search"
    elif material and project:
        intent = "combined_query"
    elif material and (precise or exact_model):
        intent = "material_query"
    elif project or precise:
        intent = "knowledge_search"
    elif EXPLANATION.search(text) or re.fullmatch(r"你好[！!。 .]*|您好[！!。 .]*|谢谢[！!。 .]*|hi[!. ]*|hello[!. ]*", text, re.I):
        intent = "direct_chat"
    else:
        intent = "knowledge_search"
    return ChatRoutingDecision(
        intent=intent,
        retrieval_query=(previous + "\n追问：" if FOLLOW_UP.search(text) and previous else "") + query,
        material_query=(previous + "\n追问：" if FOLLOW_UP.search(text) and previous else "") + query,
        material_depends_on_retrieval=intent == "combined_query" and bool(DEPENDENCY.search(contextual)),
    )


def enforce_route(
    decision: ChatRoutingDecision, query: str, history: list[dict] | None = None,
) -> tuple[ChatRoutingDecision, bool]:
    """Fail closed for project facts; never trust model-selected privileges."""
    required = rule_decision(query, history)
    if required.intent in {"generate_project", "review_package", "clarify"}:
        return required, required != decision
    # Explanatory or negated text is not authorization to start a workflow.
    if decision.intent in {"generate_project", "review_package"}:
        return required, True
    if required.roles and (
        not set(required.roles) <= set(decision.roles)
        or (required.material_depends_on_retrieval and not decision.material_depends_on_retrieval)
    ):
        return required, True
    # The original query and server-scoped previous user message remain present;
    # a model rewrite cannot drop a requested model, date or revision.
    updated = decision.model_copy(update={
        "retrieval_query": required.retrieval_query or query,
        "material_query": required.material_query or query,
        "material_depends_on_retrieval": decision.intent == "combined_query"
        and required.material_depends_on_retrieval,
    })
    return updated, updated.material_depends_on_retrieval != decision.material_depends_on_retrieval
