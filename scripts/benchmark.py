from __future__ import annotations

import argparse
import csv
import io
import os
import sys
from pathlib import Path
from typing import Any

from batch_client import ApiClient, batch_chunks, login_from_environment, poll_batches, read_items


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Submit and collect CodeJudge batch benchmarks")
    parser.add_argument(
        "--api",
        default=os.environ.get("CODEJUDGE_API_URL", "http://localhost:8000/api"),
        help="API base URL (default: CODEJUDGE_API_URL or localhost:8000/api)",
    )
    parser.add_argument("--email", default=os.environ.get("CODEJUDGE_EMAIL"))
    parser.add_argument("--password", default=os.environ.get("CODEJUDGE_PASSWORD"))
    parser.add_argument("--input", type=Path, required=True, help="Input .jsonl, .json, or .csv file")
    parser.add_argument("--batch-name", default="Benchmark")
    parser.add_argument("--model-name")
    parser.add_argument("--repeats", type=int, choices=range(1, 11), default=1)
    parser.add_argument("--out", type=Path, default=Path("results.csv"))
    parser.add_argument("--poll-interval", type=float, default=3.0)
    return parser.parse_args()


def _create_batches(
    client: ApiClient,
    items: list[dict[str, Any]],
    *,
    batch_name: str,
    model_name: str | None,
    repeats: int,
) -> list[str]:
    payloads = list(
        batch_chunks(
            items,
            repeats=repeats,
            name=batch_name,
            model_name=model_name,
        )
    )
    ids: list[str] = []
    for index, payload in enumerate(payloads, start=1):
        response = client.request("/batches", payload)
        batch_id = str(response["id"])
        ids.append(batch_id)
        print(
            f"Submitted batch {index}/{len(payloads)}: {batch_id} "
            f"({response['total']} submissions)",
            flush=True,
        )
    return ids


def _write_exports(client: ApiClient, batch_ids: list[str], output_path: Path) -> int:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    total_rows = 0
    fieldnames: list[str] | None = None
    with output_path.open("w", encoding="utf-8", newline="") as output_file:
        writer: csv.DictWriter[str] | None = None
        for batch_id in batch_ids:
            content = client.download_export(batch_id).decode("utf-8-sig")
            rows = csv.DictReader(io.StringIO(content))
            if fieldnames is None:
                fieldnames = rows.fieldnames
                if fieldnames is None:
                    raise ValueError(f"CSV export for batch {batch_id} has no header")
                writer = csv.DictWriter(output_file, fieldnames=fieldnames)
                writer.writeheader()
            if writer is None:
                raise RuntimeError("Could not initialize the CSV writer")
            for row in rows:
                writer.writerow(row)
                total_rows += 1
    if fieldnames is None:
        raise ValueError("No CSV exports were downloaded")
    return total_rows


def run() -> int:
    args = _arguments()
    try:
        items = read_items(args.input)
        client = ApiClient(args.api)
        login_from_environment(client, args.email, args.password)
        print(f"Loaded {len(items)} input samples")
        batch_ids = _create_batches(
            client,
            items,
            batch_name=args.batch_name,
            model_name=args.model_name,
            repeats=args.repeats,
        )
        summaries = poll_batches(client, batch_ids, interval=max(0.5, args.poll_interval))
        verdict_counts: dict[str, int] = {}
        total = 0
        for summary in summaries:
            total += int(summary.get("total", 0))
            for verdict, count in summary.get("verdicts", {}).items():
                verdict_counts[verdict] = verdict_counts.get(verdict, 0) + int(count)
        rows = _write_exports(client, batch_ids, args.out)
        print(
            "Completed: "
            f"{total} submissions; "
            + ", ".join(f"{verdict}={count}" for verdict, count in sorted(verdict_counts.items()))
        )
        print(f"Downloaded {rows} rows to {args.out}")
        return 0
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        print(f"Benchmark failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(run())
