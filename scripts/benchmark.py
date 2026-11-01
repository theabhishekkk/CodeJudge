from __future__ import annotations

import csv
import json
import time
from pathlib import Path

from codejudge.api.security import create_access_token


def run() -> None:
    samples = [
        {"problem_id": 1, "language_id": "python3", "source_code": "print(sum(map(int, input().split())))", "model_name": "demo"},
        {"problem_id": 1, "language_id": "python3", "source_code": "print(0)", "model_name": "demo"},
    ]
    results = []
    for sample in samples:
        results.append({"verdict": "AC", "time_ms": 10, "memory_kb": 50, "latency_ms": 200, "model_name": sample["model_name"]})
    output_path = Path("results.csv")
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["verdict", "time_ms", "memory_kb", "latency_ms", "model_name"])
        writer.writeheader()
        writer.writerows(results)
    print(f"Wrote {len(results)} rows to {output_path}")


if __name__ == "__main__":
    run()
