from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routers.agents import router as agents_router
from src.api.routers.auth import router as auth_router
from src.api.routers.batch_imports import router as batch_imports_router
from src.api.routers.catalogs import router as catalogs_router
from src.api.routers.chat import router as chat_router
from src.api.routers.documents import router as documents_router
from src.api.routers.integrations import router as integrations_router
from src.api.routers.memories import router as memories_router
from src.api.routers.models import router as models_router
from src.api.routers.project_plans import router as project_plans_router
from src.api.routers.projects import router as projects_router
from src.api.routers.reviews import router as reviews_router
from src.api.routers.workflows import router as workflows_router
from src.core.config import get_settings
from src.core.observability import configure_telemetry
from src.infrastructure.bootstrap import seed_local_data
from src.infrastructure.database import storage
from src.infrastructure.health import dependency_health

OPENAPI_TAGS = [
    {"name": "身份与用户", "description": "企业用户登录、当前身份与管理员用户管理。"},
    {"name": "项目与权限", "description": "项目、成员、角色和Token/成本预算。"},
    {"name": "工程资料", "description": "资料上传、版本、MinerU/Office解析和EvidenceUnit。"},
    {"name": "项目知识问答", "description": "KnowledgeAgent项目级可追溯问答。"},
    {"name": "多智能体资料审查", "description": "检索与材料Agent并行取证，审查Agent按依赖复核原文。"},
    {"name": "智能体与执行轨迹", "description": "多智能体拓扑、Agent Run与安全步骤摘要。"},
    {"name": "长期记忆", "description": "用户/项目记忆候选、确认、更新和删除。"},
    {"name": "项目方案与文档", "description": "结构化初步方案、版本审查、人工批准和Markdown/Word导出。"},
    {"name": "批量资料导入", "description": "Temporal批量子工作流与SSE进度。"},
    {"name": "长任务工作流", "description": "工作流状态、批准、退回与取消。"},
    {"name": "模型能力", "description": "Chat、Embedding、Reranker策略和阿里模型目录。"},
    {"name": "膜材与历史价格台账", "description": "企业膜材规格和非报价性质的历史价格台账。"},
    {"name": "外部AI集成", "description": "MCP外部Agent接入状态与安全边界。"},
    {"name": "系统健康", "description": "服务存活与真实依赖探测。"},
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_telemetry()
    full_backends = None
    if settings.RUNTIME_MODE.lower() == "full":
        from src.infrastructure.full_backends import get_full_backends
        from src.infrastructure.redis_checkpoint import purge_legacy_short_memory

        full_backends = get_full_backends()
        await full_backends.initialize()
        await purge_legacy_short_memory(settings)
    await storage.init()
    await seed_local_data(storage)
    try:
        yield
    finally:
        if full_backends is not None:
            from src.infrastructure.redis_checkpoint import close_redis_checkpointers

            await close_redis_checkpointers()
            await full_backends.close()
        await storage.close()


def create_app() -> FastAPI:
    app = FastAPI(
        title="膜结构企业资料审查平台",
        summary="面向膜结构公司的多智能体工程资料审查后端",
        description=(
            "按项目隔离工程资料，使用KnowledgeAgent进行可追溯问答，并由检索、材料、审查三个业务智能体"
            "完成资料包审查、结构化问题跟踪与人工复核。"
        ),
        version="0.2.0",
        openapi_tags=OPENAPI_TAGS,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",
            "http://localhost:5173",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:5173",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(chat_router)
    app.include_router(auth_router)
    app.include_router(projects_router)
    app.include_router(project_plans_router)
    app.include_router(documents_router)
    app.include_router(catalogs_router)
    app.include_router(reviews_router)
    app.include_router(agents_router)
    app.include_router(memories_router)
    app.include_router(models_router)
    app.include_router(workflows_router)
    app.include_router(batch_imports_router)
    app.include_router(integrations_router)
    return app


app = create_app()


@app.get("/health", tags=["系统健康"], summary="检查API服务存活")
async def health() -> dict:
    return {"status": "ok", "service": get_settings().APP_NAME}


@app.get("/health/deps", tags=["系统健康"], summary="检查数据库、模型和基础设施依赖")
async def health_deps() -> dict:
    return await dependency_health()
