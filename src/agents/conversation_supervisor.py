"""Intent routing around existing knowledge tools; package review stays separate."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.agents.knowledge_agent import AgentProtocolError, KnowledgeAgent
from src.agents.prompts import get_prompt
from src.application.authorization import ProjectAuthorizationService
from src.core.config import get_settings
from src.core.security import Principal
from src.domain.chat_routing import (
    MATERIAL_MODEL,
    PRICE,
    ChatRoutingDecision,
    ChatRoutingInfo,
    enforce_route,
    rule_decision,
)
from src.infrastructure.model_provider import ProviderRequestError, get_role_model_provider

ROLE_NAMES = {"retrieval": "RetrievalAgent", "material": "MaterialAgent"}


def scoped_session(principal: Principal, project_id: str, session_id: str) -> str:
    value = json.dumps([principal.tenant_id, principal.user_id, project_id, session_id], ensure_ascii=False)
    return "chat:" + hashlib.sha256(value.encode()).hexdigest()


def token_usage(messages: list[Any]) -> dict[str, int]:
    return {
        key: sum(int((item.usage_metadata or {}).get(key, 0)) for item in messages if isinstance(item, AIMessage))
        for key in ("input_tokens", "output_tokens")
    }


class SupervisorRouter:
    def __init__(self, provider):
        self.provider = provider

    async def route(self, query: str, history: list[dict]) -> tuple[ChatRoutingDecision, str, dict]:
        if self.provider.metadata.get("mode") != "api":
            return rule_decision(query, history), "rules", {"input_tokens": 0, "output_tokens": 0}
        prompt = get_prompt("conversation-router")
        model = create_agent(
            model=self.provider.langchain_model(json_mode=True, enable_thinking=False),
            tools=[], system_prompt=prompt.text, name="conversation_router",
        )
        content = json.dumps({"message": query, "history_context_only": history}, ensure_ascii=False)
        usage = {"input_tokens": 0, "output_tokens": 0}
        for attempt in range(2):
            try:
                result = await model.ainvoke(
                    {"messages": [{"role": "user", "content": content}]}, config={"recursion_limit": 4},
                )
            except Exception as exc:
                raise ProviderRequestError(f"Conversation router request failed ({type(exc).__name__})") from exc
            messages = result.get("messages", [])
            for key, value in token_usage(messages).items():
                usage[key] += value
            try:
                answer, _last_usage, _finish = KnowledgeAgent._answer(messages)
                normalized = answer.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
                decision = ChatRoutingDecision.model_validate_json(normalized)
                decision, guarded = enforce_route(decision, query, history)
                return decision, "server_guard" if guarded else "model", usage
            except (ValidationError, AgentProtocolError):
                if attempt == 0:
                    content += "\n上次格式无效。请只返回符合约定字段与枚举的JSON，不输出其他文字。"
        raise AgentProtocolError("Supervisor returned invalid routing JSON after two attempts")


class QueryAgentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    focus: str = Field(default="", max_length=4000)


class ConversationSupervisor:
    """Plan in the model, dispatch allowlisted tools in the server, audit once."""

    def __init__(self, knowledge: KnowledgeAgent):
        self.knowledge = knowledge
        self.store = knowledge.store
        self.authorization = ProjectAuthorizationService(self.store)
        self.router = SupervisorRouter(self._provider("supervisor"))
        self.query_timeout = get_settings().CHAT_QUERY_TIMEOUT_SECONDS

    def _provider(self, role: str):
        if get_settings().ROLE_MODEL_ROUTING_ENABLED:
            return get_role_model_provider(role)
        return self.knowledge.provider

    async def _direct(self, query: str) -> dict:
        provider = self._provider("supervisor")
        if provider.metadata.get("mode") != "api":
            if "膜结构" in query:
                answer = "膜结构利用张拉膜面与支承体系形成空间覆盖。具体项目的材料、尺寸和性能应根据项目资料核对。"
            elif re.search(r"你好|您好|hi|hello", query, re.I):
                answer = "你好，可以提问膜结构概念，也可以查询当前项目资料或材料规格。"
            else:
                answer = "当前是Fake离线演示，已进入直接问答分支；接入API模型后可回答通用知识问题。"
            usage = {"input_tokens": 0, "output_tokens": 0}
        else:
            model = create_agent(
                model=provider.langchain_model(), tools=[],
                system_prompt=get_prompt("general-knowledge").text, name="general_knowledge_agent",
            )
            try:
                result = await model.ainvoke({"messages": [{"role": "user", "content": query}]})
            except Exception as exc:
                raise ProviderRequestError(f"General knowledge request failed ({type(exc).__name__})") from exc
            answer, _last_usage, _finish = KnowledgeAgent._answer(result.get("messages", []))
            if re.search(r"\[[^\[\]]+\]", answer):
                raise AgentProtocolError("Direct chat must not invent evidence citations")
            usage = token_usage(result.get("messages", []))
        return {
            "answer": "通用知识说明：" + answer, "answer_origin": "general_knowledge",
            "sources": [], "uncertainties": [],
            "usage": {**provider.metadata, "model_usage": usage, "agents_used": ["ConversationSupervisor"]},
        }

    async def _query_role(self, role: str, principal: Principal, project_id: str,
                          query: str, memories: list[str]) -> dict:
        provider = self._provider(role)
        if provider.metadata.get("mode") == "api":
            result = await self.knowledge._invoke_api(
                principal, project_id, "role-query", query, memories, role=role, provider=provider,
            )
        else:
            # Explicit Fake uses actual authorized query tools, without network LLMs.
            tools = {item.name: item for item in self.knowledge._tools(principal, project_id, role)}
            name = "query_material_specs" if role == "material" else (
                "query_price_records" if PRICE.search(query) else "search_project_documents"
            )
            payload = json.loads(await tools[name].ainvoke({"query": query}))
            if payload.get("error"):
                raise AgentProtocolError("Knowledge query tool failed")
            requested_model = re.search(r"(?:PTFE|PVDF|PVC|ETFE)(?:[-_][A-Z0-9]+)+", query, re.I)
            from src.domain.project_plan import material_matches

            matches_requested_model = not requested_model or any(
                material_matches(requested_model.group(), item.get("text", ""))
                for item in payload.get("evidence", [])
            )
            if role == "material" and (not payload.get("evidence") or not matches_requested_model):
                # Uploaded specifications are distinct from the structured
                # catalog. Query them only when the catalog has no result.
                payload = json.loads(await tools["search_project_documents"].ainvoke({"query": query}))
                if payload.get("error"):
                    raise AgentProtocolError("Document query tool failed")
            evidence = payload.get("evidence", [])
            answer = "\n".join(f"{item['text']} [{item['evidence_id']}]" for item in evidence)
            result = {
                "answer": answer, "sources": payload.get("sources", []),
                "uncertainties": payload.get("uncertainties", []), "_tool_evidence": evidence,
                "usage": {**provider.metadata, "model_usage": {"input_tokens": 0, "output_tokens": 0},
                          "agents_used": [ROLE_NAMES[role]]},
            }
        # No evidence is a data outcome, not permission for a free-form model answer.
        if not result.get("_tool_evidence"):
            result["answer"] = "未找到可引用资料，不能确认相关项目事实或材料参数。"
            result["outcome"] = "no_results"
        else:
            result["outcome"] = "ok"
        return result

    def _query_tools(self, principal: Principal, project_id: str, decision: ChatRoutingDecision,
                     memories: list[str]) -> dict[str, StructuredTool]:
        def build(role: str) -> StructuredTool:
            async def invoke(focus: str = "") -> dict:
                query = decision.retrieval_query if role == "retrieval" else decision.material_query
                # focus may narrow a query but cannot replace its server-bound scope/query.
                if focus:
                    query += "\n已从原始资料解析的材料型号：" + focus
                return await self._query_role(role, principal, project_id, query, memories)

            return StructuredTool.from_function(
                coroutine=invoke, name=f"query_{role}", args_schema=QueryAgentInput,
                description=f"调用{ROLE_NAMES[role]}查询当前授权项目，身份与项目由服务端绑定。",
            )

        return {role: build(role) for role in decision.roles}

    async def _queries(self, principal: Principal, project_id: str, decision: ChatRoutingDecision,
                       memories: list[str], routing: ChatRoutingInfo) -> dict:
        tools = self._query_tools(principal, project_id, decision, memories)
        outputs: dict[str, dict] = {}
        invoked: list[str] = []
        steps: list[dict] = []

        async def invoke(role: str, focus: str = "") -> None:
            invoked.append(role)
            started = time.perf_counter()
            step = {"role": role, "tool": tools[role].name, "error_type": None}
            try:
                result = await asyncio.wait_for(tools[role].ainvoke({"focus": focus}), self.query_timeout)
                if result.get("outcome") not in {"ok", "no_results"}:
                    raise AgentProtocolError("Query role returned an invalid outcome")
                outputs[role] = result
                routing.outcomes[role] = result["outcome"]
            except TimeoutError:
                routing.outcomes[role] = "timeout"
                step["error_type"] = "TimeoutError"
            except Exception as exc:
                # Record a failed operation, never turn it into a successful empty result.
                routing.outcomes[role] = "failed"
                step["error_type"] = type(exc).__name__
            finally:
                steps.append({**step, "status": routing.outcomes.get(role),
                              "latency_ms": round((time.perf_counter() - started) * 1000, 2)})

        question = ""
        if decision.material_depends_on_retrieval:
            await invoke("retrieval")
            result = outputs.get("retrieval", {})
            cited_ids = set(re.findall(r"\[([^\[\]]+)\]", result.get("answer", "")))
            models = {
                match.upper().replace(" ", "-")
                for item in result.get("_tool_evidence", [])
                if item.get("evidence_id") in cited_ids
                for match in MATERIAL_MODEL.findall(item.get("text", ""))
                if re.search(r"\d", match)
            }
            if routing.outcomes.get("retrieval") == "ok" and len(models) == 1:
                await invoke("material", next(iter(models)))
            else:
                routing.outcomes["material"] = "blocked"
                question = "请明确历史项目和所用材料型号，再查询对应规格。"
        else:
            await asyncio.gather(*(invoke(role) for role in decision.roles))
        if not outputs:
            raise AgentProtocolError("All selected knowledge queries failed or timed out")
        sources, uncertainties, parts = [], [], []
        usage = {"input_tokens": 0, "output_tokens": 0}
        for role in decision.roles:
            if role not in outputs:
                if routing.outcomes.get(role) != "blocked":
                    uncertainties.append(f"{ROLE_NAMES[role]}查询失败或超时，未获得结果；不能视为没有相关资料。")
                continue
            result = outputs[role]
            parts.append(f"{'资料检索' if role == 'retrieval' else '材料查询'}：\n{result['answer']}")
            known = {source["source_id"] for source in sources}
            for source in result.get("sources", []):
                if source["source_id"] not in known:
                    sources.append(source)
                    known.add(source["source_id"])
            uncertainties.extend(result.get("uncertainties", []))
            for key in usage:
                usage[key] += int(result.get("usage", {}).get("model_usage", {}).get(key, 0))
        if question:
            parts.append(question)
            uncertainties.append(question)
        if uncertainties:
            parts.append("范围说明：\n" + "\n".join(dict.fromkeys(uncertainties)))
        return {
            "answer": "\n\n".join(parts), "answer_origin": "project_evidence",
            "sources": sources, "uncertainties": list(dict.fromkeys(uncertainties)),
            "usage": {
                **self.router.provider.metadata, "model_usage": usage,
                "agents_used": ["ConversationSupervisor", *(ROLE_NAMES[role] for role in invoked)],
                "dispatch": "validated-intent-to-tool", "combiner": "deterministic",
                "query_steps": steps,
                "role_usage": {role: outputs[role].get("usage", {}) for role in outputs},
            },
        }

    async def ainvoke(self, principal: Principal, project_id: str, session_id: str, query: str,
                      request_id: str | None = None) -> dict:
        await self.authorization.authorize(principal, project_id)
        started = time.perf_counter()
        prompt = get_prompt("conversation-router")
        run_id = await self.store.start_agent_run(
            tenant_id=principal.tenant_id, project_id=project_id, user_id=principal.user_id,
            run_type="conversation_chat", provider=str(self.router.provider.metadata.get("provider", "")),
            model=str(self.router.provider.metadata.get("model", "")), business_id=session_id,
            prompt_name=prompt.name, prompt_version=prompt.version, prompt_sha256=prompt.digest,
        )
        try:
            if self.router.provider.metadata.get("mode") == "api" and await self.store.project_has_nonpublic_documents(project_id):
                raise AgentProtocolError("项目包含非公开资料，当前云端问答不可用")
            key = scoped_session(principal, project_id, session_id)
            history = await self.store.conversation_messages(principal.user_id, key)
            await self.store.append_message(principal.user_id, key, "user", query)
            decision, source, router_usage = await self.router.route(query, history)
            routing = ChatRoutingInfo(
                intent=decision.intent, execution_mode=decision.execution_mode,
                agents_planned=[ROLE_NAMES[role] for role in decision.roles],
                needs_review=decision.intent in {"generate_project", "review_package"}, decision_source=source,
            )
            if decision.intent == "direct_chat":
                state = await self._direct(query)
            elif decision.roles:
                memories = await self.knowledge.memory.search(
                    tenant_id=principal.tenant_id, user_id=principal.user_id, project_id=project_id, query=query,
                )
                state = await self._queries(principal, project_id, decision, memories, routing)
            else:
                if decision.intent == "generate_project":
                    from src.application.project_plans import ProjectPlanService
                    from src.domain.project_plan import CreatePlanRequest, digest, requirements_from_chat

                    action_key = request_id or digest([key, query])
                    plan = await ProjectPlanService(self.store, supervisor=self).create(
                        principal, project_id, CreatePlanRequest(
                            request_id=action_key, requirements=requirements_from_chat(query),
                        ),
                    )
                    answer = (f"已受理项目初步方案 {plan['plan_id']}，版本 v{plan['version']}，当前状态：{plan['status']}。"
                              "请到项目方案页查看来源、补充缺失需求并复核；同版本审查通过且人工批准后才可下载Markdown和Word。")
                    routing.action_status = "accepted"
                    routing.agents_planned = ["RetrievalAgent", "MaterialAgent", "ReviewAgent"]
                elif decision.intent == "review_package":
                    answer = "请在现有资料审查页选定已索引资料后提交，或使用 /api/v1/package-reviews 接口；本次聊天没有创建审查任务。"
                    routing.action_status = "existing_api_required"
                else:
                    answer = decision.clarification_question
                state = {
                    "answer": answer, "sources": [], "uncertainties": [],
                    "answer_origin": "clarification" if decision.intent == "clarify" else "workflow_guidance",
                    "usage": {**self.router.provider.metadata, "model_usage": {"input_tokens": 0, "output_tokens": 0},
                              "agents_used": ["ConversationSupervisor"]},
                }
                if decision.intent == "generate_project":
                    state["project_plan"] = {name: plan[name] for name in (
                        "plan_id", "project_id", "version", "status", "workflow_id", "workflow",
                    )}
            # Keep the legacy public route for single project lookups while the
            # structured routing object exposes the new intent precisely.
            state["route"] = {
                "knowledge_search": "knowledge",
                "material_query": "knowledge",
            }.get(decision.intent, decision.intent)
            state["routing"] = routing.model_dump(mode="json")
            usage = state["usage"].setdefault("model_usage", {})
            for name in ("input_tokens", "output_tokens"):
                usage[name] = int(usage.get(name, 0)) + int(router_usage.get(name, 0))
            state["usage"]["router_usage"] = router_usage
            candidate = await self.knowledge.memory.propose_from_message(
                tenant_id=principal.tenant_id, user_id=principal.user_id, project_id=project_id,
                message=query, source_id=session_id,
            )
            state["memory_candidates"] = [candidate] if candidate else []
            await self.store.append_message(principal.user_id, key, "assistant", state["answer"])
            await self.store.finish_agent_run(
                run_id, status="completed", input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0), latency_ms=(time.perf_counter() - started) * 1000,
                finish_reason="partial" if any(value in {"failed", "timeout", "blocked"} for value in routing.outcomes.values())
                else "stop",
            )
            return state
        except Exception as exc:
            await self.store.finish_agent_run(
                run_id, status="failed", latency_ms=(time.perf_counter() - started) * 1000,
                error_type=type(exc).__name__,
            )
            raise
