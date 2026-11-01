from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from codejudge.api.middleware import BatchRequestSizeLimitMiddleware
from codejudge.api.routers import auth, batches, health, problems, stats, submissions
from codejudge.core.config import get_settings

settings = get_settings()

app = FastAPI(title="CodeJudge", version="0.1.0")
app.add_middleware(
    BatchRequestSizeLimitMiddleware,
    path=f"{settings.API_PREFIX}/batches",
    max_bytes=settings.BATCH_REQUEST_MAX_BYTES,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.CORS_ALLOW_ORIGINS.split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(problems.router, prefix="/api")
app.include_router(batches.router, prefix="/api")
app.include_router(submissions.router, prefix="/api")
app.include_router(submissions.router)
app.include_router(stats.router, prefix="/api")


@app.get("/")
async def root() -> dict[str, str]:
    return {"message": "CodeJudge API"}
