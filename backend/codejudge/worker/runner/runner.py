from __future__ import annotations

import json
import math
import os
import resource
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

OUTPUT_LIMIT_BYTES = 10 * 1024 * 1024
STDERR_LIMIT_BYTES = 4096


def _write_meta(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _limit_child_resources() -> None:
    resource.setrlimit(resource.RLIMIT_FSIZE, (OUTPUT_LIMIT_BYTES, OUTPUT_LIMIT_BYTES))
    cpu_seconds = max(1, math.ceil(int(os.environ["TIME_LIMIT_MS"]) / 1000) + 1)
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))


def _compile_cpp(output_dir: Path, meta_path: Path) -> Path | None:
    executable = output_dir / "program"
    try:
        result = subprocess.run(
            ["g++", "-std=c++17", "-O2", "-pipe", "/code/main.cpp", "-o", str(executable)],
            capture_output=True,
            timeout=10,
            check=False,
        )
    except subprocess.TimeoutExpired:
        _write_meta(
            meta_path,
            {"exit_code": 1, "compile_error": True, "stderr": "compile timed out"},
        )
        return None
    if result.returncode != 0:
        _write_meta(
            meta_path,
            {
                "exit_code": 1,
                "compile_error": True,
                "stderr": result.stderr[:STDERR_LIMIT_BYTES].decode("utf-8", errors="replace"),
            },
        )
        return None
    return executable


def main() -> int:
    output_dir = Path("/out")
    input_path = Path("/data/input.txt")
    meta_path = output_dir / "meta.json"
    output_path = output_dir / "output.txt"
    stderr_path = output_dir / "stderr.txt"
    language = os.environ.get("CODE_LANGUAGE", "python3")
    time_limit_ms = int(os.environ.get("TIME_LIMIT_MS", "2000"))
    command = [sys.executable, "-B", "/code/main.py"]
    if language == "cpp17":
        executable = _compile_cpp(output_dir, meta_path)
        if executable is None:
            return 1
        command = [str(executable)]

    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    start = time.perf_counter()
    timed_out = False
    try:
        with input_path.open("rb") as stdin, output_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            process = subprocess.Popen(
                command,
                stdin=stdin,
                stdout=stdout,
                stderr=stderr,
                start_new_session=True,
                preexec_fn=_limit_child_resources,
            )
            try:
                exit_code = process.wait(timeout=max(0.001, time_limit_ms / 1000))
            except subprocess.TimeoutExpired:
                timed_out = True
                os.killpg(process.pid, signal.SIGKILL)
                exit_code = process.wait()
    except Exception as exc:
        stderr_path.write_text(str(exc)[:STDERR_LIMIT_BYTES], encoding="utf-8")
        exit_code = 1

    elapsed_ms = int((time.perf_counter() - start) * 1000)
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    cpu_ms = max(0, int((after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime) * 1000))
    memory_kb = max(0, int(after.ru_maxrss))
    try:
        with stderr_path.open("rb") as stderr_file:
            stderr = stderr_file.read(STDERR_LIMIT_BYTES).decode("utf-8", errors="replace")
    except FileNotFoundError:
        stderr = ""
    _write_meta(
        meta_path,
        {
            "exit_code": exit_code,
            "timed_out": timed_out,
            "wall_ms": elapsed_ms,
            "cpu_ms": cpu_ms,
            "memory_kb": memory_kb,
            "stderr": stderr,
        },
    )
    return 124 if timed_out else exit_code


if __name__ == "__main__":
    raise SystemExit(main())
