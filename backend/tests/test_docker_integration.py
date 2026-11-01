from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator, cast
from uuid import uuid4

import docker
import pytest
from docker.errors import DockerException, ImageNotFound
import redis
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from codejudge.core.db import Base
from codejudge.core.enums import BatchStatus, SubmissionStatus
from codejudge.core.models import Batch, Problem, Submission, TestCase, User
from codejudge.worker import sandbox, tasks


@pytest.fixture
def docker_client() -> Iterator[docker.DockerClient]:
    try:
        client = docker.from_env()
        client.ping()
        client.images.get("codejudge-py:1")
        client.images.get("codejudge-cpp:1")
    except (DockerException, ImageNotFound) as exc:
        if "client" in locals():
            client.close()
        pytest.skip(f"Docker daemon and codejudge-py:1 are required: {exc}")
    try:
        yield client
    finally:
        client.close()


@pytest.mark.docker
@pytest.mark.parametrize(
    ("case_id", "language", "source", "expected_verdict", "time_limit_ms", "memory_limit_mb"),
    [
        (1, "python3", "print(sum(map(int, input().split())))", "AC", 500, 128),
        (2, "python3", "print(0)", "WA", 500, 128),
        (3, "python3", "raise RuntimeError('demo')", "RE", 500, 128),
        (4, "python3", "while True:\n    pass", "TLE", 500, 128),
        (5, "python3", "data = bytearray(128 * 1024 * 1024)\nprint(0)", "MLE", 500, 32),
        (
            6,
            "cpp17",
            "#include <iostream>\nint main() { long long a, b; std::cin >> a >> b; std::cout << a + b << '\\n'; }",
            "AC",
            1000,
            128,
        ),
    ],
)
def test_sandbox_executes_demo_verdict_cases(
    docker_client: docker.DockerClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    case_id: int,
    language: str,
    source: str,
    expected_verdict: str,
    time_limit_ms: int,
    memory_limit_mb: int,
) -> None:
    class Slot:
        live_count = 1

        def mark_running(self) -> int:
            return self.live_count

    @contextmanager
    def acquire(_redis_client: object, **_kwargs: object) -> Iterator[Slot]:
        yield Slot()

    class FakeRedis:
        pass

    monkeypatch.setattr(sandbox.container_semaphore, "acquire", acquire)
    code_dir = tmp_path / "code"
    code_dir.mkdir()
    filename = "main.py" if language == "python3" else "main.cpp"
    (code_dir / filename).write_text(source, encoding="utf-8")
    (code_dir / filename).chmod(0o644)

    result = sandbox.run_sandbox_command(
        language=language,
        code_path=str(code_dir),
        input_text="1 2\n",
        time_limit_ms=time_limit_ms,
        memory_limit_mb=memory_limit_mb,
        workdir=str(tmp_path),
        test_case_id=case_id,
        submission_id=str(uuid4()),
        docker_client=docker_client,
        redis_client=cast(redis.Redis, FakeRedis()),
    )

    verdict = tasks.classify_verdict(
        oom_killed=result["oom_killed"],
        timed_out=result["timed_out"],
        outer_watchdog=result["outer_watchdog"],
        exit_code=result["exit_code"],
        missing_meta=result["missing_meta"],
        actual_output=result["actual_output"],
        expected_output="3\n",
    )
    assert verdict == expected_verdict
    assert result["concurrent_containers"] == 1


