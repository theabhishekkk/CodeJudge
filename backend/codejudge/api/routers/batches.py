from __future__ import annotations

import csv
import io
import logging
import math
import time
import uuid
from datetime import datetime, timezone
from statistics import median
from typing import Any, Iterable

import redis
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, func, insert, or_
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from codejudge.core.config import get_settings
from codejudge.core.db import get_db
from codejudge.core.enums import BatchStatus, Language, SubmissionStatus, Verdict
from codejudge.core.models import Batch, Problem, RunResult, Submission, User
from codejudge.worker.celery_app import celery_app

from ..deps import get_current_user
from ..schemas import BatchCreateRequest, BatchResponse

router = APIRouter(prefix="/batches", tags=["batches"])
settings = get_settings()
logger = logging.getLogger(__name__)
DETAIL_MAX_LENGTH = 4096
SOURCE_MAX_BYTES = 64 * 1024
TERMINAL_STATUSES = (
    SubmissionStatus.COMPLETED.value,
    SubmissionStatus.ERROR.value,
    SubmissionStatus.CANCELLED.value,
)
CSV_COLUMNS = (
    "batch_id",
    "submission_id",
    "model_name",
    "sample_id",
    "repeat_index",
    "problem_id",
    "language_id",
    "status",
    "verdict",
    "wall_ms",
    "cpu_ms",
    "memory_kb",
    "queued_at",
    "started_at",
    "finished_at",
    "detail",
)


def _check_batch_rate_limit(user_id: int) -> tuple[bool, int]:
    now = int(time.time())
    retry_after = 3600 - (now % 3600)
    key = f"codejudge:batch-rate:{user_id}:{now // 3600}"
    client = redis.Redis.from_url(settings.REDIS_URL)
    try:
        count = int(
            client.eval(
                "local n = redis.call('INCR', KEYS[1]); "
                "if n == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end; "
                "return n",
                1,
                key,
                3600,
            )
        )
    except redis.RedisError as exc:
        logger.exception("Batch rate limiter is unavailable")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Batch rate limiting is temporarily unavailable",
        ) from exc
    finally:
        client.close()
    return count <= settings.BATCH_RATE_PER_HOUR, retry_after


