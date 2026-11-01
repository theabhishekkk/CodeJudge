from __future__ import annotations

import csv
from pathlib import Path


def run() -> None:
    results_path = Path("results.csv")
    if not results_path.exists():
        raise FileNotFoundError("results.csv not found. Run benchmark.py first.")
    rows = list(csv.DictReader(results_path.open("r", encoding="utf-8", newline="")))
    print(f"rows={len(rows)}")
    for row in rows:
        print(row)


if __name__ == "__main__":
    run()
