from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from codejudge.core.db import get_db
from codejudge.core.models import Problem, TestCase, User

from ..deps import get_current_admin, get_current_user
from ..schemas import ProblemCreateRequest, ProblemOut

router = APIRouter(prefix="/problems", tags=["problems"])


@router.get("", response_model=list[ProblemOut])
def list_problems(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[Problem]:
    return db.query(Problem).all()


@router.get("/{problem_id}", response_model=ProblemOut)
def get_problem(problem_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> Problem:
    problem = db.query(Problem).filter(Problem.id == problem_id).first()
    if problem is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Problem not found")
    return problem


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
