from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from docker import DockerClient
from docker.errors import DockerException

from codejudge.core.config import get_settings

settings = get_settings()


class SandboxExecutionError(RuntimeError):
    pass


def run_sandbox_command(language: str, code_path: str, input_text: str, timeout_s: int, memory_limit_mb: int, workdir: str) -> dict[str, Any]:
    client = __import__("docker").from_env()
    if not client.ping():
        raise SandboxExecutionError("Docker unavailable")
    work = Path(workdir)
    in_dir = work / "tests" / "input"
    out_dir = work / "tests" / "out"
    in_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    (in_dir / "input.txt").write_text(input_text, encoding="utf-8")
    container_name = f"codejudge-{int(time.time() * 1000)}"
    image = "codejudge-py:1" if language == "python3" else "codejudge-cpp:1"
    container = client.containers.run(
        image=image,
        name=container_name,
        detach=True,
        network_disabled=True,
        mem_limit=f"{memory_limit_mb}m",
        memswap_limit=f"{memory_limit_mb}m",
        nano_cpus=500_000_000,
        pids_limit=64,
        read_only=True,
        volumes={
            str(code_path): {"bind": "/code", "mode": "ro"},
            str(in_dir): {"bind": "/data", "mode": "ro"},
            str(work / "runner"): {"bind": "/runner", "mode": "ro"},
            str(out_dir): {"bind": "/out", "mode": "rw"},
        },
        user="65534:65534",
        cap_drop=["ALL"],
        security_opt=["no-new-privileges"],
        environment={"PYTHONDONTWRITEBYTECODE": "1"},
        working_dir="/",
        remove=False,
        auto_remove=False,
    )
    try:
        result = container.wait(timeout=timeout_s + 3)
        logs = container.logs(stdout=True, stderr=True)
        return {"status": result, "logs": logs.decode("utf-8", errors="replace")}
    finally:
        try:
            container.remove(force=True)
        except Exception:
            pass
