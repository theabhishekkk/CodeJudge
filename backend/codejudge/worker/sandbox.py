from __future__ import annotations

import json
import logging
import math
import os
import time
from pathlib import Path
from typing import Any

import docker
from docker.errors import DockerException, ImageNotFound
from docker.types import Ulimit
import redis

from codejudge.core.config import get_settings
from .capacity import container_semaphore

settings = get_settings()
logger = logging.getLogger(__name__)


class SandboxExecutionError(RuntimeError):
    pass


def _read_text(path: Path, *, limit: int | None = None) -> str:
    if not path.is_file():
        return ""
    with path.open("rb") as file:
        content = file.read() if limit is None else file.read(limit)
    return content.decode("utf-8", errors="replace")


def run_sandbox_command(
    language: str,
    code_path: str,
    input_text: str,
    time_limit_ms: int,
    memory_limit_mb: int,
    workdir: str,
    test_case_id: int,
    submission_id: str,
    docker_client: docker.DockerClient | None = None,
    redis_client: redis.Redis | None = None,
) -> dict[str, Any]:
    owns_docker_client = docker_client is None
    owns_redis_client = redis_client is None
    client = docker_client or docker.from_env()
    redis_connection = redis_client or redis.Redis.from_url(settings.REDIS_URL)
    container = None
    try:
        try:
            client.ping()
        except DockerException as exc:
            raise SandboxExecutionError("Docker daemon is unavailable") from exc

        image = {"python3": "codejudge-py:1", "cpp17": "codejudge-cpp:1"}.get(language)
        if image is None:
            raise SandboxExecutionError(f"Unsupported language: {language}")
        try:
            client.images.get(image)
        except ImageNotFound as exc:
            raise SandboxExecutionError(f"Sandbox image is not built: {image}") from exc

        test_dir = Path(workdir) / "tests" / str(test_case_id)
        input_dir = test_dir / "input"
        output_dir = test_dir / "output"
        input_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)
        (input_dir / "input.txt").write_text(input_text, encoding="utf-8")
        for path in (Path(code_path), input_dir):
            os.chmod(path, 0o755)
        os.chmod(input_dir / "input.txt", 0o644)
        os.chmod(output_dir, 0o777)

        timeout_s = max(0.1, time_limit_ms / 1000)
        watchdog_s = timeout_s + (10 if language == "cpp17" else 0) + 3
        capacity_lease_seconds = max(120, math.ceil(time_limit_ms / 1000) + 20)
        runtime = settings.SANDBOX_RUNTIME or None
        watchdog_fired = False
        try:
            with container_semaphore.acquire(
                redis_connection,
                lease_seconds=capacity_lease_seconds,
            ) as slot:
                container = client.containers.run(
                    image=image,
                    command=["python3", "/runner/runner.py"],
                    detach=True,
                    network_disabled=True,
                    mem_limit=f"{max(1, memory_limit_mb)}m",
                    memswap_limit=f"{max(1, memory_limit_mb)}m",
                    nano_cpus=500_000_000,
                    pids_limit=64,
                    read_only=True,
                    tmpfs={"/tmp": "rw,noexec,nosuid,size=16m"},
                    user="65534:65534",
                    cap_drop=["ALL"],
                    security_opt=["no-new-privileges"],
                    ulimits=[Ulimit(name="nofile", soft=64, hard=64)],
                    environment={
                        "PYTHONDONTWRITEBYTECODE": "1",
                        "CODE_LANGUAGE": language,
                        "TIME_LIMIT_MS": str(time_limit_ms),
                    },
                    volumes={
                        str(Path(code_path).resolve()): {"bind": "/code", "mode": "ro"},
                        str(input_dir.resolve()): {"bind": "/data", "mode": "ro"},
                        str(output_dir.resolve()): {"bind": "/out", "mode": "rw"},
                    },
                    labels={
                        "codejudge.sandbox": "true",
                        "codejudge.submission": submission_id,
                        "codejudge.test_case": str(test_case_id),
                    },
                    runtime=runtime,
                    auto_remove=False,
                )
                concurrent_containers = slot.mark_running()
                deadline = time.monotonic() + watchdog_s
                while True:
                    container.reload()
                    state = container.attrs.get("State", {})
                    if not state.get("Running", False):
                        break
                    if time.monotonic() >= deadline:
                        watchdog_fired = True
                        container.kill()
                        container.reload()
                        state = container.attrs.get("State", {})
                        break
                    time.sleep(0.1)
                meta_path = output_dir / "meta.json"
                try:
                    metadata = json.loads(_read_text(meta_path, limit=16_384)) if meta_path.is_file() else {}
                except json.JSONDecodeError:
                    metadata = {}

                return {
                    "exit_code": metadata.get("exit_code", state.get("ExitCode")),
                    "oom_killed": bool(state.get("OOMKilled", False)),
                    "outer_watchdog": watchdog_fired,
                    "timed_out": bool(metadata.get("timed_out", False)),
                    "missing_meta": not bool(metadata),
                    "compile_error": bool(metadata.get("compile_error", False)),
                    "actual_output": _read_text(output_dir / "output.txt", limit=10_485_760),
                    "stderr": _read_text(output_dir / "stderr.txt", limit=4096),
                    "wall_ms": int(metadata.get("wall_ms", 0)),
                    "cpu_ms": int(metadata.get("cpu_ms", 0)),
                    "memory_kb": int(metadata.get("memory_kb", 0)),
                    "concurrent_containers": concurrent_containers,
                }
        except DockerException as exc:
            raise SandboxExecutionError("Sandbox container execution failed") from exc
    finally:
        if container is not None:
            try:
                container.remove(force=True)
            except DockerException:
                logger.exception("Could not remove sandbox container for %s", submission_id)
        if owns_docker_client:
            client.close()
        if owns_redis_client:
            redis_connection.close()
