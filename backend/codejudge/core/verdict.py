from __future__ import annotations

from typing import Any

from .comparator import compare_outputs
from .enums import Verdict


def classify_verdict(
    *,
    oom_killed: bool = False,
    timed_out: bool = False,
    exit_code: int | None = None,
    missing_meta: bool = False,
    killed_by_signal: bool = False,
    actual_output: str | None = None,
    expected_output: str | None = None,
    outer_watchdog: bool = False,
) -> str:
    """Map the runner state to the final verdict in the required precedence order."""
    if oom_killed or (exit_code == 137):
        return Verdict.MLE.value
    if timed_out or outer_watchdog or exit_code == 124:
        return Verdict.TLE.value
    if missing_meta or killed_by_signal:
        return Verdict.RE.value
    if exit_code not in (0, None):
        return Verdict.RE.value
    if actual_output is not None and expected_output is not None:
        if compare_outputs(actual_output, expected_output):
            return Verdict.AC.value
        return Verdict.WA.value
    if exit_code == 0:
        return Verdict.AC.value
    return Verdict.RE.value


def determine_verdict(**kwargs: Any) -> str:
    return classify_verdict(**kwargs)


__all__ = ["classify_verdict", "determine_verdict"]
