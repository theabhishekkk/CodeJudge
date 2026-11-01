from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from pytest import MonkeyPatch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from codejudge.core.db import Base
from codejudge.core.enums import SubmissionStatus
from codejudge.core.models import Batch, Problem, RunResult, Submission, TestCase as Case, User
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

    class FakeRedis:
        def set(self, *_: object, **__: object) -> bool:
            return True

        def eval(self, *_: object) -> int:
            return 1

        def close(self) -> None:
            return None

    class FakeDockerClient:
        def close(self) -> None:
            return None

    monkeypatch.setattr(tasks.redis.Redis, "from_url", lambda *_args, **_kwargs: FakeRedis())
    monkeypatch.setattr(tasks.docker, "from_env", lambda: FakeDockerClient())

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
            "concurrent_containers": 1,
        }

    monkeypatch.setattr(tasks, "run_sandbox_command", run_sandbox)
    submission_id = str(uuid4())
    cancelled_id = str(uuid4())
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
        db.add(
            Submission(
                id=cancelled_id,
                user_id=user.id,
                problem_id=problem.id,
                language_id="python3",
                source_code="print(1)",
                status=SubmissionStatus.CANCELLED.value,
            )
        )
        db.commit()

    assert tasks.evaluate_submission.run(submission_id) == "AC"
    assert tasks.evaluate_submission.run(submission_id) == "already-completed"
    assert tasks.evaluate_submission.run(cancelled_id) == "cancelled"
    with test_session_factory() as db:
        submission = db.get(Submission, submission_id)
        assert submission is not None
        assert submission.status == "COMPLETED"
        assert submission.verdict == "AC"
        assert submission.started_at is not None
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
        assert db.query(RunResult).filter_by(submission_id=submission_id).one().concurrent_containers == 1

    engine.dispose()


def test_sweeper_republishes_stale_work_marks_lost_workers_and_finalizes_batches(
    monkeypatch: MonkeyPatch,
) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    test_session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(tasks, "SessionLocal", test_session_factory)

    class FakeRedis:
        def set(self, *_: object, **__: object) -> bool:
            return True

        def exists(self, *_: object) -> bool:
            return False

        def eval(self, *_: object) -> int:
            return 1

        def close(self) -> None:
            return None

    class ProducerContext:
        def __enter__(self) -> str:
            return "shared"

        def __exit__(self, *_: object) -> None:
            return None

    class FakeDockerClient:
        class Containers:
            def list(self, **_: object) -> list[object]:
                return []

        containers = Containers()

        def close(self) -> None:
            return None

    monkeypatch.setattr(tasks.redis.Redis, "from_url", lambda *_args, **_kwargs: FakeRedis())
    monkeypatch.setattr(tasks.celery_app, "producer_or_acquire", ProducerContext)
    monkeypatch.setattr(tasks.docker, "from_env", lambda: FakeDockerClient())
    monkeypatch.setattr(tasks, "cleanup_workdir", lambda *_: None)
    published: list[dict[str, object]] = []
    monkeypatch.setattr(
        tasks.celery_app,
        "send_task",
        lambda task_name, **kwargs: published.append({"task_name": task_name, **kwargs}),
    )

    now = datetime.now(timezone.utc)
    with test_session_factory() as db:
        user = User(email="sweeper@example.com", password_hash="hash")
        problem = Problem(title="A+B", statement="Add numbers")
        db.add_all([user, problem])
        db.flush()
        active_batch = Batch(user_id=user.id, total=2, status="RUNNING")
        cancelled_batch = Batch(user_id=user.id, total=1, status="RUNNING")
        db.add_all([active_batch, cancelled_batch])
        db.flush()
        batch_pending = Submission(
            id=str(uuid4()),
            user_id=user.id,
            problem_id=problem.id,
            batch_id=active_batch.id,
            language_id="python3",
            source_code="print(1)",
            status=SubmissionStatus.PENDING.value,
            queued_at=now - timedelta(minutes=3),
        )
        lost_running = Submission(
            id=str(uuid4()),
            user_id=user.id,
            problem_id=problem.id,
            batch_id=active_batch.id,
            language_id="python3",
            source_code="print(1)",
            status=SubmissionStatus.RUNNING.value,
            started_at=now - timedelta(minutes=11),
        )
        single_pending = Submission(
            id=str(uuid4()),
            user_id=user.id,
            problem_id=problem.id,
            language_id="python3",
            source_code="print(1)",
            status=SubmissionStatus.PENDING.value,
            queued_at=now - timedelta(minutes=3),
        )
        cancelled_item = Submission(
            id=str(uuid4()),
            user_id=user.id,
            problem_id=problem.id,
            batch_id=cancelled_batch.id,
            language_id="python3",
            source_code="print(1)",
            status=SubmissionStatus.CANCELLED.value,
        )
        db.add_all([batch_pending, lost_running, single_pending, cancelled_item])
        db.commit()
        active_batch_id = active_batch.id
        cancelled_batch_id = cancelled_batch.id
        lost_running_id = lost_running.id

    result = tasks.sweep_submissions.run()

    assert result == {"status": "completed", "republished": 2, "failed": 1, "finalized": 1}
    assert {item["task_id"] for item in published} == {batch_pending.id, single_pending.id}
    assert {item["priority"] for item in published} == {1, 5}
    with test_session_factory() as db:
        lost = db.get(Submission, lost_running_id)
        assert lost is not None
        assert lost.status == SubmissionStatus.ERROR.value
        assert "Worker lost" in (lost.detail or "")
        assert db.get(Batch, active_batch_id).status == "RUNNING"
        finished_batch = db.get(Batch, cancelled_batch_id)
        assert finished_batch is not None
        assert finished_batch.status == "CANCELLED"
        assert finished_batch.finished_at is not None

    engine.dispose()
