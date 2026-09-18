from __future__ import annotations

import uuid
from typing import Any

from src.application.authorization import ProjectAuthorizationService, project_authorization
from src.core.security import Principal
from src.domain.schemas import (
    MaterialSpecCreateRequest,
    MaterialSpecUpdateRequest,
    PriceRecordCreateRequest,
    PriceRecordUpdateRequest,
)
from src.infrastructure.database import EngineeringStorage, storage


class CatalogApplicationError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class CatalogApplicationService:
    def __init__(
        self,
        store: EngineeringStorage = storage,
        authorization: ProjectAuthorizationService = project_authorization,
    ):
        self.store = store
        self.authorization = authorization

    async def list_specs(
        self, principal: Principal, project_id: str, query: str, status: str, page: int, page_size: int,
    ) -> dict[str, Any]:
        scope = await self.authorization.authorize(principal, project_id)
        return await self.store.list_material_specs(
            tenant_id=scope.tenant_id, query=query, status=status, page=page, page_size=page_size,
        )

    async def get_spec(self, principal: Principal, project_id: str, spec_id: str) -> dict[str, Any]:
        scope = await self.authorization.authorize(principal, project_id)
        result = await self.store.get_material_spec(spec_id, scope.tenant_id)
        if result is None:
            raise CatalogApplicationError("not_found", "膜材规格不存在或无访问权限")
        return result

    async def create_spec(
        self, principal: Principal, project_id: str, request: MaterialSpecCreateRequest,
    ) -> dict[str, Any]:
        scope = await self.authorization.authorize(principal, project_id, {"admin", "material_procurement"})
        spec_id = f"spec-{uuid.uuid4().hex}"
        try:
            return await self.store.create_material_spec(
                spec_id, request.model_dump(), tenant_id=scope.tenant_id, user_id=principal.user_id,
            )
        except ValueError as exc:  # pragma: no cover - UUID collision guard
            raise CatalogApplicationError("conflict", str(exc)) from exc

    async def update_spec(
        self,
        principal: Principal,
        project_id: str,
        spec_id: str,
        request: MaterialSpecUpdateRequest,
    ) -> dict[str, Any]:
        scope = await self.authorization.authorize(principal, project_id, {"admin", "material_procurement"})
        patch = request.model_dump(exclude_unset=True)
        expected = int(patch.pop("expected_lock_version"))
        try:
            result = await self.store.update_material_spec(
                spec_id, patch, tenant_id=scope.tenant_id, expected_lock_version=expected,
            )
        except ValueError as exc:
            raise CatalogApplicationError("conflict", str(exc)) from exc
        if result is None:
            raise CatalogApplicationError("not_found", "膜材规格不存在或无访问权限")
        return result

    async def archive_spec(
        self, principal: Principal, project_id: str, spec_id: str, expected_lock_version: int,
    ) -> dict[str, Any]:
        scope = await self.authorization.authorize(principal, project_id, {"admin", "material_procurement"})
        try:
            result = await self.store.archive_material_spec(
                spec_id, tenant_id=scope.tenant_id, expected_lock_version=expected_lock_version,
            )
        except ValueError as exc:
            raise CatalogApplicationError("conflict", str(exc)) from exc
        if result is None:
            raise CatalogApplicationError("not_found", "膜材规格不存在或无访问权限")
        return result

    async def list_prices(
        self, principal: Principal, project_id: str, query: str, status: str, page: int, page_size: int,
    ) -> dict[str, Any]:
        scope = await self.authorization.authorize(principal, project_id)
        return await self.store.list_price_records(
            tenant_id=scope.tenant_id, project_id=project_id, query=query, status=status,
            page=page, page_size=page_size,
        )

    async def get_price(self, principal: Principal, project_id: str, price_id: str) -> dict[str, Any]:
        scope = await self.authorization.authorize(principal, project_id)
        result = await self.store.get_price_record(
            price_id, tenant_id=scope.tenant_id, project_id=project_id,
        )
        if result is None:
            raise CatalogApplicationError("not_found", "历史价格不存在或无访问权限")
        return result

    @staticmethod
    def _validate_price(payload: dict[str, Any]) -> None:
        if float(payload["min_price"]) > float(payload["max_price"]):
            raise CatalogApplicationError("invalid", "最低价格不能高于最高价格")
        if not bool(payload.get("synthetic", True)) and payload.get("visibility") == "public":
            raise CatalogApplicationError("invalid", "非synthetic历史价格不能设置为public")

    async def create_price(
        self, principal: Principal, project_id: str, request: PriceRecordCreateRequest,
    ) -> dict[str, Any]:
        scope = await self.authorization.authorize(principal, project_id, {"admin", "material_procurement"})
        payload = request.model_dump()
        payload["project_id"] = payload.get("project_id") or project_id
        if payload["project_id"] != project_id:
            await self.authorization.authorize(principal, payload["project_id"], {"admin", "material_procurement"})
        self._validate_price(payload)
        price_id = f"price-{uuid.uuid4().hex}"
        try:
            return await self.store.create_price_record(
                price_id, payload, tenant_id=scope.tenant_id, user_id=principal.user_id,
            )
        except ValueError as exc:  # pragma: no cover - UUID collision guard
            raise CatalogApplicationError("conflict", str(exc)) from exc

    async def update_price(
        self,
        principal: Principal,
        project_id: str,
        price_id: str,
        request: PriceRecordUpdateRequest,
    ) -> dict[str, Any]:
        scope = await self.authorization.authorize(principal, project_id, {"admin", "material_procurement"})
        current = await self.get_price(principal, project_id, price_id)
        patch = request.model_dump(exclude_unset=True)
        expected = int(patch.pop("expected_lock_version"))
        merged = {**current, **patch}
        target_project = str(merged.get("project_id") or project_id)
        await self.authorization.authorize(principal, target_project, {"admin", "material_procurement"})
        self._validate_price(merged)
        try:
            result = await self.store.update_price_record(
                price_id, patch, tenant_id=scope.tenant_id, project_id=project_id,
                expected_lock_version=expected,
            )
        except ValueError as exc:
            raise CatalogApplicationError("conflict", str(exc)) from exc
        if result is None:
            raise CatalogApplicationError("not_found", "历史价格不存在或无访问权限")
        return result

    async def archive_price(
        self, principal: Principal, project_id: str, price_id: str, expected_lock_version: int,
    ) -> dict[str, Any]:
        scope = await self.authorization.authorize(principal, project_id, {"admin", "material_procurement"})
        try:
            result = await self.store.archive_price_record(
                price_id, tenant_id=scope.tenant_id, project_id=project_id,
                expected_lock_version=expected_lock_version,
            )
        except ValueError as exc:
            raise CatalogApplicationError("conflict", str(exc)) from exc
        if result is None:
            raise CatalogApplicationError("not_found", "历史价格不存在或无访问权限")
        return result


catalog_application = CatalogApplicationService()
