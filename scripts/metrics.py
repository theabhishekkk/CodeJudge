from __future__ import annotations

import argparse
import csv
import math
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


VERDICTS = ("AC", "WA", "RE", "TLE", "MLE", "ERROR", "CANCELLED")
PASS_K_VALUES = (1, 5, 10)


def pass_at_k(sample_count: int, correct_count: int, k: int) -> float:
    if sample_count < 0 or correct_count < 0 or correct_count > sample_count:
        raise ValueError("Counts must satisfy 0 <= correct_count <= sample_count")
    if k < 1:
        raise ValueError("k must be positive")
    if sample_count < k:
        raise ValueError("sample_count must be at least k")
    if sample_count - correct_count < k:
        return 1.0
    return 1.0 - math.comb(sample_count - correct_count, k) / math.comb(sample_count, k)


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def _number(row: dict[str, str], key: str) -> float | None:
    value = row.get(key)
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def _model_metrics(model_name: str, rows: list[dict[str, str]]) -> dict[str, Any]:
    verdicts = Counter((row.get("verdict") or row.get("status") or "UNKNOWN").upper() for row in rows)
    accepted = [row for row in rows if (row.get("verdict") or "").upper() == "AC"]
    wall_all = [value for row in rows if (value := _number(row, "wall_ms")) is not None]
    wall_accepted = [value for row in accepted if (value := _number(row, "wall_ms")) is not None]
    memory_all = [value for row in rows if (value := _number(row, "memory_kb")) is not None]
    memory_accepted = [value for row in accepted if (value := _number(row, "memory_kb")) is not None]
    queue_wait = []
    start_times = []
    finish_times = []
    for row in rows:
        queued_at = _timestamp(row.get("queued_at"))
        started_at = _timestamp(row.get("started_at"))
        finished_at = _timestamp(row.get("finished_at"))
        if queued_at and started_at:
            queue_wait.append(max(0.0, (started_at - queued_at).total_seconds() * 1000))
        if started_at:
            start_times.append(started_at)
        if finished_at:
            finish_times.append(finished_at)

    problem_samples: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        problem_samples[row.get("problem_id") or "unknown"].append(row)
    pass_metrics: dict[str, float | None] = {}
    for k in PASS_K_VALUES:
        values = []
        for problem_rows in problem_samples.values():
            if len(problem_rows) >= k:
                correct = sum((row.get("verdict") or "").upper() == "AC" for row in problem_rows)
                values.append(pass_at_k(len(problem_rows), correct, k))
        pass_metrics[f"pass_at_{k}"] = statistics.mean(values) if values else None

    duration_minutes = None
    if start_times and finish_times:
        duration_seconds = (max(finish_times) - min(start_times)).total_seconds()
        if duration_seconds > 0:
            duration_minutes = duration_seconds / 60
    throughput = len(rows) / duration_minutes if duration_minutes else None
    total = len(rows)
    metrics: dict[str, Any] = {
        "model_name": model_name,
        "total": total,
        "pass_rate": len(accepted) / total if total else 0.0,
        **{f"{verdict.lower()}_count": verdicts.get(verdict, 0) for verdict in VERDICTS},
        **pass_metrics,
        "median_wall_ms_all": statistics.median(wall_all) if wall_all else None,
        "p95_wall_ms_all": _percentile(wall_all, 0.95),
        "median_memory_kb_all": statistics.median(memory_all) if memory_all else None,
        "p95_memory_kb_all": _percentile(memory_all, 0.95),
        "median_wall_ms_ac": statistics.median(wall_accepted) if wall_accepted else None,
        "p95_wall_ms_ac": _percentile(wall_accepted, 0.95),
        "median_memory_kb_ac": statistics.median(memory_accepted) if memory_accepted else None,
        "p95_memory_kb_ac": _percentile(memory_accepted, 0.95),
        "throughput_subs_per_min": throughput,
        "median_queue_wait_ms": statistics.median(queue_wait) if queue_wait else None,
    }
    return metrics


def calculate_metrics(input_path: Path, output_path: Path) -> list[dict[str, Any]]:
    with input_path.open("r", encoding="utf-8-sig", newline="") as handle:
        grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in csv.DictReader(handle):
            grouped[row.get("model_name") or "unknown"].append(row)
    if not grouped:
        raise ValueError(f"{input_path} contains no result rows")
    results = [_model_metrics(model, rows) for model, rows in sorted(grouped.items())]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    columns = list(results[0])
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(results)
    return results


def run() -> int:
    parser = argparse.ArgumentParser(description="Summarize CodeJudge benchmark exports")
    parser.add_argument("--input", type=Path, default=Path("results.csv"))
    parser.add_argument("--out", type=Path, default=Path("metrics.csv"))
    args = parser.parse_args()
    try:
        rows = calculate_metrics(args.input, args.out)
    except (OSError, ValueError) as exc:
        print(f"Metrics failed: {exc}", file=sys.stderr)
        return 1
    columns = (
        "model_name",
        "total",
        "pass_rate",
        "pass_at_1",
        "pass_at_5",
        "pass_at_10",
        "median_wall_ms_ac",
        "p95_wall_ms_ac",
        "median_memory_kb_ac",
        "p95_memory_kb_ac",
        "throughput_subs_per_min",
        "median_queue_wait_ms",
    )
    print(" | ".join(columns))
    for row in rows:
        print(" | ".join("" if row[column] is None else str(row[column]) for column in columns))
    print(f"Wrote {len(rows)} model summaries to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
