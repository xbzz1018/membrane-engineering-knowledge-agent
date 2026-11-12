from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from src.agents.knowledge_agent import AgentProtocolError
from src.agents.registry import get_conversation_supervisor
from src.api.dependencies import rate_limited_principal, require_project_role
from src.api.routers.project_plans import plan_errors
from src.core.security import Principal
from src.domain.schemas import ChatRequest, ChatResponse
from src.infrastructure.model_provider import ProviderConfigurationError, ProviderRequestError

router = APIRouter(prefix="/api/v1/chat", tags=["项目知识问答"])


async def conversation_state(request: ChatRequest, principal: Principal) -> dict:
    await require_project_role(request.project_id, principal)
    try:
        async with plan_errors():
            return await get_conversation_supervisor().ainvoke(
                principal, request.project_id, request.session_id, request.message, request_id=request.request_id,
            )
    except (AgentProtocolError, ProviderConfigurationError, ProviderRequestError) as exc:
        raise HTTPException(status_code=502, detail="问答执行失败，请检查模型或查询服务后重试") from exc


def chat_response(request: ChatRequest, state: dict) -> ChatResponse:
    return ChatResponse(
        answer=state.get("answer", ""), session_id=request.session_id,
        route=state["route"], answer_origin=state["answer_origin"], routing=state["routing"],
        agents_used=state.get("usage", {}).get("agents_used", []), sources=state.get("sources", []),
        uncertainties=state.get("uncertainties", []), usage=state.get("usage", {}),
        memory_candidates=state.get("memory_candidates", []),
        project_plan=state.get("project_plan"),
    )


@router.post("", response_model=ChatResponse, summary="按意图进行通用问答或项目资料查询")
async def chat(
    request: ChatRequest,
    principal: Principal = Depends(rate_limited_principal),
) -> ChatResponse:
    return chat_response(request, await conversation_state(request, principal))


@router.post("/stream", summary="流式返回知识问答结果")
async def chat_stream(
    request: ChatRequest,
    principal: Principal = Depends(rate_limited_principal),
) -> StreamingResponse:
    # Resolve failures before sending HTTP 200 headers; this is response SSE,
    # not a claim of token-by-token model streaming.
    response = chat_response(request, await conversation_state(request, principal))

    async def events():
        yield f"data: {json.dumps({'type': 'token', 'content': response.answer}, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'type': 'sources', 'sources': [item.model_dump() for item in response.sources]}, ensure_ascii=False)}\n\n"
        metadata = response.model_dump(mode="json", exclude={"answer", "sources"})
        yield f"data: {json.dumps({'type': 'done', **metadata}, ensure_ascii=False)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
