from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from codejudge.core.config import get_settings
from codejudge.core.db import get_db
from codejudge.core.models import User

from ..schemas import LoginRequest, RegisterRequest, TokenResponse
from ..security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()


@router.post("/register", response_model=TokenResponse)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> TokenResponse:
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")
    role = "admin" if db.query(User).count() == 0 else "user"
    user = User(email=payload.email.lower(), password_hash=hash_password(payload.password), role=role)
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_access_token(user.id)
    return TokenResponse(access_token=token)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.query(User).filter(User.email == payload.email.lower()).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    token = create_access_token(user.id)
    return TokenResponse(access_token=token)
