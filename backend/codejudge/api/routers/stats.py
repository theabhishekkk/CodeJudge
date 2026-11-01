from __future__ import annotations

import math
from statistics import median
from typing import Sequence

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from codejudge.core.db import get_db
from codejudge.core.models import RunResult, Submission, User

from ..deps import get_current_user

router = APIRouter(prefix="/stats", tags=["stats"])


def _percentile(values: Sequence[int], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return float(ordered[index])


@router.get("/summary")
def summary(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, object]:
    items = db.query(Submission).filter(Submission.user_id == user.id).all()
    verdicts = {verdict: 0 for verdict in ("AC", "WA", "TLE", "MLE", "RE", "PENDING", "RUNNING", "ERROR")}
    for item in items:
        verdict = item.verdict if item.status == "COMPLETED" and item.verdict else item.status
        verdicts[verdict] = verdicts.get(verdict, 0) + 1

    completed_ids = [item.id for item in items if item.status == "COMPLETED"]
    results = (
        db.query(RunResult)
        .filter(RunResult.submission_id.in_(completed_ids))
        .all()
        if completed_ids
        else []
    )
    wall_times = [result.wall_ms for result in results]
    cpu_times = [result.cpu_ms for result in results]
    memory_values = [result.memory_kb for result in results]
    passed = verdicts["AC"]
    completed_count = len(completed_ids)
    return {
        "total": len(items),
        "completed": completed_count,
        "pass_rate": (passed / completed_count * 100) if completed_count else 0.0,
        "verdicts": verdicts,
        "median_time_ms": float(median(wall_times)) if wall_times else None,
        "p95_time_ms": _percentile(wall_times, 0.95),
        "median_cpu_ms": float(median(cpu_times)) if cpu_times else None,
        "p95_cpu_ms": _percentile(cpu_times, 0.95),
        "median_memory_kb": float(median(memory_values)) if memory_values else None,
        "p95_memory_kb": _percentile(memory_values, 0.95),
    }
