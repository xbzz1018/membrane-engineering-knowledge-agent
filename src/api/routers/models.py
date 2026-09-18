from __future__ import annotations

from fastapi import APIRouter, Depends

from src.agents.model_catalog import get_model_capability_service
from src.api.dependencies import current_principal, require_global_role
from src.core.security import Principal

router = APIRouter(prefix="/api/v1/model-capabilities", tags=["模型能力"])


@router.get("", summary="查看当前模型策略与向量模型目录")
async def model_capabilities(principal: Principal = Depends(current_principal)) -> dict:
    return get_model_capability_service().overview()


@router.get("/discovered", summary="查询阿里 Workspace 动态模型")
async def discovered_models(principal: Principal = Depends(current_principal)) -> dict:
    require_global_role(principal, {"admin"})
    return await get_model_capability_service().discover()


@router.post("/reranker/validate", summary="真实验证当前重排序模型")
async def validate_reranker(principal: Principal = Depends(current_principal)) -> dict:
    require_global_role(principal, {"admin"})
    return await get_model_capability_service().validate_reranker()
