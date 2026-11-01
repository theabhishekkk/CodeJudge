from __future__ import annotations

import os
import shutil
from pathlib import Path


def create_submission_workdir(root: str, submission_id: str) -> Path:
    base_dir = Path(root) / submission_id
    code_dir = base_dir / "code"
    tests_dir = base_dir / "tests"
    code_dir.mkdir(parents=True, exist_ok=True)
    tests_dir.mkdir(parents=True, exist_ok=True)
    return base_dir


def cleanup_workdir(path: Path | str) -> None:
    target = Path(path)
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
