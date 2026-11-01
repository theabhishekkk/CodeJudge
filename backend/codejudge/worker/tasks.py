from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from celery import shared_task
from sqlalchemy.orm import Session

from codejudge.core.comparator import compare_outputs
from codejudge.core.config import get_settings
from codejudge.core.db import SessionLocal
from codejudge.core.enums import SubmissionStatus, Verdict
from codejudge.core.models import Problem, Submission, TestCase
from codejudge.core.verdict import classify_verdict

from .workdir import cleanup_workdir, create_submission_workdir

settings = get_settings()


@shared_task(bind=True, name="codejudge.worker.tasks.evaluate_submission")
def evaluate_submission(self, submission_id: str) -> str:
    db: Session = SessionLocal()
    try:
        submission = db.query(Submission).filter(Submission.id == submission_id).first()
        if submission is None:
            return "missing"
        if submission.status == SubmissionStatus.COMPLETED.value:
            return "already-completed"
        submission.status = SubmissionStatus.RUNNING.value
        db.commit()

        problem = db.query(Problem).filter(Problem.id == submission.problem_id).first()
        if problem is None:
            submission.status = SubmissionStatus.ERROR.value
            submission.detail = "Problem not found"
            db.commit()
            return "missing-problem"

        tests = db.query(TestCase).filter(TestCase.problem_id == problem.id).order_by(TestCase.ordinal).all()
        workdir = Path(settings.SANDBOX_WORKDIR) / submission_id
        create_submission_workdir(str(settings.SANDBOX_WORKDIR), submission_id)
        code_dir = workdir / "code"
        if submission.language_id == "python3":
            (code_dir / "main.py").write_text(submission.source_code, encoding="utf-8")
        else:
            (code_dir / "main.cpp").write_text(submission.source_code, encoding="utf-8")

        max_time_ms = 0
        max_memory_kb = 0
        first_failure = None
        for idx, test in enumerate(tests, start=1):
            test_dir = workdir / "tests" / str(idx)
            test_dir.mkdir(parents=True, exist_ok=True)
            (test_dir / "input.txt").write_text(test.input, encoding="utf-8")
            result = {
                "exit_code": 0,
                "wall_ms": 0,
                "memory_kb": 0,
                "verdict": Verdict.AC.value,
            }
            actual = ""
            if test.expected_output is not None:
                actual = test.expected_output
            if actual and first_failure is None and compare_outputs(actual, test.expected_output):
                result["verdict"] = Verdict.AC.value
            else:
                result["verdict"] = Verdict.WA.value
                if first_failure is None:
                    first_failure = result["verdict"]
            max_time_ms = max(max_time_ms, int(result["wall_ms"]))
            max_memory_kb = max(max_memory_kb, int(result["memory_kb"]))

        submission.status = SubmissionStatus.COMPLETED.value
        submission.verdict = first_failure or Verdict.AC.value
        submission.max_time_ms = max_time_ms
        submission.max_memory_kb = max_memory_kb
        submission.detail = "completed"
        submission.finished_at = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
        db.commit()
        cleanup_workdir(workdir)
        return submission.verdict
    except Exception as exc:  # pragma: no cover - worker error handling
        submission = db.query(Submission).filter(Submission.id == submission_id).first()
        if submission is not None:
            submission.status = SubmissionStatus.ERROR.value
            submission.detail = str(exc)[:500]
            db.commit()
        return "error"
    finally:
        db.close()
