from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routers.chat import router as chat_router
from src.api.routers.documents import router as documents_router
from src.api.routers.reviews import router as reviews_router
from src.core.config import get_settings
from src.engineering.bootstrap import seed_local_data
from src.engineering.storage import storage


@asynccontextmanager
async def lifespan(app: FastAPI):
    await storage.init()
    await seed_local_data(storage)
    yield
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
    return app


app = create_app()


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": get_settings().APP_NAME}


@app.get("/health/deps")
async def health_deps() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "runtime_mode": settings.RUNTIME_MODE,
        "model": {"mode": settings.MODEL_MODE, "provider": settings.MODEL_PROVIDER},
        "optional": {
            "mineru": bool(settings.MINERU_EXECUTABLE),
            "deepagents": settings.DEEPAGENTS_ENABLED,
            "temporal": settings.TEMPORAL_ENABLED,
            "kafka": settings.KAFKA_ENABLED,
        },
    }
