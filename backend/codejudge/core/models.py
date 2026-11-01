from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base
from .enums import Language, SubmissionStatus, Verdict


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), default="user", nullable=False)
    quota_per_minute: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class Problem(Base):
    __tablename__ = "problems"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    time_limit_ms: Mapped[int] = mapped_column(Integer, default=2000, nullable=False)
    memory_limit_mb: Mapped[int] = mapped_column(Integer, default=256, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    test_cases: Mapped[list["TestCase"]] = relationship(back_populates="problem")


class TestCase(Base):
    __tablename__ = "test_cases"
    __table_args__ = (UniqueConstraint("problem_id", "ordinal", name="uq_problem_testcase_ordinal"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    problem_id: Mapped[int] = mapped_column(ForeignKey("problems.id"), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    input: Mapped[str] = mapped_column(Text, nullable=False)
    expected_output: Mapped[str] = mapped_column(Text, nullable=False)
    is_hidden: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    problem: Mapped[Problem] = relationship(back_populates="test_cases")


class Submission(Base):
    __tablename__ = "submissions"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    problem_id: Mapped[int] = mapped_column(ForeignKey("problems.id"), nullable=False)
    language_id: Mapped[str] = mapped_column(String(16), nullable=False, default=Language.PYTHON3.value)
    source_code: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default=SubmissionStatus.PENDING.value, nullable=False)
    verdict: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    max_time_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    max_memory_kb: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    model_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    sample_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class RunResult(Base):
    __tablename__ = "run_results"
    __table_args__ = (UniqueConstraint("submission_id", "test_case_id", name="uq_submission_test_result"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    submission_id: Mapped[str] = mapped_column(ForeignKey("submissions.id"), nullable=False)
    test_case_id: Mapped[int] = mapped_column(ForeignKey("test_cases.id"), nullable=False)
    verdict: Mapped[str] = mapped_column(String(8), nullable=False)
    wall_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    cpu_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    memory_kb: Mapped[int] = mapped_column(Integer, nullable=False)
    exit_code: Mapped[int] = mapped_column(Integer, nullable=False)
