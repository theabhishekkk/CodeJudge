from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from contextlib import contextmanager
from typing import Any, Iterator
from uuid import uuid4

import docker
import redis
from celery import shared_task
from docker.errors import DockerException
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from codejudge.core.config import get_settings
from codejudge.core.db import SessionLocal
from codejudge.core.enums import BatchStatus, SubmissionStatus, Verdict
from codejudge.core.models import Batch, Problem, RunResult, Submission, TestCase
from codejudge.core.verdict import classify_verdict
from codejudge.worker.celery_app import celery_app

from .sandbox import run_sandbox_command
from .workdir import cleanup_workdir, create_submission_workdir

logger = logging.getLogger(__name__)
settings = get_settings()
WORKER_LEASE_SECONDS = 60
LEASE_RENEW_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('EXPIRE', KEYS[1], ARGV[2])
end
return 0
"""
LEASE_RELEASE_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""


def _upsert_run_result(db: Session, values: dict[str, Any]) -> None:
    dialect = db.get_bind().dialect.name
    insert = postgresql_insert if dialect == "postgresql" else sqlite_insert if dialect == "sqlite" else None
    if insert is None:
        result = (
            db.query(RunResult)
            .filter(
                RunResult.submission_id == values["submission_id"],
                RunResult.test_case_id == values["test_case_id"],
            )
            .first()
        )
        if result is None:
            db.add(RunResult(**values))
        else:
            for key, value in values.items():
                if key not in {"submission_id", "test_case_id"}:
                    setattr(result, key, value)
        db.commit()
        return

    update_values = {
        key: value
        for key, value in values.items()
        if key not in {"submission_id", "test_case_id"}
    }
    statement = insert(RunResult).values(**values).on_conflict_do_update(
        index_elements=["submission_id", "test_case_id"],
        set_=update_values,
    )
    db.execute(statement)
    db.commit()


@contextmanager
def _submission_worker_lease(client: redis.Redis, submission_id: str) -> Iterator[bool]:
    key = f"codejudge:submission-worker:{submission_id}"
    token = str(uuid4())
    acquired = bool(client.set(key, token, nx=True, ex=WORKER_LEASE_SECONDS))
    if not acquired:
        yield False
        return

    stopped = threading.Event()
    heartbeat_errors: list[Exception] = []

    def renew_lease() -> None:
        while not stopped.wait(WORKER_LEASE_SECONDS / 3):
            try:
                renewed = client.eval(
                    LEASE_RENEW_SCRIPT,
                    1,
                    key,
                    token,
                    WORKER_LEASE_SECONDS,
                )
                if not renewed:
                    heartbeat_errors.append(RuntimeError("Submission worker lease was lost"))
                    return
            except redis.RedisError as exc:
                heartbeat_errors.append(exc)
                logger.exception("Could not renew worker lease for submission %s", submission_id)
                return

    heartbeat = threading.Thread(target=renew_lease, name="submission-worker-lease", daemon=True)
    heartbeat.start()
    body_error: BaseException | None = None
    try:
        yield True
    except BaseException as exc:
        body_error = exc
        raise
    finally:
        stopped.set()
        heartbeat.join()
        try:
            client.eval(LEASE_RELEASE_SCRIPT, 1, key, token)
        except redis.RedisError:
            logger.exception("Could not release worker lease for submission %s", submission_id)
        if heartbeat_errors and body_error is None:
            raise RuntimeError("Submission worker lease was lost") from heartbeat_errors[0]


@shared_task(bind=True, name="codejudge.worker.tasks.evaluate_submission")
def evaluate_submission(self: Any, submission_id: str) -> str:
    db: Session = SessionLocal()
    redis_client = redis.Redis.from_url(settings.REDIS_URL)
    docker_client: docker.DockerClient | None = None
    workdir: Path | None = None
    try:
        with _submission_worker_lease(redis_client, submission_id) as lease_acquired:
            if not lease_acquired:
                return "already-running"

            submission = db.query(Submission).filter(Submission.id == submission_id).first()
            if submission is None:
                return "missing"
            if submission.status == SubmissionStatus.CANCELLED.value:
                return "cancelled"
            if submission.status == SubmissionStatus.COMPLETED.value:
                return "already-completed"

            now = datetime.now(timezone.utc)
            started = db.execute(
                update(Submission)
                .where(Submission.id == submission_id)
                .where(
                    Submission.status.in_(
                        (SubmissionStatus.PENDING.value, SubmissionStatus.RUNNING.value)
                    )
                )
                .values(
                    status=SubmissionStatus.RUNNING.value,
                    detail=None,
                    started_at=now,
                )
            )
            if started.rowcount != 1:
                db.rollback()
                return "not-pending"
            db.commit()

            problem = db.query(Problem).filter(Problem.id == submission.problem_id).first()
            if problem is None:
                db.execute(
                    update(Submission)
                    .where(Submission.id == submission_id)
                    .where(Submission.status == SubmissionStatus.RUNNING.value)
                    .values(
                        status=SubmissionStatus.ERROR.value,
                        detail="Problem not found",
                        finished_at=datetime.now(timezone.utc),
                    )
                )
                db.commit()
                return "missing-problem"

            tests = (
                db.query(TestCase)
                .filter(TestCase.problem_id == problem.id)
                .order_by(TestCase.ordinal)
                .all()
            )
            if not tests:
                raise RuntimeError("Problem has no test cases")

            docker_client = docker.from_env()
            workdir = Path(settings.SANDBOX_WORKDIR) / submission_id
            cleanup_workdir(workdir)
            workdir = create_submission_workdir(settings.SANDBOX_WORKDIR, submission_id)
            code_dir = workdir / "code"
            source_filename = "main.py" if submission.language_id == "python3" else "main.cpp"
            source_path = code_dir / source_filename
            source_path.write_text(submission.source_code, encoding="utf-8")
            source_path.chmod(0o644)

            max_time_ms = 0
            max_memory_kb = 0
            final_verdict = Verdict.AC.value
            final_detail: str | None = None
            for test in tests:
                result = run_sandbox_command(
                    language=submission.language_id,
                    code_path=str(code_dir),
                    input_text=test.input,
                    time_limit_ms=problem.time_limit_ms,
                    memory_limit_mb=problem.memory_limit_mb,
                    workdir=str(workdir),
                    test_case_id=test.id,
                    submission_id=submission_id,
                    docker_client=docker_client,
                    redis_client=redis_client,
                )
                verdict = classify_verdict(
                    oom_killed=result["oom_killed"],
                    timed_out=result["timed_out"],
                    outer_watchdog=result["outer_watchdog"],
                    exit_code=result["exit_code"],
                    missing_meta=result["missing_meta"],
                    actual_output=result["actual_output"],
                    expected_output=test.expected_output,
                )
                wall_ms = int(result["wall_ms"])
                cpu_ms = int(result["cpu_ms"])
                memory_kb = int(result["memory_kb"])
                max_time_ms = max(max_time_ms, wall_ms)
                max_memory_kb = max(max_memory_kb, memory_kb)

                _upsert_run_result(
                    db,
                    {
                        "submission_id": submission_id,
                        "test_case_id": test.id,
                        "verdict": verdict,
                        "wall_ms": wall_ms,
                        "cpu_ms": cpu_ms,
                        "memory_kb": memory_kb,
                        "exit_code": int(result["exit_code"] if result["exit_code"] is not None else -1),
                        "concurrent_containers": int(result["concurrent_containers"]),
                    },
                )

                if verdict != Verdict.AC.value and final_verdict == Verdict.AC.value:
                    final_verdict = verdict
                    if result["compile_error"]:
                        final_detail = f"compile error: {result['stderr'][:4096]}"
                    elif verdict == Verdict.RE.value:
                        final_detail = "runtime error"
                    elif verdict == Verdict.TLE.value:
                        final_detail = "time limit exceeded"
                    elif verdict == Verdict.MLE.value:
                        final_detail = "memory limit exceeded"
                    if settings.STOP_ON_FIRST_FAIL:
                        break

            db.execute(
                update(Submission)
                .where(Submission.id == submission_id)
                .where(Submission.status == SubmissionStatus.RUNNING.value)
                .values(
                    status=SubmissionStatus.COMPLETED.value,
                    verdict=final_verdict,
                    detail=final_detail,
                    max_time_ms=max_time_ms,
                    max_memory_kb=max_memory_kb,
                    finished_at=datetime.now(timezone.utc),
                )
            )
            db.commit()
            return final_verdict
    except Exception:
        db.rollback()
        logger.exception("Submission evaluation failed for %s", submission_id)
        db.execute(
            update(Submission)
            .where(Submission.id == submission_id)
            .where(Submission.status == SubmissionStatus.RUNNING.value)
            .values(
                status=SubmissionStatus.ERROR.value,
                detail="Internal worker error",
                finished_at=datetime.now(timezone.utc),
            )
        )
        db.commit()
        return "error"
    finally:
        if workdir is not None:
            cleanup_workdir(workdir)
        if docker_client is not None:
            docker_client.close()
        redis_client.close()
        db.close()


@shared_task(name="codejudge.worker.tasks.sweep_submissions")
def sweep_submissions() -> dict[str, int | str]:
    redis_client = redis.Redis.from_url(settings.REDIS_URL)
    db: Session = SessionLocal()
    lock_key = "codejudge:sweeper:lock"
    lock_token = str(uuid4())
    acquired = False
    try:
        acquired = bool(redis_client.set(lock_key, lock_token, nx=True, ex=55))
        if not acquired:
            return {"status": "locked", "republished": 0, "failed": 0, "finalized": 0}

        now = datetime.now(timezone.utc)
        stale_pending_at = now.timestamp() - settings.BATCH_STALE_PENDING_SECONDS
        stale_pending = (
            db.query(Submission.id, Submission.batch_id)
            .filter(
                Submission.status == SubmissionStatus.PENDING.value,
                Submission.queued_at < datetime.fromtimestamp(stale_pending_at, timezone.utc),
            )
            .order_by(Submission.queued_at)
            .limit(settings.BATCH_MAX_ITEMS)
            .all()
        )
        stale_running_at = datetime.fromtimestamp(now.timestamp() - 600, timezone.utc)
        stale_running = (
            db.query(Submission.id)
            .filter(
                Submission.status == SubmissionStatus.RUNNING.value,
                Submission.started_at < stale_running_at,
            )
            .all()
        )
        failed_count = 0
        lost_worker_ids: list[str] = []
        for (submission_id,) in stale_running:
            worker_key = f"codejudge:submission-worker:{submission_id}"
            if redis_client.exists(worker_key):
                continue
            updated = db.execute(
                update(Submission)
                .where(
                    Submission.id == submission_id,
                    Submission.status == SubmissionStatus.RUNNING.value,
                    Submission.started_at < stale_running_at,
                )
                .values(
                    status=SubmissionStatus.ERROR.value,
                    detail="Worker lost while grading; marked ERROR by the recovery sweeper",
                    finished_at=now,
                )
            )
            failed_count += max(0, updated.rowcount or 0)
            if updated.rowcount:
                lost_worker_ids.append(submission_id)

        if lost_worker_ids:
            try:
                docker_client = docker.from_env()
                try:
                    for submission_id in lost_worker_ids:
                        containers = docker_client.containers.list(
                            all=True,
                            filters={
                                "label": [
                                    "codejudge.sandbox=true",
                                    f"codejudge.submission={submission_id}",
                                ]
                            },
                        )
                        for container in containers:
                            try:
                                container.remove(force=True)
                            except DockerException:
                                logger.exception(
                                    "Could not remove orphan sandbox for submission %s",
                                    submission_id,
                                )
                        cleanup_workdir(Path(settings.SANDBOX_WORKDIR) / submission_id)
                finally:
                    docker_client.close()
            except DockerException:
                logger.exception("Could not connect to Docker to clean orphan sandboxes")

        running_batches = db.query(Batch).filter(Batch.status == "RUNNING").all()
        running_batch_ids = [batch.id for batch in running_batches]
        active_batch_ids = {
            batch_id
            for (batch_id,) in (
                db.query(Submission.batch_id)
                .filter(
                    Submission.batch_id.in_(running_batch_ids),
                    Submission.status.in_(
                        (SubmissionStatus.PENDING.value, SubmissionStatus.RUNNING.value)
                    ),
                )
                .distinct()
                .all()
            )
        } if running_batch_ids else set()
        cancelled_batch_ids = {
            batch_id
            for (batch_id,) in (
                db.query(Submission.batch_id)
                .filter(
                    Submission.batch_id.in_(running_batch_ids),
                    Submission.status == SubmissionStatus.CANCELLED.value,
                )
                .distinct()
                .all()
            )
        } if running_batch_ids else set()
        finalized_count = 0
        for batch in running_batches:
            if batch.id in active_batch_ids:
                continue
            batch.status = (
                BatchStatus.CANCELLED.value
                if batch.id in cancelled_batch_ids
                else BatchStatus.COMPLETED.value
            )
            batch.finished_at = now
            finalized_count += 1
        db.commit()

        republished = 0
        if stale_pending:
            try:
                with celery_app.producer_or_acquire() as producer:
                    for submission_id, batch_id in stale_pending:
                        try:
                            celery_app.send_task(
                                "codejudge.worker.tasks.evaluate_submission",
                                args=[submission_id],
                                task_id=submission_id,
                                queue="codejudge",
                                priority=1 if batch_id else 5,
                                producer=producer,
                            )
                            republished += 1
                        except Exception:
                            logger.exception("Could not republish stale submission %s", submission_id)
            except Exception:
                logger.exception("Could not open a producer for stale submissions")
        return {
            "status": "completed",
            "republished": republished,
            "failed": failed_count,
            "finalized": finalized_count,
        }
    except Exception:
        db.rollback()
        logger.exception("Submission recovery sweep failed")
        raise
    finally:
        db.close()
        if acquired:
            try:
                redis_client.eval(LEASE_RELEASE_SCRIPT, 1, lock_key, lock_token)
            except redis.RedisError:
                logger.exception("Could not release submission recovery lock")
        redis_client.close()
