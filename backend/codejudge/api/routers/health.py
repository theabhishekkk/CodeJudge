from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from redis import Redis
from sqlalchemy import text

from codejudge.core.config import get_settings
from codejudge.core.db import SessionLocal
from codejudge.worker.celery_app import celery_app

settings = get_settings()
router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
def health_check() -> dict[str, str]:
    db = SessionLocal()
    redis_client = Redis.from_url(settings.REDIS_URL)
    try:
        db.execute(text("SELECT 1"))
        redis_client.ping()
        with celery_app.connection_for_read() as connection:
            connection.ensure_connection(max_retries=0)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="A required service is unavailable",
        ) from exc
    finally:
        db.close()
        redis_client.close()
    return {"status": "ok"}