@pytest.mark.docker
def test_demo_verdicts_through_real_worker_and_sandbox(
    docker_client: docker.DockerClient,
    monkeypatch: pytest.MonkeyPatch,
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
        def set(self, *_args: object, **_kwargs: object) -> bool:
            return True

        def eval(self, *_args: object, **_kwargs: object) -> int:
            return 1

        def close(self) -> None:
            return None

    class Slot:
        live_count = 1

        def mark_running(self) -> int:
            return self.live_count

    @contextmanager
    def acquire(_redis_client: object, **_kwargs: object) -> Iterator[Slot]:
        yield Slot()

    monkeypatch.setattr(tasks.redis.Redis, "from_url", lambda *_args, **_kwargs: FakeRedis())
    monkeypatch.setattr(sandbox.container_semaphore, "acquire", acquire)

    cases = [
        ("python-ac-1", "python3", "print(sum(map(int, input().split())))", "AC"),
        ("python-ac-2", "python3", "a, b = map(int, input().split())\nprint(a + b)", "AC"),
        (
            "cpp-ac-1",
            "cpp17",
            "#include <iostream>\nint main() { long long a, b; std::cin >> a >> b; std::cout << a + b << std::endl; }",
            "AC",
        ),
        (
            "cpp-ac-2",
            "cpp17",
            "#include <iostream>\nusing namespace std;\nint main() { int a, b; if (cin >> a >> b) cout << (a + b) << endl; }",
            "AC",
        ),
        ("wrong-answer", "python3", "print(0)", "WA"),
        ("runtime-error", "python3", "raise RuntimeError('demo runtime error')", "RE"),
        ("time-limit", "python3", "while True:\n    pass", "TLE"),
        *[
            (
                f"memory-limit-{index + 1:02d}",
                "python3",
                f"import mmap\nsize = {chunk_size} * 1024 * 1024\ndata = mmap.mmap(-1, size)\npopulate_write = getattr(mmap, 'MADV_POPULATE_WRITE', 23)\ntry:\n    data.madvise(populate_write)\nexcept (AttributeError, OSError):\n    pass\ndata[::4096] = bytes([{index + 1}]) * ((size + 4095) // 4096)",
                "MLE",
            )
            for index, chunk_size in enumerate((320, 352, 384, 416, 448, 480, 512, 544, 576, 608))
        ],
    ]
    submission_ids: dict[str, str] = {}
    with test_session_factory() as db:
        user = User(email="demo-verdicts@example.com", password_hash="hash")
        problem = Problem(
            title="Demo verdict verification",
            statement="Read two integers and print their sum.",
            time_limit_ms=1000,
            memory_limit_mb=256,
        )
        db.add_all([user, problem])
        db.flush()
        db.add(TestCase(problem_id=problem.id, ordinal=1, input="1 2\n", expected_output="3\n"))
        db.flush()
        for sample_id, language, source, _expected in cases:
            submission = Submission(
                user_id=user.id,
                problem_id=problem.id,
                language_id=language,
                source_code=source,
                sample_id=sample_id,
            )
            db.add(submission)
            db.flush()
            submission_ids[sample_id] = submission.id
        db.commit()

    sandbox_results: dict[str, dict[str, object]] = {}
    real_run_sandbox = tasks.run_sandbox_command

    def capture_sandbox_result(**kwargs: object) -> dict[str, object]:
        result = real_run_sandbox(**kwargs)
        sandbox_results[str(kwargs["submission_id"])] = result
        return result

    monkeypatch.setattr(tasks, "run_sandbox_command", capture_sandbox_result)
    actual_verdicts: dict[str, str] = {}
    details: dict[str, str | None] = {}
    for sample_id, _language, _source, _expected in cases:
        submission_id = submission_ids[sample_id]
        actual_verdicts[sample_id] = tasks.evaluate_submission.run(submission_id)
        with test_session_factory() as db:
            submission = db.get(Submission, submission_id)
            assert submission is not None
            details[sample_id] = submission.detail

    print(
        "Generated-style C++ sandbox diagnostics:",
        {
            sample_id: {
                "compile_stderr": sandbox_results[submission_ids[sample_id]]["stderr"],
                "detail": details[sample_id],
                "verdict": actual_verdicts[sample_id],
            }
            for sample_id in ("cpp-ac-1", "cpp-ac-2")
        },
    )
    print("Memory bomb sandbox diagnostics:", {
        sample_id: {
            "result": sandbox_results[submission_ids[sample_id]],
            "detail": details[sample_id],
        }
        for sample_id, *_ in cases
        if sample_id.startswith("memory-limit-")
    })
    assert actual_verdicts == {sample_id: expected for sample_id, _, _, expected in cases}
    assert all(details[sample_id] is None for sample_id in ("cpp-ac-1", "cpp-ac-2"))
    assert all(
        sandbox_results[submission_ids[sample_id]]["oom_killed"] is True
        for sample_id, *_ in cases
        if sample_id.startswith("memory-limit-")
    )
    engine.dispose()


@pytest.mark.docker
def test_sweeper_recovers_work_and_removes_orphan_after_worker_kill(
    docker_client: docker.DockerClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'worker-kill.db'}",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    test_session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(tasks, "SessionLocal", test_session_factory)
    monkeypatch.setattr(tasks.docker, "from_env", docker.from_env)
    monkeypatch.setattr(tasks, "cleanup_workdir", lambda *_args: None)

    class FakeRedis:
        def set(self, *_args: object, **_kwargs: object) -> bool:
            return True

        def exists(self, *_args: object) -> bool:
            return False

        def eval(self, *_args: object) -> int:
            return 1

        def close(self) -> None:
            return None

    class ProducerContext:
        def __enter__(self) -> str:
            return "shared"

        def __exit__(self, *_args: object) -> None:
            return None

    monkeypatch.setattr(tasks.redis.Redis, "from_url", lambda *_args, **_kwargs: FakeRedis())
    monkeypatch.setattr(tasks.celery_app, "producer_or_acquire", ProducerContext)
    monkeypatch.setattr(tasks.celery_app, "send_task", lambda *_args, **_kwargs: None)

    submission_id = str(uuid4())
    worker = docker_client.containers.run(
        "codejudge-py:1",
        command=["python", "-c", "import time; time.sleep(120)"],
        detach=True,
    )
    orphan = None
    try:
        orphan = docker_client.containers.run(
            "codejudge-py:1",
            command=["python", "-c", "import time; time.sleep(120)"],
            detach=True,
            labels={
                "codejudge.sandbox": "true",
                "codejudge.submission": submission_id,
                "codejudge.test_case": "1",
            },
        )
        worker.kill()
        with test_session_factory() as db:
            user = User(email="docker-recovery@example.com", password_hash="hash")
            problem = Problem(title="A+B", statement="Add numbers")
            db.add_all([user, problem])
            db.flush()
            batch = Batch(user_id=user.id, total=1, status="RUNNING")
            db.add(batch)
            db.flush()
            submission = Submission(
                id=submission_id,
                user_id=user.id,
                problem_id=problem.id,
                batch_id=batch.id,
                language_id="python3",
                source_code="print(1)",
                status=SubmissionStatus.RUNNING.value,
                started_at=datetime.now(timezone.utc) - timedelta(minutes=11),
            )
            db.add(submission)
            db.commit()
            batch_id = batch.id

        result = tasks.sweep_submissions.run()

        assert result["failed"] == 1
        assert result["finalized"] == 1
        with test_session_factory() as db:
            recovered = db.get(Submission, submission_id)
            finalized = db.get(Batch, batch_id)
            assert recovered is not None
            assert recovered.status == SubmissionStatus.ERROR.value
            assert "Worker lost" in (recovered.detail or "")
            assert finalized is not None
            assert finalized.status == BatchStatus.COMPLETED.value
        assert orphan.id not in {container.id for container in docker_client.containers.list(all=True)}
    finally:
        if orphan is not None:
            try:
                orphan.remove(force=True)
            except DockerException:
                pass
        try:
            worker.remove(force=True)
        except DockerException:
            pass
        engine.dispose()
