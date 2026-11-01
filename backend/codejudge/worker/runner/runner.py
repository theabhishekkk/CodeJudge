from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


def write_meta(path: Path, **payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def main() -> int:
    code_path = Path("/code")
    data_dir = Path("/data")
    out_dir = Path("/out")
    out_dir.mkdir(parents=True, exist_ok=True)
    input_path = data_dir / "input.txt"
    stderr_path = out_dir / "stderr.txt"
    meta_path = out_dir / "meta.json"

    start = time.perf_counter()
    try:
        if (code_path / "main.py").exists():
            proc = subprocess.run(
                [sys.executable, "/code/main.py"],
                stdin=input_path.open("rb"),
                stdout=(out_dir / "output.txt").open("wb"),
                stderr=stderr_path.open("wb"),
                timeout=30,
                start_new_session=True,
                check=False,
            )
        else:
            proc = subprocess.run(
                ["/code/main"],
                stdin=input_path.open("rb"),
                stdout=(out_dir / "output.txt").open("wb"),
                stderr=stderr_path.open("wb"),
                timeout=30,
                start_new_session=True,
                check=False,
            )
        elapsed = time.perf_counter() - start
        write_meta(
            meta_path,
            exit_code=proc.returncode,
            elapsed_ms=int(elapsed * 1000),
            timed_out=False,
            stderr_truncated=str(stderr_path.read_text(errors="replace")[:4096]),
            stdout_path=str(out_dir / "output.txt"),
        )
        return proc.returncode
    except subprocess.TimeoutExpired:
        write_meta(meta_path, exit_code=124, elapsed_ms=30000, timed_out=True)
        return 124
    except Exception as exc:  # pragma: no cover - sandbox safety
        write_meta(meta_path, exit_code=1, elapsed_ms=0, timed_out=False, error=str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
