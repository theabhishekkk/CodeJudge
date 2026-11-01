from __future__ import annotations

import threading
import time
from typing import Any

from codejudge.worker.capacity import (
    ACQUIRE_SCRIPT,
    MARK_RUNNING_SCRIPT,
    RELEASE_SCRIPT,
    RENEW_SCRIPT,
    ContainerSemaphore,
)


class FakeRedis:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._members: dict[str, dict[str, int]] = {}
        self._running: dict[str, dict[str, int]] = {}

    def eval(self, script: str, *_args: Any) -> int:
        num_keys, key, *values = _args
        with self._lock:
            members = self._members.setdefault(key, {})
            running_key = values.pop(0) if num_keys == 2 else None
            if script == ACQUIRE_SCRIPT:
                now, token, limit, lease = values
                running = self._running.setdefault(running_key, {})
                expired = [member for member, expiry in members.items() if expiry <= now]
                for member in expired:
                    members.pop(member)
                    running.pop(member, None)
                members.update({member: expiry for member, expiry in members.items() if expiry > now})
                if token in members:
                    members[token] = now + lease
                    return len(members)
                if len(members) >= limit:
                    return 0
                members[token] = now + lease
                return len(members)
            if script == MARK_RUNNING_SCRIPT:
                token = values[0]
                if token in members:
                    running = self._running.setdefault(running_key, {})
                    running[token] = 1
                    return len(running)
                return 0
            if script == RENEW_SCRIPT:
                token, expiry = values
                if token in members:
                    members[token] = expiry
                    return 1
                return 0
            if script == RELEASE_SCRIPT:
                token = values[0]
                self._running.setdefault(running_key, {}).pop(token, None)
                return int(members.pop(token, None) is not None)
            raise AssertionError("Unexpected Redis script")

    def zcard(self, key: str) -> int:
        with self._lock:
            return len(self._members.get(key, {}))

    def hlen(self, key: str) -> int:
        with self._lock:
            return len(self._running.get(key, {}))


def test_container_semaphore_bounds_concurrent_threads() -> None:
    semaphore = ContainerSemaphore(limit=3, host_id="test-host")
    redis_client = FakeRedis()
    state_lock = threading.Lock()
    active = 0
    peak = 0

    def run_container() -> None:
        nonlocal active, peak
        with semaphore.acquire(redis_client) as slot:
            live_count = slot.mark_running()
            with state_lock:
                active += 1
                peak = max(peak, active)
                assert live_count <= 3
                assert slot.live_count <= 3
            time.sleep(0.02)
            with state_lock:
                active -= 1

    threads = [threading.Thread(target=run_container) for _ in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert peak == 3
    assert redis_client.zcard(semaphore.key) == 0
