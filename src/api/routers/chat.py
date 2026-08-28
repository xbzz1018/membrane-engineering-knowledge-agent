from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from src.api.dependencies import rate_limited_principal, require_project_role
from src.core.security import Principal
from src.engineering.agents import get_knowledge_agent
from src.engineering.schemas import ChatRequest, ChatResponse

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    principal: Principal = Depends(rate_limited_principal),
) -> ChatResponse:
    await require_project_role(request.project_id, principal)
    state = await get_knowledge_agent().ainvoke(
        principal, request.project_id, request.session_id, request.message,
    )
    return ChatResponse(
        answer=state.get("answer", ""),
        session_id=request.session_id,
        route=state.get("route", "multi"),
        agents_used=state.get("usage", {}).get("agents_used", []),
        sources=state.get("sources", []),
        uncertainties=state.get("uncertainties", []),
        usage=state.get("usage", {}),
        memory_candidates=state.get("memory_candidates", []),
    )


@router.post("/stream")
async def chat_stream(
    request: ChatRequest,
    principal: Principal = Depends(rate_limited_principal),
) -> StreamingResponse:
    async def events():
        await require_project_role(request.project_id, principal)
        state = await get_knowledge_agent().ainvoke(
            principal, request.project_id, request.session_id, request.message,
        )
        response = ChatResponse(
            answer=state["answer"],
            session_id=request.session_id,
            route=state.get("route", "knowledge"),
            agents_used=state.get("usage", {}).get("agents_used", []),
            sources=state.get("sources", []),
            uncertainties=state.get("uncertainties", []),
            usage=state.get("usage", {}),
            memory_candidates=state.get("memory_candidates", []),
        )
        yield f"data: {json.dumps({'type': 'token', 'content': response.answer}, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'type': 'sources', 'sources': [item.model_dump() for item in response.sources]}, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'type': 'done', 'session_id': response.session_id}, ensure_ascii=False)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
