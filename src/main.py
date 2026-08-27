from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routers.chat import router as chat_router
from src.api.routers.documents import router as documents_router
from src.api.routers.events import router as events_router
from src.api.routers.memories import router as memories_router
from src.api.routers.reviews import router as reviews_router
from src.api.routers.workflows import router as workflows_router
from src.core.config import get_settings
from src.engineering.bootstrap import load_local_data, seed_local_data
from src.engineering.health import dependency_health
from src.engineering.storage import storage


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    full_backends = None
    if settings.RUNTIME_MODE.lower() == "full":
        from src.engineering.full_backends import get_full_backends

        full_backends = get_full_backends()
        await full_backends.initialize()
    await storage.init()
    await seed_local_data(storage)
    if full_backends is not None:
        await full_backends.sync_graph_cases(load_local_data(storage)["cases"])
    try:
        yield
    finally:
        if full_backends is not None:
            from src.engineering.redis_checkpoint import get_redis_checkpointer

            await get_redis_checkpointer().aclose()
            await full_backends.close()
        await storage.close()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.APP_NAME, version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(chat_router)
    app.include_router(documents_router)
    app.include_router(reviews_router)
    app.include_router(memories_router)
    app.include_router(workflows_router)
    app.include_router(events_router)
    return app


app = create_app()


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": get_settings().APP_NAME}


@app.get("/health/deps")
async def health_deps() -> dict:
    return await dependency_health()
