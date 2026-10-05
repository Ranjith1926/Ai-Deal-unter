"""Redis-based job locks so overlapping runs of the same job are skipped, not stacked."""
import uuid
from contextlib import contextmanager
from typing import Iterator

import redis

_RELEASE = """
if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end
"""


@contextmanager
def job_lock(redis_url: str, name: str, ttl_seconds: int) -> Iterator[bool]:
    """Yield True if the lock was acquired. The TTL frees it if a worker dies mid-job."""
    client = redis.Redis.from_url(redis_url)
    key, token = f"dh:lock:{name}", uuid.uuid4().hex
    acquired = bool(client.set(key, token, nx=True, ex=ttl_seconds))
    try:
        yield acquired
    finally:
        if acquired:
            client.eval(_RELEASE, 1, key, token)
        client.close()
