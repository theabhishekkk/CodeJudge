from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Any

from batch_client import ApiClient, batch_chunks, login_from_environment, poll_batches


PYTHON_CORRECT = "print(sum(map(int, input().split())))"
PYTHON_WRONG = "print(0)"
PYTHON_RUNTIME_ERROR = "raise RuntimeError('synthetic load-test error')"
CPP_CORRECT = """#include <iostream>
int main() {
    long long a, b;
    if (std::cin >> a >> b) std::cout << a + b << '\\n';
    return 0;
}"""
CPP_WRONG = "#include <iostream>\nint main() { std::cout << 0 << '\\n'; }"
CPP_RUNTIME_ERROR = """#include <stdexcept>
int main() { throw std::runtime_error("synthetic load-test error"); }"""


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Load-test CodeJudge using a synthetic batch")
    parser.add_argument(
        "--api",
        default=os.environ.get("CODEJUDGE_API_URL", "http://localhost:8000/api"),
    )
    parser.add_argument("--email", default=os.environ.get("CODEJUDGE_EMAIL"))
    parser.add_argument("--password", default=os.environ.get("CODEJUDGE_PASSWORD"))
    parser.add_argument("--count", type=int, default=120)
    parser.add_argument("--problem-id", type=int, default=1)
    parser.add_argument("--language", choices=("python3", "cpp17"), default="python3")
    parser.add_argument("--batch-name", default="Synthetic load test")
    parser.add_argument("--poll-interval", type=float, default=3.0)
    return parser.parse_args()


def _synthetic_items(count: int, problem_id: int, language: str) -> list[dict[str, Any]]:
    items = []
    for index in range(count):
        if index % 10 == 0:
            code = CPP_RUNTIME_ERROR if language == "cpp17" else PYTHON_RUNTIME_ERROR
        elif index % 5 == 0:
            code = CPP_WRONG if language == "cpp17" else PYTHON_WRONG
        else:
            code = CPP_CORRECT if language == "cpp17" else PYTHON_CORRECT
        items.append(
            {
                "problem_id": problem_id,
                "language_id": language,
                "source_code": code,
                "sample_id": f"load-{index + 1:04d}",
            }
        )
    return items


def run() -> int:
    args = _arguments()
    if args.count < 1:
        print("--count must be positive", file=sys.stderr)
        return 2
    try:
        client = ApiClient(args.api)
        login_from_environment(client, args.email, args.password)
        items = _synthetic_items(args.count, args.problem_id, args.language)
        started = time.monotonic()
        batch_ids = []
        payloads = list(
            batch_chunks(
                items,
                repeats=1,
                name=args.batch_name,
                model_name="synthetic-load-test",
            )
        )
        for payload in payloads:
            response = client.request("/batches", payload)
            batch_ids.append(str(response["id"]))
        summaries = poll_batches(client, batch_ids, interval=max(0.5, args.poll_interval))
        elapsed = time.monotonic() - started
        verdicts: dict[str, int] = {}
        for summary in summaries:
            for verdict, count in summary.get("verdicts", {}).items():
                verdicts[verdict] = verdicts.get(verdict, 0) + int(count)
        throughput = args.count / (elapsed / 60) if elapsed else 0.0
        print(f"Completed {args.count} submissions in {elapsed:.2f}s")
        print(f"Throughput: {throughput:.2f} submissions/min")
        print("Verdicts: " + ", ".join(f"{key}={value}" for key, value in sorted(verdicts.items())))
        return 0
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        print(f"Load test failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(run())
