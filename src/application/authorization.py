from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from src.core.security import Principal
from src.infrastructure.database import EngineeringStorage, storage


class ProjectAccessError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class ProjectScope:
    tenant_id: str
    project_id: str
    user_id: str
    role: str


class ProjectAuthorizationService:
    def __init__(self, store: EngineeringStorage = storage):
        self.store = store

    async def authorize(
        self,
        principal: Principal,
        project_id: str,
        roles: Iterable[str] | None = None,
    ) -> ProjectScope:
        role = await self.store.project_access(
            project_id,
            principal.user_id,
            principal.tenant_id,
            principal.role,
        )
        if role is None:
            raise ProjectAccessError("not_found", "项目不存在或无访问权限")
        if roles is not None and role not in set(roles) and principal.role != "admin":
            raise ProjectAccessError("forbidden", "当前项目角色无权执行此操作")
        return ProjectScope(principal.tenant_id, project_id, principal.user_id, role)


project_authorization = ProjectAuthorizationService()
