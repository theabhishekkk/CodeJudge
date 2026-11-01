from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from celery import shared_task
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from codejudge.core.config import get_settings
from codejudge.core.db import SessionLocal
from codejudge.core.enums import SubmissionStatus, Verdict
from codejudge.core.models import Problem, RunResult, Submission, TestCase
from codejudge.core.verdict import classify_verdict

from .sandbox import run_sandbox_command
from .workdir import cleanup_workdir, create_submission_workdir

logger = logging.getLogger(__name__)
settings = get_settings()


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


@shared_task(bind=True, name="codejudge.worker.tasks.evaluate_submission")
def evaluate_submission(self: Any, submission_id: str) -> str:
    db: Session = SessionLocal()
    workdir: Path | None = None
    try:
        submission = db.query(Submission).filter(Submission.id == submission_id).first()
        if submission is None:
            return "missing"
        if submission.status == SubmissionStatus.COMPLETED.value:
            return "already-completed"

        submission.status = SubmissionStatus.RUNNING.value
        submission.detail = None
        db.commit()

        problem = db.query(Problem).filter(Problem.id == submission.problem_id).first()
        if problem is None:
            db.execute(
                update(Submission)
                .where(Submission.id == submission_id)
                .where(Submission.status != SubmissionStatus.COMPLETED.value)
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
            .where(Submission.status != SubmissionStatus.COMPLETED.value)
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
        logger.error("Submission evaluation failed for %s", submission_id)
        db.execute(
            update(Submission)
            .where(Submission.id == submission_id)
            .where(Submission.status != SubmissionStatus.COMPLETED.value)
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
        db.close()
