from __future__ import annotations

import json
import sys
from pathlib import Path

from pytest import MonkeyPatch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from batch_client import batch_chunks, read_items


def test_read_jsonl_and_csv_inputs(tmp_path: Path) -> None:
    jsonl_path = tmp_path / "items.jsonl"
    jsonl_path.write_text(
        json.dumps({"problem_id": 1, "language_id": "python3", "source_code": "print(1)"}) + "\n",
        encoding="utf-8",
    )
    csv_path = tmp_path / "items.csv"
    csv_path.write_text(
        "problem_id,language_id,source_code,sample_id\n1,python3,print(1),one\n",
        encoding="utf-8",
    )

    assert read_items(jsonl_path)[0]["problem_id"] == 1
    assert read_items(csv_path)[0]["sample_id"] == "one"
    assert read_items(csv_path)[0]["problem_id"] == 1


def test_batch_chunks_respect_expanded_limit_and_request_bytes(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("BATCH_MAX_ITEMS", "4")
    monkeypatch.setenv("BATCH_REQUEST_MAX_BYTES", "1000")
    items = [
        {"problem_id": 1, "language_id": "python3", "source_code": f"print({index})"}
        for index in range(5)
    ]

    chunks = list(batch_chunks(items, repeats=2, name="run", model_name=None))

    assert [len(chunk["items"]) for chunk in chunks] == [2, 2, 1]
    assert sum(len(chunk["items"]) * chunk["repeats"] for chunk in chunks) == 10
