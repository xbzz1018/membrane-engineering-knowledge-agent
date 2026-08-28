from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.api.dependencies import current_principal, require_global_role, require_project_role
from src.core.security import ROLES, Principal
from src.engineering.storage import storage

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])


class CreateProjectRequest(BaseModel):
    name: str = Field(min_length=1, max_length=256)


class ProjectMemberRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=64)
    role: str


@router.get("")
async def list_projects(principal: Principal = Depends(current_principal)) -> list[dict]:
    rows = await storage.list_projects_for_user(principal.user_id, principal.tenant_id, principal.role)
    hidden = {"reserved_tokens", "used_tokens", "reserved_cost_micros", "used_cost_micros"}
    return [{key: value for key, value in row.items() if key not in hidden} for row in rows]


@router.post("", status_code=201)
async def create_project(
    request: CreateProjectRequest,
    principal: Principal = Depends(current_principal),
) -> dict:
    require_global_role(principal, {"admin"})
    row = await storage.create_project(request.name, principal.tenant_id)
    await storage.add_project_member(row["id"], principal.user_id, "admin")
    return row


@router.post("/{project_id}/members", status_code=204)
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
