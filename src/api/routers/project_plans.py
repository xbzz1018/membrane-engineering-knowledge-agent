from __future__ import annotations

from collections.abc import Awaitable
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import Field

from src.agents.knowledge_agent import AgentProtocolError
from src.agents.review_agents import ReviewAgentError
from src.api.dependencies import rate_limited_principal
from src.application.authorization import ProjectAccessError
from src.application.project_plans import get_project_plan_service
from src.core.security import Principal
from src.documents.project_export import MIME
from src.domain.project_plan import (
    CreatePlanRequest,
    PlanDecisionRequest,
    PlanExportRequest,
    RevisionRequest,
    StrictModel,
)
from src.infrastructure.model_provider import ProviderConfigurationError, ProviderRequestError
from src.infrastructure.project_plan_repository import PlanConflict

router = APIRouter(tags=["项目方案与文档"])


@asynccontextmanager
async def plan_errors():
    try:
        yield
    except ProjectAccessError as exc:
        raise HTTPException(status_code=404 if exc.code == "not_found" else 403, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="方案、版本或产物不存在") from exc
    except PlanConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (AgentProtocolError, ReviewAgentError, ProviderConfigurationError, ProviderRequestError) as exc:
        raise HTTPException(status_code=502, detail="方案执行失败，未生成成功结果；请查看方案状态后重试") from exc
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail="方案取证超时，未生成成功结果，请查看方案状态") from exc


async def call_plan[T](operation: Awaitable[T]) -> T:
    async with plan_errors():
        return await operation


@router.get("/api/v1/projects/{project_id}/plans", summary="查询当前项目的方案")
async def list_plans(project_id: str, principal: Principal = Depends(rate_limited_principal)) -> list[dict]:
    service = get_project_plan_service()
    async with plan_errors():
        await service.authorization.authorize(principal, project_id)
        rows = await service.repo.list(principal.tenant_id, project_id)
        return [service.public(await service.repo.get(row["id"])) for row in rows]


@router.post("/api/v1/projects/{project_id}/plans", status_code=202, summary="创建需求并生成审查初步方案")
async def create_plan(project_id: str, request: CreatePlanRequest,
                      principal: Principal = Depends(rate_limited_principal)) -> dict:
    return await call_plan(get_project_plan_service().create(principal, project_id, request))


@router.get("/api/v1/plans/{plan_id}", summary="读取当前方案版本与审批状态")
async def get_plan(plan_id: str, principal: Principal = Depends(rate_limited_principal)) -> dict:
    service = get_project_plan_service()
    return service.public(await call_plan(service.authorize_plan(principal, plan_id)))


@router.get("/api/v1/plans/{plan_id}/versions/{version}", summary="读取指定方案版本")
async def get_plan_version(plan_id: str, version: int,
                           principal: Principal = Depends(rate_limited_principal)) -> dict:
    service = get_project_plan_service()
    return service.public(await call_plan(service.authorize_plan(principal, plan_id, version)))


@router.post("/api/v1/plans/{plan_id}/versions/{version}/generate", status_code=202, summary="恢复受理或重试失败的方案任务")
async def generate_plan(plan_id: str, version: int,
                         principal: Principal = Depends(rate_limited_principal)) -> dict:
    return await call_plan(get_project_plan_service().start(principal, plan_id, version))


@router.post("/api/v1/plans/{plan_id}/revisions", status_code=202, summary="修改形成新版本并重新审查")
async def revise_plan(plan_id: str, request: RevisionRequest,
                       principal: Principal = Depends(rate_limited_principal)) -> dict:
    return await call_plan(get_project_plan_service().revise(principal, plan_id, request))


@router.post("/api/v1/plans/{plan_id}/versions/{version}/decision", summary="对绑定审查的同版本方案批准或退回")
async def decide_plan(plan_id: str, version: int, request: PlanDecisionRequest,
                       principal: Principal = Depends(rate_limited_principal)) -> dict:
    return await call_plan(get_project_plan_service().decide(principal, plan_id, version, request))


@router.post("/api/v1/plans/{plan_id}/versions/{version}/exports", status_code=202, summary="导出当前批准版本的Markdown与Word")
async def export_plan(plan_id: str, version: int, request: PlanExportRequest,
                       principal: Principal = Depends(rate_limited_principal)) -> dict:
    return await call_plan(get_project_plan_service().export(principal, plan_id, version, request))


@router.get("/api/v1/plan-artifacts/{artifact_id}/download", summary="鉴权下载同版本批准产物")
async def download_plan(artifact_id: str, principal: Principal = Depends(rate_limited_principal)) -> Response:
    data, item = await call_plan(get_project_plan_service().download(principal, artifact_id))
    filename = f"project-plan-{item['plan_id']}-v{item['version']}.{item['format']}"
    return Response(data, media_type=MIME[item["format"]], headers={
        "Cache-Control": "no-store", "Content-Disposition": f'attachment; filename="{filename}"',
        "X-Content-SHA256": item["sha256"], "X-Plan-Version": str(item["version"]),
    })


class CancelPlanRequest(StrictModel):
    expected_lock_version: int = Field(ge=1)


@router.post("/api/v1/plans/{plan_id}/versions/{version}/cancel", summary="取消未提交决定的方案版本")
async def cancel_plan(plan_id: str, version: int, request: CancelPlanRequest,
                       principal: Principal = Depends(rate_limited_principal)) -> dict:
    return await call_plan(get_project_plan_service().cancel(principal, plan_id, version, request.expected_lock_version))
