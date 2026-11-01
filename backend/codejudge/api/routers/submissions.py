from __future__ import annotations

import uuid
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from codejudge.core.config import get_settings
from codejudge.core.db import get_db
from codejudge.core.enums import SubmissionStatus
from codejudge.core.models import Problem, RunResult, Submission, TestCase, User
from codejudge.worker.celery_app import celery_app

from ..deps import get_current_user
from ..ratelimit import check_rate_limit
from ..schemas import SubmissionCreateRequest, SubmissionResponse

router = APIRouter(prefix="/submissions", tags=["submissions"])
settings = get_settings()
logger = logging.getLogger(__name__)


@router.post("", response_model=SubmissionResponse, status_code=status.HTTP_202_ACCEPTED)
def create_submission(payload: SubmissionCreateRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> SubmissionResponse:
    allowed, retry_after = check_rate_limit(str(user.id), settings.RATE_LIMIT_PER_MINUTE)
    if not allowed:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Rate limit exceeded", headers={"Retry-After": str(retry_after)})
    problem = db.query(Problem).filter(Problem.id == payload.problem_id).first()
    if problem is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Problem not found")
    if not payload.source_code or len(payload.source_code.encode("utf-8")) > 65536:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid source code")
    submission = Submission(
        id=str(uuid.uuid4()),
        user_id=user.id,
        problem_id=problem.id,
        language_id=payload.language_id,
        source_code=payload.source_code,
        status=SubmissionStatus.PENDING.value,
        model_name=payload.model_name,
        sample_id=payload.sample_id,
    )
    db.add(submission)
    db.commit()
    db.refresh(submission)
    try:
        celery_app.send_task(
            "codejudge.worker.tasks.evaluate_submission",
            args=[submission.id],
        )
    except Exception as exc:
        logger.error("Could not enqueue submission %s", submission.id)
        submission.status = SubmissionStatus.ERROR.value
        submission.detail = "Submission could not be queued"
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Submission queue is unavailable",
        ) from exc
    return SubmissionResponse(id=submission.id, status=submission.status)


@router.get("/{submission_id}")
def get_submission(submission_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    submission = db.query(Submission).filter(Submission.id == submission_id).first()
    if submission is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found")
    if submission.user_id != user.id and user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    results = (
        db.query(RunResult, TestCase.ordinal)
        .join(TestCase, RunResult.test_case_id == TestCase.id)
        .filter(RunResult.submission_id == submission.id)
        .order_by(TestCase.ordinal)
        .all()
    )
    return {
        "id": submission.id,
        "user_id": submission.user_id,
        "problem_id": submission.problem_id,
        "language_id": submission.language_id,
        "status": submission.status,
        "verdict": submission.verdict,
        "detail": submission.detail,
        "max_time_ms": submission.max_time_ms,
        "max_memory_kb": submission.max_memory_kb,
        "test_results": [
            {
                "ordinal": ordinal,
                "verdict": result.verdict,
                "wall_ms": result.wall_ms,
                "cpu_ms": result.cpu_ms,
                "memory_kb": result.memory_kb,
                "exit_code": result.exit_code,
            }
            for result, ordinal in results
        ],
    }


@router.get("")
def list_submissions(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    items = (
        db.query(Submission)
        .filter(Submission.user_id == user.id)
        .order_by(Submission.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [{
        "id": item.id,
        "problem_id": item.problem_id,
        "status": item.status,
        "verdict": item.verdict,
        "created_at": item.created_at,
    } for item in items]
