from __future__ import annotations

import os

from pytest import MonkeyPatch

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
if os.path.exists("test.db"):
    os.remove("test.db")

from fastapi.testclient import TestClient

from codejudge.api.main import app
from codejudge.core.db import Base, engine
from codejudge.worker.celery_app import celery_app

Base.metadata.create_all(bind=engine)

client = TestClient(app)


def test_register_login_and_submit(monkeypatch: MonkeyPatch) -> None:
    queued: list[tuple[str, list[str]]] = []
    monkeypatch.setattr(
        celery_app,
        "send_task",
        lambda task_name, args: queued.append((task_name, args)),
    )
    reg = client.post("/api/auth/register", json={"email": "admin@example.com", "password": "secret123"})
    assert reg.status_code == 200, reg.text
    token = reg.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    problem = client.post(
        "/api/problems",
        json={"title": "Sum", "statement": "Add two numbers", "time_limit_ms": 1000, "memory_limit_mb": 128, "tests": [{"ordinal": 1, "input": "1 2\n", "expected_output": "3\n", "is_hidden": False}]},
        headers=headers,
    )
    assert problem.status_code in {200, 201}, problem.text

    submit = client.post(
        "/submissions",
        json={"problem_id": 1, "language_id": "python3", "source_code": "print(sum(map(int, input().split())))"},
        headers=headers,
    )
    assert submit.status_code == 202, submit.text
    assert "id" in submit.json()
    assert queued == [
        ("codejudge.worker.tasks.evaluate_submission", [submit.json()["id"]])
    ]
    details = client.get(f"/submissions/{submit.json()['id']}", headers=headers)
    assert details.status_code == 200
    assert "expected_output" not in details.text
    assert "input" not in details.text
