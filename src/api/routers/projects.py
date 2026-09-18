from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from src.api.dependencies import current_principal, require_global_role, require_project_role
from src.core.security import ROLES, Principal
from src.domain.schemas import BudgetUpdateRequest
from src.infrastructure.database import storage
from src.infrastructure.health import dependency_health

router = APIRouter(prefix="/api/v1/projects", tags=["项目与权限"])


class CreateProjectRequest(BaseModel):
    model_config = ConfigDict(title="创建项目请求")
    name: str = Field(min_length=1, max_length=256, description="项目名称")


class ProjectMemberRequest(BaseModel):
    model_config = ConfigDict(title="项目成员请求")
    user_id: str = Field(min_length=1, max_length=64, description="企业用户ID")
    role: str = Field(description="项目角色")


@router.get("", summary="查看当前用户可访问的项目")
async def list_projects(principal: Principal = Depends(current_principal)) -> list[dict]:
    rows = await storage.list_projects_for_user(principal.user_id, principal.tenant_id, principal.role)
    hidden = {"reserved_tokens", "used_tokens", "reserved_cost_micros", "used_cost_micros"}
    return [{key: value for key, value in row.items() if key not in hidden} for row in rows]


@router.post("", status_code=201, summary="管理员创建项目")
async def create_project(
    request: CreateProjectRequest,
    principal: Principal = Depends(current_principal),
) -> dict:
    require_global_role(principal, {"admin"})
    row = await storage.create_project(request.name, principal.tenant_id)
    await storage.add_project_member(row["id"], principal.user_id, "admin")
    return row


@router.get("/{project_id}", summary="查看项目详情")
async def get_project(
    project_id: str,
    principal: Principal = Depends(current_principal),
) -> dict:
    await require_project_role(project_id, principal)
    row = await storage.get_project(project_id, principal.tenant_id)
    if not row:
        raise HTTPException(status_code=404, detail="项目不存在")
    hidden = {"reserved_tokens", "used_tokens", "reserved_cost_micros", "used_cost_micros"}
    return {key: value for key, value in row.items() if key not in hidden}


@router.get("/{project_id}/members", summary="查看项目成员与角色")
async def list_members(
    project_id: str,
    principal: Principal = Depends(current_principal),
) -> list[dict]:
    await require_project_role(project_id, principal)
    return await storage.list_project_members(project_id)


@router.get("/{project_id}/budget", summary="查看项目Token与成本预算")
async def project_budget(
    project_id: str,
    principal: Principal = Depends(current_principal),
) -> dict:
    await require_project_role(project_id, principal)
    result = await storage.get_project_budget(project_id, principal.tenant_id)
    if not result:
        raise HTTPException(status_code=404, detail="项目不存在")
    return result


@router.patch("/{project_id}/budget", summary="管理员更新项目预算保护阀")
async def update_project_budget(
    project_id: str,
    request: BudgetUpdateRequest,
    principal: Principal = Depends(current_principal),
) -> dict:
    await require_project_role(project_id, principal, {"admin"})
    try:
        result = await storage.update_project_budget(
            project_id,
            principal.tenant_id,
            daily_token_limit=request.daily_token_limit,
            monthly_cost_limit_micros=request.monthly_cost_limit_micros,
            max_concurrent_reviews=request.max_concurrent_reviews,
            expected_lock_version=request.expected_lock_version,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    return result


@router.get("/{project_id}/dashboard", summary="查看项目审查工作台总览")
async def project_dashboard(
    project_id: str,
    principal: Principal = Depends(current_principal),
) -> dict:
    await require_project_role(project_id, principal)
    result = await storage.project_dashboard(project_id, principal.tenant_id)
    if result is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    result["dependencies"] = (await dependency_health())["checks"]
    return result


@router.post("/{project_id}/members", status_code=204, summary="管理员添加或更新项目成员")
async def add_member(
    project_id: str,
    request: ProjectMemberRequest,
    principal: Principal = Depends(current_principal),
) -> None:
    await require_project_role(project_id, principal, {"admin"})
    if request.role not in ROLES:
        raise HTTPException(status_code=422, detail="不支持的项目角色")
    if not await storage.get_user(request.user_id):
        raise HTTPException(status_code=404, detail="用户不存在")
    await storage.add_project_member(project_id, request.user_id, request.role)
