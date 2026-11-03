from __future__ import annotations

import json
import re
import time
from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver

from src.agents.prompts import get_prompt
from src.application.knowledge import KnowledgeQueryError, KnowledgeQueryService
from src.application.memory import get_memory_service
from src.core.config import get_settings
from src.core.observability import span
from src.core.security import Principal
from src.domain.document_search import DocumentSearchFilters
from src.infrastructure.database import EngineeringStorage, storage
from src.infrastructure.model_provider import ModelProvider, get_model_provider
from src.infrastructure.retrieval import RetrievalService

SYSTEM_PROMPT = get_prompt("knowledge").text

_local_checkpointer = InMemorySaver()


class AgentProtocolError(RuntimeError):
    pass


class KnowledgeAgent:
    def __init__(
        self,
        store: EngineeringStorage = storage,
        provider: ModelProvider | None = None,
    ):
        self.store = store
        self.provider = provider or get_model_provider()
        self.retrieval = RetrievalService(store, self.provider)
        self.queries = KnowledgeQueryService(store, retrieval=self.retrieval)
        self.memory = get_memory_service(store)

    def _checkpointer(self):
        if get_settings().RUNTIME_MODE.lower() == "full":
            from src.infrastructure.redis_checkpoint import get_redis_checkpointer

            return get_redis_checkpointer()
        return _local_checkpointer

    def _tools(self, principal: Principal, project_id: str):
        queries = self.queries

        async def call_query(operation, tool_name: str) -> str:
            try:
                result = await operation()
            except KnowledgeQueryError as exc:
                # Let the model correct an invalid identifier or explain a scope miss;
                # tool exceptions must not abort the whole LangGraph run.
                result = {"tool": tool_name, "error": exc.code, "message": str(exc), "evidence": [], "sources": []}
            return json.dumps(result, ensure_ascii=False, default=str)

        @tool
        async def search_project_documents(query: str, limit: int = 8,
                                           filters: DocumentSearchFilters | None = None) -> str:
            """检索当前项目公开资料。明确型号/适用版本/业务日期放filters，未知条件不要猜测。"""
            return await call_query(
                lambda: queries.search_documents(
                    principal, project_id, query, limit=limit, classifications={"public"},
                    **({"filters": filters} if filters is not None else {}),
                ),
                "search_project_documents",
            )

        @tool
        async def query_material_specs(query: str, limit: int = 8) -> str:
            """查询当前企业的公开膜材型号、规格、性能、来源和版本。"""
            return await call_query(
                lambda: queries.query_material_specs(
                    principal, project_id, query, limit=limit, visibility={"public"},
                ),
                "query_material_specs",
            )

        @tool
        async def query_price_records(query: str, limit: int = 8) -> str:
            """查询项目可见的公开历史测试价格，返回日期、地区、币种、单位与synthetic声明。"""
            return await call_query(
                lambda: queries.query_price_records(
                    principal, project_id, query, limit=limit, visibility={"public"},
                ),
                "query_price_records",
            )

        @tool
        async def get_document_evidence(document_id: str, limit: int = 20) -> str:
            """按文档ID读取公开Evidence的文件名、页码或位置、版本和受限长度正文。"""
            return await call_query(
                lambda: queries.get_document_evidence(
                    principal, document_id, limit=limit, classifications={"public"},
                ),
                "get_document_evidence",
            )

        return [search_project_documents, query_material_specs, query_price_records, get_document_evidence]

    @staticmethod
    def _tool_payloads(messages: list[Any]) -> list[dict[str, Any]]:
        payloads = []
        for message in messages:
            if isinstance(message, ToolMessage):
                try:
                    payload = json.loads(str(message.content))
                    if isinstance(payload, dict) and payload.get("tool"):
                        payloads.append(payload)
                except (TypeError, json.JSONDecodeError):
                    continue
        return payloads

    @staticmethod
    def _answer(messages: list[Any]) -> tuple[str, dict[str, Any], str]:
        for message in reversed(messages):
            if not isinstance(message, AIMessage):
                continue
            content = message.content
            if isinstance(content, str) and content.strip():
                response_metadata = dict(message.response_metadata or {})
                finish_reason = str(response_metadata.get("finish_reason", ""))
                if finish_reason == "length":
                    raise AgentProtocolError("KnowledgeAgent output was truncated")
                return content, dict(message.usage_metadata or {}), finish_reason
        raise AgentProtocolError("KnowledgeAgent returned no final answer")

    async def _invoke_api(
        self,
        principal: Principal,
        project_id: str,
        session_id: str,
        query: str,
        memories: list[str],
    ) -> dict[str, Any]:
        if await self.store.project_has_nonpublic_documents(project_id):
            raise AgentProtocolError("项目包含非公开资料，未配置本地模型时禁止云端调用")
        prompt = get_prompt("knowledge")
        agent = create_agent(
            model=self.provider.langchain_model(),
            tools=self._tools(principal, project_id),
            system_prompt=prompt.text,
            checkpointer=self._checkpointer(),
            name="knowledge_agent",
        )
        content = (
            f"问题：{query}\n"
            "请根据问题选择必要的知识工具。必须至少调用一个工具后再回答。"
        )
        if memories:
            content += "\n用户已确认的项目记忆（仅作上下文，不是证据）：" + json.dumps(memories, ensure_ascii=False)
        with span("gen_ai.invoke_agent", {
            "gen_ai.agent.name": "KnowledgeAgent",
            "gen_ai.provider.name": str(self.provider.metadata.get("provider", "")),
            "gen_ai.request.model": str(self.provider.metadata.get("model", "")),
        }):
            result = await agent.ainvoke(
                {"messages": [{"role": "user", "content": content}]},
                config={
                    "configurable": {
                        "thread_id": f"{principal.tenant_id}:{principal.user_id}:{project_id}:{session_id}",
                    }
                },
            )
        messages = result.get("messages", [])
        payloads = self._tool_payloads(messages)
        if not payloads:
            raise AgentProtocolError("KnowledgeAgent did not call a knowledge tool")
        answer, usage, finish_reason = self._answer(messages)
        sources = []
        uncertainties = []
        evidence_ids = set()
        for payload in payloads:
            for source in payload.get("sources", []):
                if source.get("source_id") not in {item.get("source_id") for item in sources}:
                    sources.append(source)
            for item in payload.get("evidence", []):
                evidence_id = item.get("evidence_id")
                if evidence_id:
                    evidence_ids.add(str(evidence_id))
            uncertainties.extend(item for item in payload.get("uncertainties", []) if item not in uncertainties)
        citations = set(re.findall(r"\[([^\[\]]+)\]", answer))
        memory_intent = bool(re.search(r"记住|记下|记得|remember", query, re.IGNORECASE))
        if evidence_ids and not memory_intent and ((not citations) or not citations <= evidence_ids):
            raise AgentProtocolError("KnowledgeAgent returned missing or invalid evidence citations")
        return {
            "answer": answer,
            "route": "knowledge",
            "sources": sources,
            "uncertainties": uncertainties,
            "usage": {
                **self.provider.metadata,
                "model_usage": usage,
                "finish_reason": finish_reason,
                "agents_used": ["KnowledgeAgent"],
            },
        }

    async def _invoke_fake(self, principal: Principal, project_id: str, query: str) -> dict[str, Any]:
        packet = await self.retrieval.retrieve(query, project_id, tenant_id=principal.tenant_id)
        if packet.evidence:
            answer, usage = await self.provider.chat(SYSTEM_PROMPT, f"问题：{query}\n证据：\n{packet.context}")
        else:
            answer = "当前项目资料中没有找到足够证据，无法给出可靠结论。"
            usage = self.provider.metadata
        return {
            "answer": answer,
            "route": "knowledge",
            "sources": packet.sources,
            "uncertainties": packet.uncertainties,
            "usage": {**usage, "agents_used": ["KnowledgeAgent"]},
        }

    async def ainvoke(
        self,
        principal: Principal,
        project_id: str,
        session_id: str,
        query: str,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        prompt = get_prompt("knowledge")
        run_id = await self.store.start_agent_run(
            tenant_id=principal.tenant_id,
            project_id=project_id,
            user_id=principal.user_id,
            run_type="knowledge_chat",
            provider=str(self.provider.metadata.get("provider", "")),
            model=str(self.provider.metadata.get("model", "")),
            business_id=session_id,
            prompt_name=prompt.name,
            prompt_version=prompt.version,
            prompt_sha256=prompt.digest,
        )
        try:
            await self.store.append_message(principal.user_id, session_id, "user", query)
            memories = await self.memory.search(
                tenant_id=principal.tenant_id,
                user_id=principal.user_id,
                project_id=project_id,
                query=query,
            )
            if self.provider.metadata.get("mode") == "api":
                state = await self._invoke_api(principal, project_id, session_id, query, memories)
            else:
                state = await self._invoke_fake(principal, project_id, query)
            candidate = await self.memory.propose_from_message(
                tenant_id=principal.tenant_id,
                user_id=principal.user_id,
                project_id=project_id,
                message=query,
                source_id=session_id,
            )
            state["memory_candidates"] = [candidate] if candidate else []
            await self.store.append_message(principal.user_id, session_id, "assistant", state["answer"])
            model_usage = state.get("usage", {}).get("model_usage", state.get("usage", {}))
            await self.store.finish_agent_run(
                run_id,
                status="completed",
                input_tokens=int(model_usage.get("input_tokens", 0) or 0),
                output_tokens=int(model_usage.get("output_tokens", 0) or 0),
                latency_ms=(time.perf_counter() - started) * 1000,
                finish_reason=str(state.get("usage", {}).get("finish_reason", "")),
            )
            return state
        except Exception as exc:
            await self.store.finish_agent_run(
                run_id,
                status="failed",
                latency_ms=(time.perf_counter() - started) * 1000,
                error_type=type(exc).__name__,
            )
            raise
