"""Short-lived JSON response cache in Redis (fails open)."""
import hashlib
import json
import logging
from typing import Any, Awaitable, Callable

from fastapi import Request
from redis.exceptions import RedisError

from app.services.rankings import CACHE_PREFIX

logger = logging.getLogger(__name__)


def cache_key(namespace: str, params: dict[str, Any]) -> str:
    digest = hashlib.sha256(json.dumps(params, sort_keys=True, default=str).encode()).hexdigest()[:24]
    return f"{CACHE_PREFIX}{namespace}:{digest}"


async def cached(
    request: Request, namespace: str, params: dict[str, Any], ttl: int, build: Callable[[], Awaitable[Any]]
) -> Any:
    """Return the cached JSON for ``params`` or build, store (with a TTL) and return it.

    ``build`` must return JSON-serialisable data (use ``model_dump(mode="json")``).
    """
    redis = getattr(request.app.state, "redis", None)
    key = cache_key(namespace, params)
    if redis is not None:
        try:
            hit = await redis.get(key)
            if hit is not None:
                return json.loads(hit)
        except RedisError:
            logger.warning("Cache read failed")
    value = await build()
    if redis is not None:
        try:
            await redis.set(key, json.dumps(value, default=str), ex=ttl)
        except RedisError:
            logger.warning("Cache write failed")
    return value
