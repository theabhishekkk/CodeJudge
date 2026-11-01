from __future__ import annotations

from codejudge.api.security import create_access_token, hash_password, verify_password


def test_password_hashing_and_token() -> None:
    hashed = hash_password("secret")
    assert verify_password("secret", hashed) is True
    token = create_access_token("42")
    assert isinstance(token, str)
    assert token.startswith("ey")
