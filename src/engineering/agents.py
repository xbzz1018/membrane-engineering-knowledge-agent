from __future__ import annotations

import json
from typing import Any, TypedDict

from src.engineering.memory import get_memory_service
from src.engineering.provider import ModelProvider, get_model_provider
from src.engineering.schemas import SourceRef
from src.engineering.storage import EngineeringStorage, storage

try:
    from langgraph.graph import END, START, StateGraph
except Exception:  # pragma: no cover - optional fallback for minimal installs
    END = START = None
    StateGraph = None


class AgentState(TypedDict, total=False):
    user_id: str
    session_id: str
    query: str
    route: str
    hits: dict[str, list[dict[str, Any]]]
    memory: list[str]
    short_memory: list[dict[str, str]]
    answer: str
    sources: list[dict[str, Any]]
    uncertainties: list[str]
    usage: dict[str, Any]


class EngineeringSupervisor:
    def __init__(self, store: EngineeringStorage = storage, provider: ModelProvider | None = None):
        self.store = store
        self.provider = provider or get_model_provider()
        self.memory = get_memory_service(store)
        self.graph = self._build_graph() if StateGraph else None

    @staticmethod
    def route(query: str) -> str:
        text = query.lower()
        material_words = (
            "规格", "厚度", "重量", "透光", "抗拉", "膜材", "材料", "参数", "型号",
            "etfe", "ptfe", "pvc", "precontraint", "flexlight",
        )
        price_words = ("价格", "报价", "多少钱", "成本")
        if any(word in text for word in ("比较", "对比", "方案", "案例", "设计")):
            if any(word in text for word in material_words + price_words):
                return "multi"
            return "design"
        if any(word in text for word in price_words):
            return "price"
        if any(word in text for word in material_words):
            return "material"
        return "multi"

    async def _retrieve(self, state: AgentState) -> AgentState:
        route = state["route"]
        query = state["query"]
        hits: dict[str, list[dict[str, Any]]] = {"cases": [], "chunks": [], "specs": [], "prices": []}
        hits["chunks"] = await self.store.search_chunks(query)
        if route in {"design", "multi"}:
            hits["cases"] = await self.store.search_cases(query)
        if route in {"material", "multi"}:
            hits["specs"] = await self.store.search_specs(query)
        if route in {"price", "multi"}:
            hits["prices"] = await self.store.search_prices(query)
        return {**state, "hits": hits}

    async def _compose(self, state: AgentState) -> AgentState:
        hits = state.get("hits", {})
        context_parts: list[str] = []
        source_refs: list[dict[str, Any]] = []
        for item in hits.get("chunks", []):
            source_id = f"doc:{item['document_id']}:{item['chunk_index']}"
            created_at = item.get("created_at")
            source_refs.append(SourceRef(
                source_id=source_id,
                title=item.get("filename", source_id),
                source_type="document",
                location=f"第{item['page_number']}页",
                excerpt=item["text"][:300],
                date=created_at.isoformat() if hasattr(created_at, "isoformat") else str(created_at or ""),
                version=str(item.get("version", "")),
                retrieval=item.get("retrieval", []),
                fusion_score=item.get("fusion_score"),
                fusion_method=item.get("fusion_method", ""),
            ).model_dump())
            context_parts.append(f"文档证据 {item['text']}")
        for item in hits.get("cases", []):
            source_id = str(item.get("case_id", "case"))
            source_refs.append(SourceRef(
                source_id=source_id,
                title=item.get("title", source_id),
                source_type="case",
                url=item.get("source_url", ""),
                date=str(item.get("year") or item.get("retrieved_at", "")),
                version=str(item.get("source_version", "")),
                retrieval=item.get("retrieval", []),
                fusion_score=item.get("fusion_score"),
                fusion_method=item.get("fusion_method", ""),
            ).model_dump())
            context_parts.append(f"案例 {item}")
        for item in hits.get("specs", []):
            source_id = str(item.get("spec_id", "spec"))
            source_refs.append(SourceRef(
                source_id=source_id,
                title=item.get("material", source_id),
                source_type="material_spec",
                url=item.get("source_url", ""),
                date=str(item.get("retrieved_at", "")),
                version=str(item.get("source_version", "")),
                retrieval=item.get("retrieval", []),
            ).model_dump())
            context_parts.append(f"规格 {item}")
        for item in hits.get("prices", []):
            source_id = str(item.get("price_id", "price"))
            source_refs.append(SourceRef(
                source_id=source_id,
                title=item.get("material", source_id),
                source_type="price",
                url=item.get("source_url", ""),
                date=str(item.get("effective_date", "")),
                version=str(item.get("source_version", "")),
                retrieval=item.get("retrieval", []),
            ).model_dump())
            context_parts.append(f"价格 {item}")
        evidence = "\n".join(context_parts[:16])
        if not evidence:
            answer = "当前工程资料中没有找到足够证据，无法给出可靠结论。请上传相关设计方案、膜材规格或报价资料。"
            uncertainty = ["没有匹配到工程资料"]
            usage = self.provider.metadata
        else:
            system = (
                "你是膜结构工程资料助手。只能根据证据回答，不得进行结构安全计算或生成正式报价。"
                "价格必须说明资料日期和仅供参考；证据不足时明确说不知道。"
            )
            short_memory = json.dumps(state.get("short_memory", []), ensure_ascii=False)
            prompt = (
                f"问题：{state['query']}\n"
                f"本会话最近消息：{short_memory}\n"
                f"长期记忆：{state.get('memory', [])}\n证据：\n{evidence}"
            )
            answer, usage = await self.provider.chat(system, prompt)
            uncertainty = []
            if not hits.get("prices") and any(word in state["query"] for word in ("价格", "报价", "成本")):
                uncertainty.append("未找到带日期和来源的价格记录")
            if len(source_refs) == 0:
                uncertainty.append("未返回可引用来源")
        agents = {
            "design": ["EngineeringQueryAgent", "DesignCaseAgent"],
            "material": ["EngineeringQueryAgent", "MaterialPriceAgent"],
            "price": ["EngineeringQueryAgent", "MaterialPriceAgent"],
            "multi": ["EngineeringQueryAgent", "DesignCaseAgent", "MaterialPriceAgent"],
        }[state["route"]]
        return {**state, "answer": answer, "sources": source_refs[:12], "uncertainties": uncertainty, "usage": {**usage, "agents_used": agents}}

    def _build_graph(self):
        builder = StateGraph(AgentState)

        async def route_node(state: AgentState) -> AgentState:
            return {**state, "route": self.route(state["query"]), "memory": await self.memory.search_long(state["user_id"], state["query"])}

        builder.add_node("route", route_node)
        builder.add_node("retrieve", self._retrieve)
        builder.add_node("compose", self._compose)
        builder.add_edge(START, "route")
        builder.add_edge("route", "retrieve")
        builder.add_edge("retrieve", "compose")
        builder.add_edge("compose", END)
        runtime_mode = getattr(getattr(self.store, "settings", None), "RUNTIME_MODE", "local")
        if runtime_mode.lower() == "full":
            from src.engineering.redis_checkpoint import get_redis_checkpointer

            return builder.compile(checkpointer=get_redis_checkpointer())
        return builder.compile()

    async def ainvoke(self, user_id: str, session_id: str, query: str) -> dict[str, Any]:
        await self.memory.maybe_save_long(user_id, query)
        short_memory = await self.memory.append_short(user_id, session_id, "user", query)
        await self.store.append_message(user_id, session_id, "user", query)
        initial: AgentState = {
            "user_id": user_id,
            "session_id": session_id,
            "query": query,
            "short_memory": short_memory,
        }
        if self.graph:
            state = await self.graph.ainvoke(
                initial,
                config={"configurable": {"thread_id": f"{user_id}:{session_id}"}},
            )
        else:
            state = await self._compose(await self._retrieve({**initial, "route": self.route(query), "memory": await self.memory.search_long(user_id, query)}))
        await self.memory.append_short(user_id, session_id, "assistant", state.get("answer", ""))
        await self.store.append_message(user_id, session_id, "assistant", state.get("answer", ""))
        return state


_supervisor: EngineeringSupervisor | None = None


def get_supervisor() -> EngineeringSupervisor:
    global _supervisor
    if _supervisor is None:
        _supervisor = EngineeringSupervisor()
    return _supervisor
