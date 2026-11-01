from __future__ import annotations

import time
from collections import defaultdict
from typing import DefaultDict


class InMemoryRateLimiter:
    def __init__(self, limit_per_minute: int = 60):
        self.limit = limit_per_minute
        self._buckets: DefaultDict[str, list[float]] = defaultdict(list)

    def check(self, key: str) -> tuple[bool, int]:
        now = time.time()
        window = 60
        timestamps = [ts for ts in self._buckets[key] if now - ts < window]
        timestamps.append(now)
        self._buckets[key] = timestamps
        allowed = len(timestamps) <= self.limit
        retry_after = max(0, int(window - (now - timestamps[0]))) if not allowed else 0
        return allowed, retry_after


rate_limiter = InMemoryRateLimiter()


def check_rate_limit(user_key: str, limit_per_minute: int = 60) -> tuple[bool, int]:
    limiter = InMemoryRateLimiter(limit_per_minute)
    return limiter.check(user_key)
