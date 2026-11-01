from __future__ import annotations

import csv
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Iterator


DEFAULT_MAX_ITEMS = 500
DEFAULT_MAX_REQUEST_BYTES = 20 * 1024 * 1024


class ApiClient:
    def __init__(self, api_url: str, *, timeout: float = 30) -> None:
        normalized = api_url.rstrip("/")
        self.api_url = normalized if normalized.endswith("/api") else f"{normalized}/api"
        self.timeout = timeout
        self.token: str | None = None

    def login(self, email: str, password: str) -> None:
        response = self.request(
            "/auth/login",
            {"email": email, "password": password},
            authenticated=False,
        )
        self.token = str(response["access_token"])

    def request(
        self,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        authenticated: bool = True,
    ) -> dict[str, Any]:
        headers = {"Accept": "application/json"}
        body = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if authenticated and self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(
            f"{self.api_url}{path}",
            data=body,
            headers=headers,
            method="POST" if body is not None else "GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"API request failed ({exc.code}): {error_body}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Cannot connect to CodeJudge API: {exc.reason}") from exc

    def download_export(self, batch_id: str) -> bytes:
        headers = {"Accept": "text/csv"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(
            f"{self.api_url}/batches/{batch_id}/export.csv",
            headers=headers,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"CSV export failed ({exc.code}): {error_body}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Cannot connect to CodeJudge API: {exc.reason}") from exc


def read_items(path: Path) -> list[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            raw_items: list[dict[str, Any]] = list(csv.DictReader(handle))
    elif suffix == ".jsonl":
        raw_items = []
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{path}:{line_number}: invalid JSON: {exc.msg}") from exc
                if not isinstance(value, dict):
                    raise ValueError(f"{path}:{line_number}: each JSONL row must be an object")
                raw_items.append(value)
    elif suffix == ".json":
        value = json.loads(path.read_text(encoding="utf-8"))
        raw_items = value.get("items") if isinstance(value, dict) else value
        if not isinstance(raw_items, list):
            raise ValueError("JSON input must be an array or an object containing an items array")
    else:
        raise ValueError("Input file must have a .jsonl, .json, or .csv extension")

    items: list[dict[str, Any]] = []
    required = ("problem_id", "language_id", "source_code")
    for index, raw_item in enumerate(raw_items):
        if not isinstance(raw_item, dict):
            raise ValueError(f"Input row {index + 1} must be an object")
        missing = [field for field in required if field not in raw_item]
        if missing:
            raise ValueError(f"Input row {index + 1} is missing: {', '.join(missing)}")
        item = {field: raw_item[field] for field in required}
        if isinstance(item["problem_id"], str):
            try:
                item["problem_id"] = int(item["problem_id"])
            except ValueError as exc:
                raise ValueError(f"Input row {index + 1} has an invalid problem_id") from exc
        if "sample_id" in raw_item and raw_item["sample_id"] is not None:
            item["sample_id"] = raw_item["sample_id"]
        items.append(item)
    if not items:
        raise ValueError("Input file contains no submissions")
    return items


def batch_chunks(
    items: list[dict[str, Any]],
    *,
    repeats: int,
    name: str | None,
    model_name: str | None,
) -> Iterator[dict[str, Any]]:
    if not 1 <= repeats <= 10:
        raise ValueError("repeats must be between 1 and 10")
    max_items = int(os.environ.get("BATCH_MAX_ITEMS", DEFAULT_MAX_ITEMS))
    max_request_bytes = int(
        os.environ.get("BATCH_REQUEST_MAX_BYTES", DEFAULT_MAX_REQUEST_BYTES)
    )
    max_rows = max_items // repeats
    if max_rows < 1:
        raise ValueError("BATCH_MAX_ITEMS is smaller than the requested repeats count")

    current: list[dict[str, Any]] = []
    for item in items:
        candidate = [*current, item]
        payload: dict[str, Any] = {"repeats": repeats, "items": candidate}
        if name:
            payload["name"] = name
        if model_name:
            payload["model_name"] = model_name
        encoded_size = len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        if current and (len(candidate) > max_rows or encoded_size > max_request_bytes):
            yield _batch_payload(current, repeats, name, model_name)
            current = []
            candidate = [item]
            payload = _batch_payload(candidate, repeats, name, model_name)
            encoded_size = len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        if encoded_size > max_request_bytes:
            raise ValueError("A single input row exceeds BATCH_REQUEST_MAX_BYTES")
        current.append(item)
        if len(current) == max_rows:
            yield _batch_payload(current, repeats, name, model_name)
            current = []
    if current:
        yield _batch_payload(current, repeats, name, model_name)


def _batch_payload(
    items: list[dict[str, Any]],
    repeats: int,
    name: str | None,
    model_name: str | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"repeats": repeats, "items": items}
    if name:
        payload["name"] = name
    if model_name:
        payload["model_name"] = model_name
    return payload


def login_from_environment(client: ApiClient, email: str | None, password: str | None) -> None:
    selected_email = email or os.environ.get("CODEJUDGE_EMAIL")
    selected_password = password or os.environ.get("CODEJUDGE_PASSWORD")
    if not selected_email or not selected_password:
        raise ValueError("Provide --email/--password or CODEJUDGE_EMAIL/CODEJUDGE_PASSWORD")
    client.login(selected_email, selected_password)


def poll_batches(client: ApiClient, batch_ids: list[str], *, interval: float = 3.0) -> list[dict[str, Any]]:
    completed: dict[str, dict[str, Any]] = {}
    latest: dict[str, dict[str, Any]] = {}
    next_report = 0.0
    while len(completed) < len(batch_ids):
        summaries: dict[str, dict[str, Any]] = {}
        for batch_id in batch_ids:
            if batch_id in completed:
                continue
            summary = client.request(f"/batches/{batch_id}")
            summaries[batch_id] = summary
            latest[batch_id] = summary
            counts = summary.get("counts", {})
            if not counts.get("PENDING", 0) and not counts.get("RUNNING", 0):
                completed[batch_id] = summary
        now = time.monotonic()
        if now >= next_report:
            total = sum(summary.get("total", 0) for summary in latest.values())
            finished = sum(
                sum(count for key, count in summary.get("counts", {}).items() if key not in {"PENDING", "RUNNING"})
                for summary in latest.values()
            )
            print(f"Progress: {finished}/{total} submissions terminal across {len(batch_ids)} batch(es)", flush=True)
            next_report = now + interval
        if len(completed) < len(batch_ids):
            time.sleep(interval)
    return [completed[batch_id] for batch_id in batch_ids]
