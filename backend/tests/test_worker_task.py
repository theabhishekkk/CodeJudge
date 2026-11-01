from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from pytest import MonkeyPatch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from codejudge.core.db import Base
from codejudge.core.models import Problem, RunResult, Submission, TestCase as Case, User
from codejudge.worker import tasks


def test_submission_task_grades_and_upserts_run_results(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    test_session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(tasks, "SessionLocal", test_session_factory)
    monkeypatch.setattr(tasks.settings, "SANDBOX_WORKDIR", str(tmp_path))

    def run_sandbox(**kwargs: object) -> dict[str, object]:
        return {
            "exit_code": 0,
            "oom_killed": False,
            "outer_watchdog": False,
            "timed_out": False,
            "missing_meta": False,
            "compile_error": False,
            "actual_output": "3\n",
            "stderr": "",
            "wall_ms": 4,
            "cpu_ms": 2,
            "memory_kb": 256,
        }

    monkeypatch.setattr(tasks, "run_sandbox_command", run_sandbox)
    submission_id = str(uuid4())
    with test_session_factory() as db:
        user = User(email="worker@example.com", password_hash="hash")
        problem = Problem(title="A+B", statement="Add numbers", time_limit_ms=1000)
        db.add_all([user, problem])
        db.flush()
        db.add(Case(problem_id=problem.id, ordinal=1, input="1 2\n", expected_output="3\n"))
        db.flush()
        db.add(
            Submission(
                id=submission_id,
                user_id=user.id,
                problem_id=problem.id,
                language_id="python3",
                source_code="print(sum(map(int, input().split())))",
            )
        )
        db.commit()

    assert tasks.evaluate_submission.run(submission_id) == "AC"
    with test_session_factory() as db:
        submission = db.get(Submission, submission_id)
        assert submission is not None
        assert submission.status == "COMPLETED"
        assert submission.verdict == "AC"
        assert db.query(RunResult).filter_by(submission_id=submission_id).count() == 1
        result = db.query(RunResult).filter_by(submission_id=submission_id).one()
        task_values = {
            "submission_id": submission_id,
            "test_case_id": result.test_case_id,
            "verdict": "AC",
            "wall_ms": 5,
            "cpu_ms": 2,
            "memory_kb": 300,
            "exit_code": 0,
        }
        tasks._upsert_run_result(db, task_values)
        db.expire_all()
        assert db.query(RunResult).filter_by(submission_id=submission_id).count() == 1
        assert db.query(RunResult).filter_by(submission_id=submission_id).one().wall_ms == 5

    engine.dispose()
