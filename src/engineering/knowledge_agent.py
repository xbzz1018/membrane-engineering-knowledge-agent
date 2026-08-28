from __future__ import annotations

import json
import time
from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver

from src.core.config import get_settings
from src.core.observability import span
from src.core.security import Principal
from src.engineering.memory import get_memory_service
from src.engineering.provider import ModelProvider, get_model_provider
from src.engineering.retrieval import RetrievalService
from src.engineering.storage import EngineeringStorage, storage

SYSTEM_PROMPT = """你是膜结构企业内部知识助手。
回答工程资料问题前必须调用search_project_knowledge，只能根据工具返回的evidence回答。
项目记忆仅用于理解用户偏好，不能作为事实证据。每个事实结论都要引用[evidence_id]。
证据不足时明确说明不知道；不得进行结构安全计算，不得生成正式报价。"""

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
        self.memory = get_memory_service(store)

    def _checkpointer(self):
        if get_settings().RUNTIME_MODE.lower() == "full":
            from src.engineering.redis_checkpoint import get_redis_checkpointer

            return get_redis_checkpointer()
        return _local_checkpointer

    def _search_tool(self, project_id: str):
        retrieval = self.retrieval

        @tool
        async def search_project_knowledge(query: str) -> str:
            """检索当前项目文档、工程案例、膜材规格与带日期的历史价格资料。"""
            packet = await retrieval.retrieve(query, project_id)
            return json.dumps(packet.as_tool_result(), ensure_ascii=False, default=str)

        return search_project_knowledge

    @staticmethod
    def _tool_payload(messages: list[Any]) -> dict[str, Any] | None:
        for message in reversed(messages):
            if isinstance(message, ToolMessage) and message.name == "search_project_knowledge":
                try:
                    return json.loads(str(message.content))
                except (TypeError, json.JSONDecodeError):
                    return None
        return None

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
        packet = await self.retrieval.retrieve(query, project_id)
        if not packet.evidence:
            return {
                "answer": "当前项目资料中没有找到足够证据，无法给出可靠结论。",
                "route": "knowledge",
                "sources": [],
                "uncertainties": packet.uncertainties,
                "usage": {**self.provider.metadata, "agents_used": ["KnowledgeAgent"]},
            }
        agent = create_agent(
            model=self.provider.langchain_model(),
            tools=[self._search_tool(project_id)],
            system_prompt=SYSTEM_PROMPT,
            checkpointer=self._checkpointer(),
            name="knowledge_agent",
        )
        content = (
            f"问题：{query}\n"
            "应用层已检索的证据（必须仅依据这些evidence_id回答）：\n"
            f"{json.dumps(packet.as_tool_result(), ensure_ascii=False, default=str)}"
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
        payload = self._tool_payload(messages) or packet.as_tool_result()
        answer, usage, finish_reason = self._answer(messages)
        return {
            "answer": answer,
            "route": "knowledge",
            "sources": payload.get("sources", []),
            "uncertainties": payload.get("uncertainties", []),
            "usage": {
                **self.provider.metadata,
                "model_usage": usage,
                "finish_reason": finish_reason,
                "agents_used": ["KnowledgeAgent"],
            },
        }

    async def _invoke_fake(self, project_id: str, query: str) -> dict[str, Any]:
        packet = await self.retrieval.retrieve(query, project_id)
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
        run_id = await self.store.start_agent_run(
            tenant_id=principal.tenant_id,
            project_id=project_id,
            user_id=principal.user_id,
            run_type="knowledge_chat",
            provider=str(self.provider.metadata.get("provider", "")),
            model=str(self.provider.metadata.get("model", "")),
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
                state = await self._invoke_fake(project_id, query)
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
