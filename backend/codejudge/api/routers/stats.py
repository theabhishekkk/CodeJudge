from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from codejudge.core.db import get_db
from codejudge.core.models import Submission, User

from ..deps import get_current_user

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("/summary")
def summary(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, object]:
    items = db.query(Submission).filter(Submission.user_id == user.id).all()
    return {
        "total": len(items),
        "verdicts": {"AC": sum(1 for item in items if item.verdict == "AC"), "WA": sum(1 for item in items if item.verdict == "WA")},
    }
