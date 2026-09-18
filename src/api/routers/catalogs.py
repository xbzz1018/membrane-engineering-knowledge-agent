from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from src.api.dependencies import current_principal, rate_limited_principal
from src.application.authorization import ProjectAccessError
from src.application.catalogs import CatalogApplicationError, catalog_application
from src.core.security import Principal
from src.domain.schemas import (
    ArchiveRequest,
    MaterialSpecCreateRequest,
    MaterialSpecUpdateRequest,
    PriceRecordCreateRequest,
    PriceRecordUpdateRequest,
)

router = APIRouter(prefix="/api/v1", tags=["膜材与历史价格台账"])


def _error(exc: Exception) -> HTTPException:
    code = getattr(exc, "code", "")
    return HTTPException(
        status_code={"not_found": 404, "forbidden": 403, "conflict": 409, "invalid": 422}.get(code, 400),
        detail=str(exc),
    )


@router.get("/material-specs", summary="查询企业膜材规格台账")
async def list_material_specs(
    project_id: str = Query(description="用于权限校验的项目ID"),
    query: str = Query(default="", max_length=256),
    status: str = Query(default="active", pattern="^(active|archived)?$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    principal: Principal = Depends(current_principal),
) -> dict:
    try:
        return await catalog_application.list_specs(principal, project_id, query, status, page, page_size)
    except (ProjectAccessError, CatalogApplicationError) as exc:
        raise _error(exc) from exc


@router.get("/material-specs/{spec_id}", summary="查看膜材规格详情")
async def get_material_spec(
    spec_id: str,
    project_id: str = Query(description="用于权限校验的项目ID"),
    principal: Principal = Depends(current_principal),
) -> dict:
    try:
        return await catalog_application.get_spec(principal, project_id, spec_id)
    except (ProjectAccessError, CatalogApplicationError) as exc:
        raise _error(exc) from exc


@router.post("/material-specs", status_code=201, summary="新增膜材规格")
async def create_material_spec(
    request: MaterialSpecCreateRequest,
    project_id: str = Query(description="用于权限校验的项目ID"),
    principal: Principal = Depends(rate_limited_principal),
) -> dict:
    try:
        return await catalog_application.create_spec(principal, project_id, request)
    except (ProjectAccessError, CatalogApplicationError) as exc:
        raise _error(exc) from exc


@router.patch("/material-specs/{spec_id}", summary="更新膜材规格")
async def update_material_spec(
    spec_id: str,
    request: MaterialSpecUpdateRequest,
    project_id: str = Query(description="用于权限校验的项目ID"),
    principal: Principal = Depends(rate_limited_principal),
) -> dict:
    try:
        return await catalog_application.update_spec(principal, project_id, spec_id, request)
    except (ProjectAccessError, CatalogApplicationError) as exc:
        raise _error(exc) from exc


@router.post("/material-specs/{spec_id}/archive", summary="归档膜材规格")
async def archive_material_spec(
    spec_id: str,
    request: ArchiveRequest,
    project_id: str = Query(description="用于权限校验的项目ID"),
    principal: Principal = Depends(rate_limited_principal),
) -> dict:
    try:
        return await catalog_application.archive_spec(
            principal, project_id, spec_id, request.expected_lock_version,
        )
    except (ProjectAccessError, CatalogApplicationError) as exc:
        raise _error(exc) from exc


@router.get("/price-records", summary="查询历史价格台账")
async def list_price_records(
    project_id: str = Query(description="项目ID"),
    query: str = Query(default="", max_length=256),
    status: str = Query(default="active", pattern="^(active|archived)?$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    principal: Principal = Depends(current_principal),
) -> dict:
    try:
        return await catalog_application.list_prices(principal, project_id, query, status, page, page_size)
    except (ProjectAccessError, CatalogApplicationError) as exc:
        raise _error(exc) from exc


@router.get("/price-records/{price_id}", summary="查看历史价格详情")
async def get_price_record(
    price_id: str,
    project_id: str = Query(description="项目ID"),
    principal: Principal = Depends(current_principal),
) -> dict:
    try:
        return await catalog_application.get_price(principal, project_id, price_id)
    except (ProjectAccessError, CatalogApplicationError) as exc:
        raise _error(exc) from exc


@router.post("/price-records", status_code=201, summary="新增历史价格")
async def create_price_record(
    request: PriceRecordCreateRequest,
    project_id: str = Query(description="项目ID"),
    principal: Principal = Depends(rate_limited_principal),
) -> dict:
    try:
        return await catalog_application.create_price(principal, project_id, request)
    except (ProjectAccessError, CatalogApplicationError) as exc:
        raise _error(exc) from exc


@router.patch("/price-records/{price_id}", summary="更新历史价格")
async def update_price_record(
    price_id: str,
    request: PriceRecordUpdateRequest,
    project_id: str = Query(description="项目ID"),
    principal: Principal = Depends(rate_limited_principal),
) -> dict:
    try:
        return await catalog_application.update_price(principal, project_id, price_id, request)
    except (ProjectAccessError, CatalogApplicationError) as exc:
        raise _error(exc) from exc


@router.post("/price-records/{price_id}/archive", summary="归档历史价格")
async def archive_price_record(
    price_id: str,
    request: ArchiveRequest,
    project_id: str = Query(description="项目ID"),
    principal: Principal = Depends(rate_limited_principal),
) -> dict:
    try:
        return await catalog_application.archive_price(
            principal, project_id, price_id, request.expected_lock_version,
        )
    except (ProjectAccessError, CatalogApplicationError) as exc:
        raise _error(exc) from exc
