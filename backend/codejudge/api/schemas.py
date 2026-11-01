from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from codejudge.core.enums import Language


class RegisterRequest(BaseModel):
    email: str = Field(..., min_length=3)
    password: str = Field(..., min_length=6)


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=3)
    password: str = Field(..., min_length=6)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ProblemCreateRequest(BaseModel):
    title: str
    statement: str
    time_limit_ms: int = 2000
    memory_limit_mb: int = 256
    tests: list["TestCaseCreateRequest"] = []


class TestCaseCreateRequest(BaseModel):
    ordinal: int
    input: str
    expected_output: str
    is_hidden: bool = False


class SubmissionCreateRequest(BaseModel):
    problem_id: int
    language_id: str = Language.PYTHON3.value
    source_code: str = Field(..., min_length=1, max_length=65536)
    model_name: Optional[str] = None
    sample_id: Optional[str] = None

    @field_validator("language_id")
    @classmethod
    def validate_language(cls, value: str) -> str:
        if value not in {item.value for item in Language}:
            raise ValueError("Unsupported language")
        return value


class SubmissionResponse(BaseModel):
    id: str
    status: str


class UserOut(BaseModel):
    id: int
    email: str
    role: str
    model_config = ConfigDict(from_attributes=True)


class ProblemOut(BaseModel):
    id: int
    title: str
    statement: str
    time_limit_ms: int
    memory_limit_mb: int
    model_config = ConfigDict(from_attributes=True)


class ProblemSampleOut(BaseModel):
    ordinal: int
    input: str
    expected_output: str


class ProblemDetailOut(ProblemOut):
    sample_tests: list[ProblemSampleOut]


class SubmissionOut(BaseModel):
    id: str
    user_id: int
    problem_id: int
    language_id: str
    source_code: str
    status: str
    verdict: Optional[str] = None
    detail: Optional[str] = None
    max_time_ms: Optional[int] = None
    max_memory_kb: Optional[int] = None
    model_name: Optional[str] = None
    sample_id: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)
