from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from codejudge.api.main import app
from codejudge.api.routers import batches
from codejudge.core.db import Base, get_db
from codejudge.core.enums import SubmissionStatus
from codejudge.api.security import create_access_token
from codejudge.core.models import Batch, Problem, Submission, TestCase as Case, User


@pytest.fixture
def batch_api(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, sessionmaker[Session], int, int, str]]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_get_db() -> Iterator[Session]:
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    with factory() as db:
        user = User(email=f"batch-{uuid4()}@example.com", password_hash="hash")
        problem = Problem(title="A+B", statement="Add numbers", time_limit_ms=1000)
        db.add_all([user, problem])
        db.flush()
        db.add(
            Case(
                problem_id=problem.id,
                ordinal=1,
                input="PRIVATE_HIDDEN_INPUT",
                expected_output="PRIVATE_EXPECTED_OUTPUT",
                is_hidden=True,
            )
        )
        db.commit()
        user_id, problem_id = user.id, problem.id

    token = create_access_token(user_id)
    monkeypatch.setattr(batches, "_check_batch_rate_limit", lambda _: (True, 0))
    monkeypatch.setattr(batches, "publish_batch_submissions", lambda _: None)
    try:
        with TestClient(app) as client:
            yield client, factory, user_id, problem_id, token
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _item(problem_id: int, *, sample_id: str = "case-1", code: str = "print(1)") -> dict[str, Any]:
    return {
        "problem_id": problem_id,
        "language_id": "python3",
        "source_code": code,
        "sample_id": sample_id,
    }


