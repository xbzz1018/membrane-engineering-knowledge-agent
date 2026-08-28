from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Configuration for the local-first engineering assistant."""

    APP_NAME: str = "membrane-engineering-knowledge-agent"
    APP_ENV: str = "dev"
    APP_DEBUG: bool = True
    RUNTIME_MODE: str = "local"

    AUTH_ENABLED: bool = False
    JWT_SECRET: str = "local-development-only-change-me"
    JWT_ALGORITHM: str = "HS256"
    JWT_TTL_MINUTES: int = Field(default=480, ge=5, le=10080)
    DEFAULT_TENANT_ID: str = "membrane-company"
    BOOTSTRAP_ADMIN_USERNAME: str = "admin"
    BOOTSTRAP_ADMIN_PASSWORD: str = "admin-change-me"
    DEFAULT_PROJECT_ID: str = "demo-project"

    MODEL_MODE: str = "fake"  # fake | api
    MODEL_PROVIDER: str = "auto"  # auto | dashscope | deepseek | gateway | fake
    DASHSCOPE_API_KEY: str = ""
    DASHSCOPE_API_BASE: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    DASHSCOPE_MODEL: str = ""
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_API_BASE: str = "https://api.deepseek.com"
    DEEPSEEK_MODEL: str = ""
    GATEWAY_API_KEY: str = ""
    GATEWAY_API_BASE: str = ""
    GATEWAY_MODEL: str = ""
    GATEWAY_EMBEDDING_MODEL: str = ""
    CHAT_MODEL: str = "deepseek-chat"
    EMBEDDING_PROVIDER: str = "auto"  # auto | embedding/local/custom/openai | dashscope | gateway | fake
    EMBEDDING_API_KEY: str = ""
    EMBEDDING_API_BASE: str = ""
    EMBEDDING_MODEL: str = "text-embedding-v3"
    EMBEDDING_DIMENSIONS: int = Field(default=1024, ge=1, le=65536)
    RERANKER_ENABLED: bool = False
    RERANKER_API_BASE: str = ""
    RERANKER_API_KEY: str = ""
    RERANKER_MODEL: str = "qwen3-rerank"
    RERANKER_TOP_N: int = Field(default=8, ge=1, le=100)
    MODEL_TEMPERATURE: float = Field(default=0.0, ge=0, le=2)
    MODEL_MAX_TOKENS: int = Field(default=2048, ge=128, le=16384)
    MODEL_CONTEXT_WINDOW: int = Field(default=32768, ge=4096, le=1048576)
    MODEL_TIMEOUT_SECONDS: int = Field(default=60, ge=5, le=600)
    MODEL_RETRY_ATTEMPTS: int = Field(default=2, ge=1, le=5)
    MODEL_RETRY_BACKOFF_SECONDS: float = Field(default=0.5, ge=0, le=10)

    LOCAL_DATA_PATH: str = "data/processed"
    LOCAL_UPLOAD_PATH: str = "data/uploads"
    LOCAL_DB_PATH: str = "data/runtime/engineering.db"

    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_USER: str = "engineering"
    DB_PASSWORD: str = "engineering123"
    DB_NAME: str = "engineering_db"
    DATABASE_URL: str = ""

    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 16379
    REDIS_PASSWORD: str = ""
    REDIS_DB: int = 0
    SHORT_TERM_MEMORY_TTL: int = Field(default=86400, ge=60, le=604800)

    MINIO_ENDPOINT: str = "localhost:19000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin"
    MINIO_BUCKET: str = "engineering-docs"
    MINIO_SECURE: bool = False
    MILVUS_HOST: str = "localhost"
    MILVUS_PORT: int = 19530
    MILVUS_DOCUMENT_COLLECTION: str = "engineering_document_chunks"
    MILVUS_MEMORY_COLLECTION: str = "engineering_long_term_memory"
    REDIS_CHECKPOINT_PREFIX: str = "membrane:checkpoint"
    API_RATE_LIMIT_PER_MINUTE: int = Field(default=60, ge=1, le=10000)

    PARSER_MODE: str = "basic"  # basic | mineru
    MINERU_EXECUTABLE: str = r"F:\code\homework\project\1_membrane_project_precheck\runtime\envs\mineru\Scripts\mineru.exe"
    MINERU_API_URL: str = ""
    MINERU_WORK_ROOT: str = r"F:\code\homework\model-cache\mineru"
    MINERU_TIMEOUT: int = Field(default=900, ge=30, le=3600)
    MINERU_BACKEND: str = "pipeline"
    MINERU_METHOD: str = "auto"
    MINERU_LANG: str = "ch"

    TEMPORAL_ENABLED: bool = False
    TEMPORAL_TARGET: str = "127.0.0.1:7233"
    TEMPORAL_NAMESPACE: str = "default"
    TEMPORAL_TASK_QUEUE: str = "membrane-engineering"
    TEMPORAL_PARSE_TASK_QUEUE: str = "membrane-document-parse"
    TEMPORAL_REVIEW_TASK_QUEUE: str = "membrane-agent-review"
    TEMPORAL_MAINTENANCE_TASK_QUEUE: str = "membrane-maintenance"
    TEMPORAL_ACTIVITY_TEST_DELAY_SECONDS: int = Field(default=0, ge=0, le=120)
    BATCH_DOCUMENT_LIMIT: int = Field(default=100, ge=1, le=500)
    BATCH_CHILD_CONCURRENCY: int = Field(default=5, ge=1, le=50)
    DEFAULT_DAILY_TOKEN_LIMIT: int = Field(default=1_000_000, ge=10_000)
    DEFAULT_MONTHLY_COST_LIMIT_MICROS: int = Field(default=100_000_000, ge=0)
    DEFAULT_MAX_CONCURRENT_REVIEWS: int = Field(default=3, ge=1, le=100)
    MODEL_ESTIMATED_COST_MICROS_PER_1K_TOKENS: int = Field(default=2000, ge=0)
    OTEL_ENABLED: bool = False
    OTEL_EXPORTER_OTLP_ENDPOINT: str = ""
    TRACE_CONTENT: bool = False
    HEALTHCHECK_TIMEOUT_SECONDS: float = Field(default=3.0, ge=0.2, le=30)

    LONG_TERM_MEMORY_ENABLED: bool = True
    LOG_LEVEL: str = "INFO"
    LOG_DIR: str = "logs"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )

    @computed_field
    @property
    def resolved_database_url(self) -> str:
        if self.DATABASE_URL:
            return self.DATABASE_URL
        db_path = (PROJECT_ROOT / self.LOCAL_DB_PATH).resolve()
        if self.RUNTIME_MODE.lower() == "local":
            db_path.parent.mkdir(parents=True, exist_ok=True)
            return f"sqlite+aiosqlite:///{db_path.as_posix()}"
        return (
            f"postgresql+asyncpg://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )

    @property
    def data_path(self) -> Path:
        path = Path(self.LOCAL_DATA_PATH)
        return path if path.is_absolute() else PROJECT_ROOT / path

    @property
    def upload_path(self) -> Path:
        path = Path(self.LOCAL_UPLOAD_PATH)
        return path if path.is_absolute() else PROJECT_ROOT / path


@lru_cache
def get_settings() -> Settings:
    return Settings()
