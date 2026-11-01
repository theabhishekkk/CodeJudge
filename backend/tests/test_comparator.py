from __future__ import annotations

from codejudge.core.comparator import compare_outputs


def test_compare_outputs_whitespace_and_empty() -> None:
    assert compare_outputs(" 1 2 3 \n", "1 2 3") is True
    assert compare_outputs("", "") is True
    assert compare_outputs("1 2", "1 2 3") is False


def test_compare_outputs_unicode_and_count() -> None:
    assert compare_outputs("föß 你好", "föß 你好") is True
    assert compare_outputs("a\n\tb", "a b") is True
    assert compare_outputs("a b", "a c") is False
