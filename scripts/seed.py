from __future__ import annotations

import os
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from codejudge.core.config import get_settings
from codejudge.core.models import Problem, TestCase, User
from codejudge.api.security import hash_password

settings = get_settings()
engine = create_engine(settings.DATABASE_URL)

PROBLEMS = [
    {
        "title": "A+B",
        "statement": "Read two integers and print their sum.",
        "time_limit_ms": 1000,
        "memory_limit_mb": 128,
        "tests": [
            ("1 2\n", "3\n", False),
            ("10 20\n", "30\n", False),
            ("-5 7\n", "2\n", True),
        ],
    },
    {
        "title": "Reverse String",
        "statement": "Reverse a string.",
        "time_limit_ms": 1000,
        "memory_limit_mb": 128,
        "tests": [
            ("abc\n", "cba\n", False),
            ("hello\n", "olleh\n", False),
            ("racecar\n", "racecar\n", True),
        ],
    },
]


def seed() -> None:
    with Session(engine) as db:
        user = db.query(User).filter(User.email == os.getenv("ADMIN_EMAIL", "admin@example.com")).first()
        if user is None:
            db.add(User(email=os.getenv("ADMIN_EMAIL", "admin@example.com"), password_hash=hash_password(os.getenv("ADMIN_PASSWORD", "admin123")), role="admin"))
        for problem_data in PROBLEMS:
            problem = db.query(Problem).filter(Problem.title == problem_data["title"]).first()
            if problem is None:
                problem = Problem(title=problem_data["title"], statement=problem_data["statement"], time_limit_ms=problem_data["time_limit_ms"], memory_limit_mb=problem_data["memory_limit_mb"])
                db.add(problem)
                db.flush()
            for ordinal, (inp, out, hidden) in enumerate(problem_data["tests"], start=1):
                if not db.query(TestCase).filter(TestCase.problem_id == problem.id, TestCase.ordinal == ordinal).first():
                    db.add(TestCase(problem_id=problem.id, ordinal=ordinal, input=inp, expected_output=out, is_hidden=hidden))
        db.commit()


if __name__ == "__main__":
    seed()