def _validate_items(payload: BatchCreateRequest, db: Session) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    errors: list[dict[str, Any]] = []
    normalized: list[dict[str, Any]] = []
    problem_ids: set[int] = set()
    supported_languages = {language.value for language in Language}

    for index, raw_item in enumerate(payload.items):
        if not isinstance(raw_item, dict):
            errors.append({"index": index, "field": "item", "message": "Item must be an object"})
            continue

        item: dict[str, Any] = {"index": index}
        problem_id = raw_item.get("problem_id")
        if isinstance(problem_id, bool) or not isinstance(problem_id, int) or problem_id < 1:
            errors.append({"index": index, "field": "problem_id", "message": "Must be a positive integer"})
        else:
            item["problem_id"] = problem_id
            problem_ids.add(problem_id)

        language_id = raw_item.get("language_id")
        if not isinstance(language_id, str) or language_id not in supported_languages:
            errors.append({"index": index, "field": "language_id", "message": "Unsupported language"})
        else:
            item["language_id"] = language_id

        source_code = raw_item.get("source_code")
        if not isinstance(source_code, str) or not source_code:
            errors.append({"index": index, "field": "source_code", "message": "Must be a non-empty string"})
        else:
            try:
                source_bytes = len(source_code.encode("utf-8"))
            except UnicodeEncodeError:
                source_bytes = SOURCE_MAX_BYTES + 1
            if source_bytes > SOURCE_MAX_BYTES:
                errors.append({"index": index, "field": "source_code", "message": "Must not exceed 64 KB"})
            else:
                item["source_code"] = source_code

        sample_id = raw_item.get("sample_id")
        if sample_id is not None and (not isinstance(sample_id, str) or len(sample_id) > 255):
            errors.append({"index": index, "field": "sample_id", "message": "Must be a string of at most 255 characters"})
        else:
            item["sample_id"] = sample_id

        normalized.append(item)

    if problem_ids:
        existing_ids = {
            problem_id
            for (problem_id,) in db.query(Problem.id).filter(Problem.id.in_(problem_ids)).all()
        }
        for item in normalized:
            problem_id = item.get("problem_id")
            if problem_id is not None and problem_id not in existing_ids:
                errors.append(
                    {
                        "index": item["index"],
                        "field": "problem_id",
                        "message": "Problem not found",
                    }
                )

    expanded_count = len(payload.items) * payload.repeats
    if expanded_count > settings.BATCH_MAX_ITEMS:
        errors.append(
            {
                "index": max(0, settings.BATCH_MAX_ITEMS // payload.repeats),
                "field": "items",
                "message": f"Expanded batch exceeds the {settings.BATCH_MAX_ITEMS}-submission limit",
            }
        )
    return normalized, errors


def publish_batch_submissions(submission_ids: list[str]) -> None:
    try:
        with celery_app.producer_or_acquire() as producer:
            for submission_id in submission_ids:
                try:
                    celery_app.send_task(
                        "codejudge.worker.tasks.evaluate_submission",
                        args=[submission_id],
                        task_id=submission_id,
                        queue="codejudge",
                        priority=1,
                        producer=producer,
                    )
                except Exception:
                    logger.exception("Could not publish batch submission %s", submission_id)
    except Exception:
        logger.exception("Could not open a producer for batch submissions")


def _create_batch(
    payload: BatchCreateRequest,
    db: Session,
    user: User,
) -> BatchResponse:
    normalized, errors = _validate_items(payload, db)
    if errors:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=errors,
        )

    allowed, retry_after = _check_batch_rate_limit(user.id)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Batch limit reached; try again in {retry_after} seconds",
            headers={"Retry-After": str(retry_after)},
        )

    active_count = (
        db.query(func.count(Submission.id))
        .filter(
            Submission.user_id == user.id,
            Submission.status.in_((SubmissionStatus.PENDING.value, SubmissionStatus.RUNNING.value)),
        )
        .scalar()
        or 0
    )
    expanded_count = len(normalized) * payload.repeats
    if active_count + expanded_count > settings.MAX_ACTIVE_SUBMISSIONS_PER_USER:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                "Active submission limit reached "
                f"({settings.MAX_ACTIVE_SUBMISSIONS_PER_USER}); wait for existing submissions to finish"
            ),
            headers={"Retry-After": "60"},
        )

    now = datetime.now(timezone.utc)
    batch_id = str(uuid.uuid4())
    submission_ids = [str(uuid.uuid4()) for _ in range(expanded_count)]
    rows: list[dict[str, Any]] = []
    task_index = 0
    for item in normalized:
        for repeat_index in range(payload.repeats):
            rows.append(
                {
                    "id": submission_ids[task_index],
                    "user_id": user.id,
                    "problem_id": item["problem_id"],
                    "batch_id": batch_id,
                    "language_id": item["language_id"],
                    "source_code": item["source_code"],
                    "status": SubmissionStatus.PENDING.value,
                    "model_name": payload.model_name,
                    "sample_id": item["sample_id"],
                    "repeat_index": repeat_index,
                    "created_at": now,
                    "queued_at": now,
                }
            )
            task_index += 1

    db.rollback()
    try:
        with db.begin():
            db.add(
                Batch(
                    id=batch_id,
                    user_id=user.id,
                    name=payload.name,
                    model_name=payload.model_name,
                    total=expanded_count,
                    status=BatchStatus.RUNNING.value,
                    created_at=now,
                )
            )
            db.flush()
            db.execute(insert(Submission), rows)
    except SQLAlchemyError as exc:
        db.rollback()
        logger.exception("Could not persist batch %s", batch_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Batch could not be saved",
        ) from exc

    publish_batch_submissions(submission_ids)
    return BatchResponse(id=batch_id, total=expanded_count, status=BatchStatus.RUNNING.value)


def _get_owned_batch(db: Session, user: User, batch_id: str) -> Batch:
    batch = db.query(Batch).filter(Batch.id == batch_id).first()
    if batch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Batch not found")
    if batch.user_id != user.id and user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    return batch


