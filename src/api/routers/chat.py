from __future__ import annotations

import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from src.engineering.agents import get_supervisor
from src.engineering.schemas import ChatRequest, ChatResponse

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    state = await get_supervisor().ainvoke(request.user_id, request.session_id, request.message)
    return ChatResponse(
        answer=state.get("answer", ""),
        session_id=request.session_id,
        route=state.get("route", "multi"),
        agents_used=state.get("usage", {}).get("agents_used", []),
        sources=state.get("sources", []),
        uncertainties=state.get("uncertainties", []),
        usage=state.get("usage", {}),
    )


@router.post("/stream")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    async def events():
        response = await chat(request)
        yield f"data: {json.dumps({'type': 'token', 'content': response.answer}, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'type': 'sources', 'sources': [item.model_dump() for item in response.sources]}, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'type': 'done', 'session_id': response.session_id}, ensure_ascii=False)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
