from __future__ import annotations

import re
from typing import Iterable

_TOKEN_SPLIT = re.compile(r"\s+")


def _tokenize(value: str | None) -> list[str]:
    if value is None:
        return []
    text = value.decode("utf-8", errors="replace") if isinstance(value, (bytes, bytearray)) else str(value)
    stripped = text.strip()
    if not stripped:
        return []
    return _TOKEN_SPLIT.split(stripped)


def compare_outputs(actual: str | bytes | None, expected: str | bytes | None) -> bool:
    """Return True when token sequences match exactly, ignoring extra whitespace."""
    actual_tokens = _tokenize(actual)
    expected_tokens = _tokenize(expected)
    if len(actual_tokens) != len(expected_tokens):
        return False
    return all(a == b for a, b in zip(actual_tokens, expected_tokens))


def compare_outputs_with_counts(actual: str | bytes | None, expected: str | bytes | None) -> tuple[bool, int, int]:
    actual_tokens = _tokenize(actual)
    expected_tokens = _tokenize(expected)
    mismatches = sum(1 for a, b in zip(actual_tokens, expected_tokens) if a != b)
    return len(actual_tokens) == len(expected_tokens) and mismatches == 0, len(actual_tokens), len(expected_tokens)