def test_batch_create_expands_repeats_and_publishes_ids(
    batch_api: tuple[TestClient, sessionmaker[Session], int, int, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, factory, user_id, problem_id, token = batch_api
    published: list[list[str]] = []
    monkeypatch.setattr(batches, "publish_batch_submissions", lambda ids: published.append(ids))

    response = client.post(
        "/api/batches",
        headers=_headers(token),
        json={"name": "benchmark", "model_name": "model-a", "repeats": 2, "items": [_item(problem_id)]},
    )

    assert response.status_code == 202, response.text
    assert response.json()["total"] == 2
    with factory() as db:
        batch = db.get(Batch, response.json()["id"])
        submissions = db.query(Submission).filter_by(batch_id=response.json()["id"]).order_by(Submission.repeat_index).all()
        assert batch is not None
        assert batch.total == 2
        assert [item.repeat_index for item in submissions] == [0, 1]
        assert all(item.status == "PENDING" for item in submissions)
        assert all(item.queued_at is not None for item in submissions)
        assert len(published) == 1
        assert published[0] == [item.id for item in submissions]


def test_batch_validation_is_all_or_nothing_and_reports_indexes(
    batch_api: tuple[TestClient, sessionmaker[Session], int, int, str],
) -> None:
    client, factory, _, problem_id, token = batch_api
    response = client.post(
        "/api/batches",
        headers=_headers(token),
        json={
            "items": [
                _item(problem_id),
                {"problem_id": 999_999, "language_id": "java", "source_code": ""},
            ]
        },
    )

    assert response.status_code == 422
    errors = response.json()["detail"]
    assert {error["index"] for error in errors} == {1}
    assert {error["field"] for error in errors} >= {"problem_id", "language_id", "source_code"}
    with factory() as db:
        assert db.query(Batch).count() == 0
        assert db.query(Submission).count() == 0


def test_batch_expanded_limit_and_active_limit_return_retry_headers(
    batch_api: tuple[TestClient, sessionmaker[Session], int, int, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, factory, user_id, problem_id, token = batch_api
    monkeypatch.setattr(batches.settings, "BATCH_MAX_ITEMS", 1)
    too_many = client.post(
        "/api/batches",
        headers=_headers(token),
        json={"repeats": 2, "items": [_item(problem_id)]},
    )
    assert too_many.status_code == 422
    with factory() as db:
        assert db.query(Batch).count() == 0
        db.add(
            Submission(
                id=str(uuid4()),
                user_id=user_id,
                problem_id=problem_id,
                language_id="python3",
                source_code="print(1)",
                status=SubmissionStatus.PENDING.value,
            )
        )
        db.commit()

    monkeypatch.setattr(batches.settings, "BATCH_MAX_ITEMS", 500)
    monkeypatch.setattr(batches.settings, "MAX_ACTIVE_SUBMISSIONS_PER_USER", 1)
    active_limit = client.post(
        "/api/batches",
        headers=_headers(token),
        json={"items": [_item(problem_id)]},
    )
    assert active_limit.status_code == 429
    assert active_limit.headers["retry-after"] == "60"
    with factory() as db:
        assert db.query(Batch).count() == 0


def test_batch_rate_limit_returns_retry_after(
    batch_api: tuple[TestClient, sessionmaker[Session], int, int, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _, _, problem_id, token = batch_api
    monkeypatch.setattr(batches, "_check_batch_rate_limit", lambda _: (False, 123))
    response = client.post(
        "/api/batches",
        headers=_headers(token),
        json={"items": [_item(problem_id)]},
    )

    assert response.status_code == 429
    assert response.headers["retry-after"] == "123"


def test_publish_uses_one_producer_and_sets_priority_and_task_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ProducerContext:
        def __init__(self) -> None:
            self.open_count = 0

        def __enter__(self) -> str:
            self.open_count += 1
            return "shared-producer"

        def __exit__(self, *_: object) -> None:
            return None

    context = ProducerContext()
    published: list[dict[str, Any]] = []
    monkeypatch.setattr(batches.celery_app, "producer_or_acquire", lambda: context)
    monkeypatch.setattr(
        batches.celery_app,
        "send_task",
        lambda task_name, **kwargs: published.append({"task_name": task_name, **kwargs}),
    )
    ids = [str(uuid4()), str(uuid4())]

    batches.publish_batch_submissions(ids)

    assert context.open_count == 1
    assert [task["task_id"] for task in published] == ids
    assert [task["priority"] for task in published] == [1, 1]
    assert all(task["producer"] == "shared-producer" for task in published)


def test_batch_summary_items_and_csv_never_expose_hidden_tests(
    batch_api: tuple[TestClient, sessionmaker[Session], int, int, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, factory, _, problem_id, token = batch_api
    created = client.post(
        "/api/batches",
        headers=_headers(token),
        json={"items": [_item(problem_id)]},
    )
    batch_id = created.json()["id"]
    with factory() as db:
        submission = db.query(Submission).filter_by(batch_id=batch_id).one()
        submission.status = SubmissionStatus.COMPLETED.value
        submission.verdict = "AC"
        db.commit()

    summary = client.get(f"/api/batches/{batch_id}", headers=_headers(token))
    items = client.get(f"/api/batches/{batch_id}/items", headers=_headers(token))
    export = client.get(f"/api/batches/{batch_id}/export.csv", headers=_headers(token))
    assert summary.status_code == 200
    assert summary.json()["counts"]["COMPLETED"] == 1
    assert items.status_code == 200
    assert "PRIVATE_HIDDEN_INPUT" not in summary.text + items.text + export.text
    assert "PRIVATE_EXPECTED_OUTPUT" not in summary.text + items.text + export.text
    assert export.text.splitlines()[0].split(",") == list(batches.CSV_COLUMNS)
    assert "source_code" not in items.text


def test_batch_owner_or_admin_access(
    batch_api: tuple[TestClient, sessionmaker[Session], int, int, str],
) -> None:
    client, factory, _, problem_id, token = batch_api
    created = client.post(
        "/api/batches",
        headers=_headers(token),
        json={"items": [_item(problem_id)]},
    )
    batch_id = created.json()["id"]
    with factory() as db:
        other_user = User(email="other@example.com", password_hash="hash")
        db.add(other_user)
        db.commit()
        other_token = create_access_token(other_user.id)

    assert client.get(f"/api/batches/{batch_id}", headers=_headers(other_token)).status_code == 403
    assert client.get(f"/api/batches/{uuid4()}", headers=_headers(token)).status_code == 404
    assert client.get(f"/api/batches/{batch_id}").status_code == 401


def test_cancel_marks_pending_and_keeps_running_submissions(
    batch_api: tuple[TestClient, sessionmaker[Session], int, int, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, factory, _, problem_id, token = batch_api
    created = client.post(
        "/api/batches",
        headers=_headers(token),
        json={"items": [_item(problem_id), _item(problem_id, sample_id="case-2")]},
    )
    batch_id = created.json()["id"]
    with factory() as db:
        submissions = db.query(Submission).filter_by(batch_id=batch_id).order_by(Submission.created_at).all()
        submissions[0].status = SubmissionStatus.RUNNING.value
        db.commit()
    revoked: list[str] = []
    monkeypatch.setattr(batches.celery_app.control, "revoke", lambda task_id, terminate: revoked.append(task_id))

    response = client.post(f"/api/batches/{batch_id}/cancel", headers=_headers(token))

    assert response.status_code == 200
    assert response.json()["status"] == "RUNNING"
    assert response.json()["cancelled"] == 1
    assert response.json()["running"] == 1
    assert len(revoked) == 1
    with factory() as db:
        statuses = {item.status for item in db.query(Submission).filter_by(batch_id=batch_id).all()}
        assert statuses == {"RUNNING", "CANCELLED"}


def test_rerun_failed_creates_a_new_batch_with_only_failures(
    batch_api: tuple[TestClient, sessionmaker[Session], int, int, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, factory, _, problem_id, token = batch_api
    created = client.post(
        "/api/batches",
        headers=_headers(token),
        json={"model_name": "model-a", "items": [_item(problem_id), _item(problem_id, sample_id="pass")]},
    )
    batch_id = created.json()["id"]
    with factory() as db:
        submissions = db.query(Submission).filter_by(batch_id=batch_id).order_by(Submission.created_at).all()
        submissions[0].status = SubmissionStatus.COMPLETED.value
        submissions[0].verdict = "WA"
        submissions[1].status = SubmissionStatus.COMPLETED.value
        submissions[1].verdict = "AC"
        db.commit()
    published: list[list[str]] = []
    monkeypatch.setattr(batches, "publish_batch_submissions", lambda ids: published.append(ids))

    response = client.post(f"/api/batches/{batch_id}/rerun-failed", headers=_headers(token))

    assert response.status_code == 202, response.text
    assert response.json()["total"] == 1
    with factory() as db:
        rerun = db.query(Batch).filter(Batch.id != batch_id).one()
        rerun_submission = db.query(Submission).filter_by(batch_id=rerun.id).one()
        assert rerun.model_name == "model-a"
        assert rerun_submission.sample_id != "pass"
        assert rerun_submission.source_code == "print(1)"
        assert len(published[0]) == 1


def test_items_support_filter_and_optional_code(
    batch_api: tuple[TestClient, sessionmaker[Session], int, int, str],
) -> None:
    client, _, _, problem_id, token = batch_api
    created = client.post(
        "/api/batches",
        headers=_headers(token),
        json={"items": [_item(problem_id, code="print('shown')")]},
    )
    batch_id = created.json()["id"]

    hidden_code = client.get(
        f"/api/batches/{batch_id}/items",
        headers=_headers(token),
        params={"language_id": "python3", "status": "PENDING"},
    )
    included_code = client.get(
        f"/api/batches/{batch_id}/items",
        headers=_headers(token),
        params={"include_code": "true"},
    )

    assert hidden_code.status_code == 200
    assert "source_code" not in hidden_code.text
    assert included_code.json()["items"][0]["source_code"] == "print('shown')"
