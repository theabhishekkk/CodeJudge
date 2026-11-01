from __future__ import annotations

from enum import Enum


class Language(str, Enum):
    PYTHON3 = "python3"
    CPP17 = "cpp17"


class SubmissionStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    ERROR = "ERROR"


class Verdict(str, Enum):
    AC = "AC"
    WA = "WA"
    TLE = "TLE"
    MLE = "MLE"
    RE = "RE"
