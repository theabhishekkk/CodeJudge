from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from codejudge.core.db import get_db
from codejudge.core.models import Problem, TestCase, User

from ..deps import get_current_admin, get_current_user
from ..schemas import ProblemCreateRequest, ProblemDetailOut, ProblemOut

router = APIRouter(prefix="/problems", tags=["problems"])


@router.get("", response_model=list[ProblemOut])
def list_problems(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[Problem]:
    return db.query(Problem).all()


@router.get("/{problem_id}", response_model=ProblemDetailOut)
def get_problem(problem_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, object]:
    problem = db.query(Problem).filter(Problem.id == problem_id).first()
    if problem is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Problem not found")
    samples = (
        db.query(TestCase)
        .filter(TestCase.problem_id == problem.id, TestCase.is_hidden.is_(False))
        .order_by(TestCase.ordinal)
        .all()
    )
    return {
        "id": problem.id,
        "title": problem.title,
        "statement": problem.statement,
        "time_limit_ms": problem.time_limit_ms,
        "memory_limit_mb": problem.memory_limit_mb,
        "sample_tests": [
            {
                "ordinal": sample.ordinal,
                "input": sample.input,
                "expected_output": sample.expected_output,
            }
            for sample in samples
        ],
    }


@router.post("", response_model=ProblemOut)
def create_problem(payload: ProblemCreateRequest, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)) -> Problem:
    problem = Problem(title=payload.title, statement=payload.statement, time_limit_ms=payload.time_limit_ms, memory_limit_mb=payload.memory_limit_mb)
    db.add(problem)
    db.flush()
    for tc in payload.tests:
        db.add(TestCase(problem_id=problem.id, ordinal=tc.ordinal, input=tc.input, expected_output=tc.expected_output, is_hidden=tc.is_hidden))
    db.commit()
    db.refresh(problem)
    return problem