def _percentile(values: list[int], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return float(ordered[index])


def _metric_summary(db: Session, batch_id: str) -> tuple[list[int], list[int]]:
    rows = (
        db.query(RunResult.wall_ms, RunResult.memory_kb)
        .join(Submission, Submission.id == RunResult.submission_id)
        .filter(Submission.batch_id == batch_id)
        .all()
    )
    return [row.wall_ms for row in rows], [row.memory_kb for row in rows]


def _batch_summary(db: Session, batch: Batch) -> dict[str, Any]:
    grouped = (
        db.query(
            Submission.status,
            Submission.verdict,
            func.count(Submission.id),
            func.min(Submission.started_at),
        )
        .filter(Submission.batch_id == batch.id)
        .group_by(Submission.status, Submission.verdict)
        .all()
    )
    counts = {submission_status.value: 0 for submission_status in SubmissionStatus}
    verdicts: dict[str, int] = {}
    started_values: list[datetime] = []
    for row_status, verdict, count, first_started_at in grouped:
        counts[row_status] = counts.get(row_status, 0) + count
        if verdict:
            verdicts[verdict] = verdicts.get(verdict, 0) + count
        if first_started_at is not None:
            started_values.append(first_started_at)

    completed = counts.get(SubmissionStatus.COMPLETED.value, 0)
    terminal_count = sum(counts.get(value, 0) for value in TERMINAL_STATUSES)
    active_count = counts.get(SubmissionStatus.PENDING.value, 0) + counts.get(
        SubmissionStatus.RUNNING.value, 0
    )
    started_at = min(started_values) if started_values else None
    if started_at is not None and started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    end_time = batch.finished_at or now
    if end_time.tzinfo is None:
        end_time = end_time.replace(tzinfo=timezone.utc)
    elapsed_seconds = max(0.0, (end_time - started_at).total_seconds()) if started_at else 0.0
    processed_count = completed + counts.get(SubmissionStatus.ERROR.value, 0)
    throughput = processed_count / (elapsed_seconds / 60) if elapsed_seconds > 0 else 0.0
    eta_seconds = (
        active_count / throughput * 60
        if active_count > 0 and throughput > 0
        else 0.0 if active_count == 0 else None
    )
    wall_values, memory_values = _metric_summary(db, batch.id)
    return {
        "id": batch.id,
        "name": batch.name,
        "model_name": batch.model_name,
        "total": batch.total,
        "status": batch.status,
        "created_at": batch.created_at,
        "finished_at": batch.finished_at,
        "counts": counts,
        "verdicts": verdicts,
        "completed": completed,
        "percent": terminal_count / batch.total * 100 if batch.total else 0.0,
        "started_at": started_at,
        "throughput": throughput,
        "eta_seconds": eta_seconds,
        "max_wall_ms": max(wall_values, default=None),
        "median_wall_ms": float(median(wall_values)) if wall_values else None,
        "p95_wall_ms": _percentile(wall_values, 0.95),
        "max_memory_kb": max(memory_values, default=None),
        "median_memory_kb": float(median(memory_values)) if memory_values else None,
        "p95_memory_kb": _percentile(memory_values, 0.95),
    }


@router.post("", response_model=BatchResponse, status_code=status.HTTP_202_ACCEPTED)
def create_batch(
    payload: BatchCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> BatchResponse:
    return _create_batch(payload, db, user)


@router.get("")
def list_batches(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    batches = (
        db.query(Batch)
        .filter(Batch.user_id == user.id)
        .order_by(Batch.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    if not batches:
        total = db.query(func.count(Batch.id)).filter(Batch.user_id == user.id).scalar() or 0
        return {"items": [], "total": total, "limit": limit, "offset": offset}

    ids = [batch.id for batch in batches]
    grouped = (
        db.query(Submission.batch_id, Submission.status, Submission.verdict, func.count(Submission.id))
        .filter(Submission.batch_id.in_(ids))
        .group_by(Submission.batch_id, Submission.status, Submission.verdict)
        .all()
    )
    progress: dict[str, dict[str, Any]] = {}
    for batch_id, row_status, verdict, count in grouped:
        batch_progress = progress.setdefault(batch_id, {"counts": {}, "verdicts": {}})
        batch_progress["counts"][row_status] = batch_progress["counts"].get(row_status, 0) + count
        if verdict:
            batch_progress["verdicts"][verdict] = batch_progress["verdicts"].get(verdict, 0) + count
    return {
        "items": [
            {
                "id": batch.id,
                "name": batch.name,
                "model_name": batch.model_name,
                "total": batch.total,
                "status": batch.status,
                "created_at": batch.created_at,
                "finished_at": batch.finished_at,
                "counts": progress.get(batch.id, {}).get("counts", {}),
                "verdicts": progress.get(batch.id, {}).get("verdicts", {}),
            }
            for batch in batches
        ],
        "total": db.query(func.count(Batch.id)).filter(Batch.user_id == user.id).scalar() or 0,
        "limit": limit,
        "offset": offset,
    }


@router.get("/{batch_id}")
def get_batch(
    batch_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return _batch_summary(db, _get_owned_batch(db, user, batch_id))


@router.get("/{batch_id}/items")
def get_batch_items(
    batch_id: str,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    verdict: str | None = None,
    submission_status: str | None = Query(default=None, alias="status"),
    problem_id: int | None = None,
    language_id: str | None = None,
    sort: str = "created_at",
    include_code: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    batch = _get_owned_batch(db, user, batch_id)
    metrics = (
        db.query(
            RunResult.submission_id.label("submission_id"),
            func.max(RunResult.wall_ms).label("wall_ms"),
            func.max(RunResult.cpu_ms).label("cpu_ms"),
            func.max(RunResult.memory_kb).label("memory_kb"),
        )
        .group_by(RunResult.submission_id)
        .subquery()
    )
    query = (
        db.query(Submission, Problem.title, metrics.c.wall_ms, metrics.c.cpu_ms, metrics.c.memory_kb)
        .join(Problem, Problem.id == Submission.problem_id)
        .outerjoin(metrics, metrics.c.submission_id == Submission.id)
        .filter(Submission.batch_id == batch.id)
    )
    if verdict:
        query = query.filter(Submission.verdict == verdict)
    if submission_status:
        query = query.filter(Submission.status == submission_status)
    if problem_id is not None:
        query = query.filter(Submission.problem_id == problem_id)
    if language_id:
        query = query.filter(Submission.language_id == language_id)

    sort_desc = sort.startswith("-")
    sort_key = sort[1:] if sort_desc else sort
    sort_columns = {
        "created_at": Submission.created_at,
        "status": Submission.status,
        "verdict": Submission.verdict,
        "problem_id": Submission.problem_id,
        "language_id": Submission.language_id,
        "wall_ms": metrics.c.wall_ms,
        "memory_kb": metrics.c.memory_kb,
    }
    if sort_key not in sort_columns:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Unsupported sort field")
    sort_column = sort_columns[sort_key]
    query = query.order_by(sort_column.desc() if sort_desc else sort_column.asc())
    total = query.count()
    rows = query.offset(offset).limit(limit).all()

    items: list[dict[str, Any]] = []
    for submission, problem_title, wall_ms, cpu_ms, memory_kb in rows:
        item = {
            "id": submission.id,
            "problem_id": submission.problem_id,
            "problem_title": problem_title,
            "language_id": submission.language_id,
            "sample_id": submission.sample_id,
            "repeat_index": submission.repeat_index,
            "status": submission.status,
            "verdict": submission.verdict,
            "wall_ms": wall_ms,
            "cpu_ms": cpu_ms,
            "memory_kb": memory_kb,
            "detail": submission.detail[:DETAIL_MAX_LENGTH] if submission.detail else None,
            "created_at": submission.created_at,
            "queued_at": submission.queued_at,
            "started_at": submission.started_at,
            "finished_at": submission.finished_at,
        }
        if include_code:
            item["source_code"] = submission.source_code
        items.append(item)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/{batch_id}/export.csv")
def export_batch_csv(
    batch_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    batch = _get_owned_batch(db, user, batch_id)
    metrics = (
        db.query(
            RunResult.submission_id.label("submission_id"),
            func.max(RunResult.wall_ms).label("wall_ms"),
            func.max(RunResult.cpu_ms).label("cpu_ms"),
            func.max(RunResult.memory_kb).label("memory_kb"),
        )
        .group_by(RunResult.submission_id)
        .subquery()
    )
    rows = (
        db.query(Submission, metrics.c.wall_ms, metrics.c.cpu_ms, metrics.c.memory_kb)
        .outerjoin(metrics, metrics.c.submission_id == Submission.id)
        .filter(Submission.batch_id == batch.id)
        .order_by(Submission.created_at, Submission.id)
        .all()
    )
    exported = [
        {
            "batch_id": batch.id,
            "submission_id": submission.id,
            "model_name": submission.model_name,
            "sample_id": submission.sample_id,
            "repeat_index": submission.repeat_index,
            "problem_id": submission.problem_id,
            "language_id": submission.language_id,
            "status": submission.status,
            "verdict": submission.verdict,
            "wall_ms": wall_ms,
            "cpu_ms": cpu_ms,
            "memory_kb": memory_kb,
            "queued_at": submission.queued_at.isoformat() if submission.queued_at else None,
            "started_at": submission.started_at.isoformat() if submission.started_at else None,
            "finished_at": submission.finished_at.isoformat() if submission.finished_at else None,
            "detail": submission.detail[:DETAIL_MAX_LENGTH] if submission.detail else None,
        }
        for submission, wall_ms, cpu_ms, memory_kb in rows
    ]

    def generate_csv() -> Iterable[str]:
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        yield output.getvalue()
        output.seek(0)
        output.truncate(0)
        for row in exported:
            writer.writerow(row)
            yield output.getvalue()
            output.seek(0)
            output.truncate(0)

    return StreamingResponse(
        generate_csv(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="batch-{batch.id}.csv"'},
    )


@router.post("/{batch_id}/cancel")
def cancel_batch(
    batch_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    batch = _get_owned_batch(db, user, batch_id)
    pending_ids = [
        submission_id
        for (submission_id,) in db.query(Submission.id)
        .filter(
            Submission.batch_id == batch.id,
            Submission.status == SubmissionStatus.PENDING.value,
        )
        .all()
    ]
    now = datetime.now(timezone.utc)
    if pending_ids:
        (
            db.query(Submission)
            .filter(
                Submission.batch_id == batch.id,
                Submission.status == SubmissionStatus.PENDING.value,
            )
            .update(
                {
                    Submission.status: SubmissionStatus.CANCELLED.value,
                    Submission.finished_at: now,
                },
                synchronize_session=False,
            )
        )
    running_count = (
        db.query(func.count(Submission.id))
        .filter(
            Submission.batch_id == batch.id,
            Submission.status == SubmissionStatus.RUNNING.value,
        )
        .scalar()
        or 0
    )
    if running_count == 0 and batch.status == BatchStatus.RUNNING.value:
        batch.status = BatchStatus.CANCELLED.value
        batch.finished_at = now
    db.commit()
    for submission_id in pending_ids:
        try:
            celery_app.control.revoke(submission_id, terminate=False)
        except Exception:
            logger.exception("Could not revoke cancelled submission %s", submission_id)
    return {
        "id": batch.id,
        "status": batch.status,
        "cancelled": len(pending_ids),
        "running": running_count,
    }


@router.post("/{batch_id}/rerun-failed", response_model=BatchResponse, status_code=status.HTTP_202_ACCEPTED)
def rerun_failed_batch(
    batch_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> BatchResponse:
    batch = _get_owned_batch(db, user, batch_id)
    failed = (
        db.query(Submission)
        .filter(
            Submission.batch_id == batch.id,
            or_(
                Submission.status == SubmissionStatus.ERROR.value,
                and_(
                    Submission.status == SubmissionStatus.COMPLETED.value,
                    Submission.verdict.isnot(None),
                    Submission.verdict != Verdict.AC.value,
                ),
            ),
        )
        .order_by(Submission.created_at, Submission.id)
        .all()
    )
    if not failed:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Batch has no failed submissions to rerun")
    payload = BatchCreateRequest(
        name=f"{batch.name or 'Batch'} (rerun failed)",
        model_name=batch.model_name,
        items=[
            {
                "problem_id": item.problem_id,
                "language_id": item.language_id,
                "source_code": item.source_code,
                "sample_id": item.sample_id,
            }
            for item in failed
        ],
    )
    return _create_batch(payload, db, user)
