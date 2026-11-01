from __future__ import annotations

from codejudge.core.verdict import classify_verdict


def test_verdict_precedence() -> None:
    assert classify_verdict(oom_killed=True) == "MLE"
    assert classify_verdict(oom_killed=True, timed_out=True) == "MLE"
    assert classify_verdict(timed_out=True) == "TLE"
    assert classify_verdict(exit_code=137) == "MLE"
    assert classify_verdict(exit_code=124) == "TLE"
    assert classify_verdict(exit_code=0, actual_output="1 2", expected_output="1 2") == "AC"
    assert classify_verdict(exit_code=0, actual_output="1 2", expected_output="1 3") == "WA"
    assert classify_verdict(exit_code=1) == "RE"
