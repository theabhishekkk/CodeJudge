from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator
from uuid import uuid4

import redis

from codejudge.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)
LEASE_SECONDS = 120
ACQUIRE_SCRIPT = """
local now = tonumber(ARGV[1])
local token = ARGV[2]
local limit = tonumber(ARGV[3])
local expiry = now + tonumber(ARGV[4])
local expired = redis.call('ZRANGEBYSCORE', KEYS[1], '-inf', now)
for _, old_token in ipairs(expired) do redis.call('HDEL', KEYS[2], old_token) end
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now)
if redis.call('ZSCORE', KEYS[1], token) then
  redis.call('ZADD', KEYS[1], expiry, token)
  return redis.call('ZCARD', KEYS[1])
end
local count = redis.call('ZCARD', KEYS[1])
if count >= limit then return 0 end
redis.call('ZADD', KEYS[1], expiry, token)
return count + 1
"""
MARK_RUNNING_SCRIPT = """
if redis.call('ZSCORE', KEYS[1], ARGV[1]) then
  redis.call('HSET', KEYS[2], ARGV[1], 1)
  return redis.call('HLEN', KEYS[2])
end
return 0
"""
RENEW_SCRIPT = """
if redis.call('ZSCORE', KEYS[1], ARGV[1]) then
  redis.call('ZADD', KEYS[1], ARGV[2], ARGV[1])
  return 1
end
return 0
"""
RELEASE_SCRIPT = """
redis.call('HDEL', KEYS[2], ARGV[1])
return redis.call('ZREM', KEYS[1], ARGV[1])
"""


@dataclass(frozen=True)
class ContainerSlot:
    client: redis.Redis
    key: str
    running_key: str
    token: str

    @property
    def live_count(self) -> int:
        return int(self.client.hlen(self.running_key))

    def mark_running(self) -> int:
        return int(
            self.client.eval(
                MARK_RUNNING_SCRIPT,
                2,
                self.key,
                self.running_key,
                self.token,
            )
        )


class ContainerSemaphore:
    def __init__(self, limit: int, host_id: str) -> None:
        if limit < 1:
            raise ValueError("Container limit must be at least one")
        self.limit = limit
        self.key = f"codejudge:container-slots:{host_id}"
        self.running_key = f"{self.key}:running"
        self._local = threading.BoundedSemaphore(limit)

    @contextmanager
    def acquire(
        self,
        client: redis.Redis,
        lease_seconds: int = LEASE_SECONDS,
    ) -> Iterator[ContainerSlot]:
        self._local.acquire()
        token = str(uuid4())
        expiry_ms = lease_seconds * 1000
        slot = ContainerSlot(client=client, key=self.key, running_key=self.running_key, token=token)
        try:
            while True:
                now_ms = int(time.time() * 1000)
                count = int(
                    client.eval(
                        ACQUIRE_SCRIPT,
                        2,
                        self.key,
                        self.running_key,
                        now_ms,
                        token,
                        self.limit,
                        expiry_ms,
                    )
                )
                if count:
                    break
                time.sleep(0.1)
        except Exception:
            self._local.release()
            raise

        stopped = threading.Event()
        heartbeat_errors: list[Exception] = []

        def renew_lease() -> None:
            while not stopped.wait(lease_seconds / 3):
                try:
                    renewed = client.eval(
                        RENEW_SCRIPT,
                        1,
                        self.key,
                        token,
                        int(time.time() * 1000) + expiry_ms,
                    )
                    if not renewed:
                        heartbeat_errors.append(RuntimeError("Container capacity lease was lost"))
                        return
                except redis.RedisError as exc:
                    heartbeat_errors.append(exc)
                    logger.exception("Could not renew container capacity lease")
                    return

        heartbeat = threading.Thread(target=renew_lease, name="container-capacity-lease", daemon=True)
        heartbeat.start()
        body_error: BaseException | None = None
        try:
            yield slot
        except BaseException as exc:
            body_error = exc
            raise
        finally:
            stopped.set()
            heartbeat.join()
            try:
                client.eval(RELEASE_SCRIPT, 2, self.key, self.running_key, token)
            except redis.RedisError:
                logger.exception("Could not release container capacity lease")
            self._local.release()
            if heartbeat_errors and body_error is None:
                raise RuntimeError("Container capacity lease was lost") from heartbeat_errors[0]


container_semaphore = ContainerSemaphore(
    settings.MAX_PARALLEL_CONTAINERS,
    settings.WORKER_HOST_ID,
)
