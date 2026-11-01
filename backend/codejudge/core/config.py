from __future__ import annotations

import os
import socket
from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    APP_NAME: str = "CodeJudge"
    APP_ENV: Literal["dev", "prod", "test"] = "dev"
    DATABASE_URL: str = Field(
        default="postgresql+psycopg://postgres:postgres@localhost:5432/codejudge",
        validation_alias=AliasChoices("DATABASE_URL", "POSTGRES_URL"),
    )
    REDIS_URL: str = "redis://localhost:6379/0"
    BROKER_URL: str = "amqp://guest:guest@localhost:5672//"
    JWT_SECRET: str = "change-me-in-production-please-use-long-enough-key"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    RATE_LIMIT_PER_MINUTE: int = 60
    BATCH_MAX_ITEMS: int = 500
    BATCH_RATE_PER_HOUR: int = 20
    MAX_ACTIVE_SUBMISSIONS_PER_USER: int = 1000
    BATCH_REQUEST_MAX_BYTES: int = 20 * 1024 * 1024
    BATCH_STALE_PENDING_SECONDS: int = 120
    WORKER_CONCURRENCY: int = Field(default_factory=lambda: min(os.cpu_count() or 1, 4), ge=1)
    MAX_PARALLEL_CONTAINERS: int = Field(default_factory=lambda: (os.cpu_count() or 1) * 2, ge=1)
    WORKER_HOST_ID: str = Field(default_factory=socket.gethostname)
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    SANDBOX_WORKDIR: str = "/tmp/codejudge"
    SANDBOX_RUNTIME: str = ""
    STOP_ON_FIRST_FAIL: bool = True
    POSTGRES_DB: str = "codejudge"
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    API_PREFIX: str = "/api"
    FRONTEND_ORIGIN: str = "http://localhost:5173"
    CORS_ALLOW_ORIGINS: str = "http://localhost:5173"


@lru_cache
def get_settings() -> Settings:
    return Settings()
