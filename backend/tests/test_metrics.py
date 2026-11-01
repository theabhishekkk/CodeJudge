from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from metrics import calculate_metrics, pass_at_k


def test_pass_at_k_unbiased_probability() -> None:
    assert pass_at_k(10, 1, 1) == pytest.approx(0.1)
    assert pass_at_k(10, 1, 5) == pytest.approx(0.5)
    assert pass_at_k(10, 1, 10) == 1.0
    assert pass_at_k(10, 0, 5) == 0.0
    assert pass_at_k(5, 3, 5) == 1.0


def test_pass_at_k_rejects_invalid_counts() -> None:
    with pytest.raises(ValueError):
        pass_at_k(3, 4, 1)
    with pytest.raises(ValueError):
        pass_at_k(3, 1, 5)


def test_metrics_average_pass_at_k_per_problem(tmp_path: Path) -> None:
    input_path = tmp_path / "results.csv"
    output_path = tmp_path / "metrics.csv"
    rows = [
        "model_name,problem_id,verdict,wall_ms,memory_kb,queued_at,started_at,finished_at",
        "model-a,1,AC,10,20,2026-01-01T00:00:00+00:00,2026-01-01T00:00:01+00:00,2026-01-01T00:00:02+00:00",
        "model-a,1,WA,30,40,2026-01-01T00:00:00+00:00,2026-01-01T00:00:01+00:00,2026-01-01T00:00:03+00:00",
        "model-a,2,AC,50,60,2026-01-01T00:00:00+00:00,2026-01-01T00:00:01+00:00,2026-01-01T00:00:04+00:00",
    ]
    input_path.write_text("\n".join(rows) + "\n", encoding="utf-8")

    metrics = calculate_metrics(input_path, output_path)

    assert metrics[0]["total"] == 3
    assert metrics[0]["pass_rate"] == pytest.approx(2 / 3)
    assert metrics[0]["pass_at_1"] == pytest.approx(0.75)
    assert metrics[0]["pass_at_5"] is None
    assert metrics[0]["median_wall_ms_ac"] == 30
    assert metrics[0]["median_queue_wait_ms"] == 1000
    assert output_path.is_file()
