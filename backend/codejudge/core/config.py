from __future__ import annotations

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
