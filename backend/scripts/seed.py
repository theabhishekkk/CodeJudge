from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from codejudge.api.security import hash_password
from codejudge.core.config import get_settings
from codejudge.core.models import Problem, TestCase, User

settings = get_settings()
engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)

PROBLEMS: tuple[dict[str, object], ...] = (
    {
        "title": "A+B",
        "statement": "Read two integers and print their sum.",
        "time_limit_ms": 1000,
        "memory_limit_mb": 128,
        "tests": (
            ("1 2\n", "3\n", False),
            ("10 20\n", "30\n", False),
            ("-5 7\n", "2\n", True),
            ("1000000000 1000000000\n", "2000000000\n", True),
            ("-1000000000 -1000000000\n", "-2000000000\n", True),
        ),
    },
    {
        "title": "Sum of Array",
        "statement": "Read n followed by n integers and print their sum.",
        "time_limit_ms": 1000,
        "memory_limit_mb": 128,
        "tests": (
            ("0\n\n", "0\n", False),
            ("1\n5\n", "5\n", False),
            ("3\n1 2 3\n", "6\n", True),
            ("5\n-1 0 2 -3 4\n", "2\n", True),
            ("4\n100 200 300 400\n", "1000\n", True),
        ),
    },
    {
        "title": "Reverse String",
        "statement": "Reverse a string.",
        "time_limit_ms": 1000,
        "memory_limit_mb": 128,
        "tests": (
            ("abc\n", "cba\n", False),
            ("hello\n", "olleh\n", False),
            ("racecar\n", "racecar\n", True),
            ("a\n", "a\n", True),
            ("CodeJudge\n", "egduJedoC\n", True),
        ),
    },
    {
        "title": "Fibonacci Modulo",
        "statement": "Print the zero-indexed Fibonacci number F(n) modulo 1000000007.",
        "time_limit_ms": 2000,
        "memory_limit_mb": 128,
        "tests": (
            ("0\n", "0\n", False),
            ("1\n", "1\n", False),
            ("10\n", "55\n", True),
            ("100\n", "687995182\n", True),
            ("100000\n", "911435502\n", True),
        ),
    },
    {
        "title": "Prime Counting",
        "statement": "Count the prime numbers less than or equal to n.",
        "time_limit_ms": 2000,
        "memory_limit_mb": 128,
        "tests": (
            ("0\n", "0\n", False),
            ("10\n", "4\n", False),
            ("1\n", "0\n", True),
            ("2\n", "1\n", True),
            ("100\n", "25\n", True),
        ),
    },
    {
        "title": "Longest Increasing Subsequence",
        "statement": "Read n and n integers; print the length of a longest strictly increasing subsequence.",
        "time_limit_ms": 2000,
        "memory_limit_mb": 128,
        "tests": (
            ("0\n\n", "0\n", False),
            ("1\n5\n", "1\n", False),
            ("3\n1 2 3\n", "3\n", True),
            ("3\n3 2 1\n", "1\n", True),
            ("8\n10 9 2 5 3 7 101 18\n", "4\n", True),
        ),
    },
)


def seed() -> None:
    admin_email = os.getenv("ADMIN_EMAIL", "admin@example.com").lower()
    with Session(engine) as db:
        user = db.query(User).filter(User.email == admin_email).first()
        if user is None:
            db.add(
                User(
                    email=admin_email,
                    password_hash=hash_password(os.getenv("ADMIN_PASSWORD", "admin123")),
                    role="admin",
                )
            )
        for problem_data in PROBLEMS:
            title = str(problem_data["title"])
            problem = db.query(Problem).filter(Problem.title == title).first()
            if problem is None:
                problem = Problem(
                    title=title,
                    statement=str(problem_data["statement"]),
                    time_limit_ms=int(problem_data["time_limit_ms"]),
                    memory_limit_mb=int(problem_data["memory_limit_mb"]),
                )
                db.add(problem)
                db.flush()
            tests = problem_data["tests"]
            assert isinstance(tests, tuple)
            for ordinal, (input_text, expected_output, is_hidden) in enumerate(tests, start=1):
                test_case = (
                    db.query(TestCase)
                    .filter(TestCase.problem_id == problem.id, TestCase.ordinal == ordinal)
                    .first()
                )
                if test_case is None:
                    db.add(
                        TestCase(
                            problem_id=problem.id,
                            ordinal=ordinal,
                            input=input_text,
                            expected_output=expected_output,
                            is_hidden=is_hidden,
                        )
                    )
        db.commit()


if __name__ == "__main__":
    seed()
