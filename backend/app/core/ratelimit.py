"""Fixed-window rate limiter backed by Redis, with an in-process fallback if Redis is unreachable."""

import time
from collections import defaultdict
from threading import Lock

import redis

from app.core.config import get_settings
from app.core.errors import RateLimited
from app.core.logging import log

_client: redis.Redis | None = None
_local: dict[str, tuple[int, int]] = defaultdict(lambda: (0, 0))
_lock = Lock()


def _redis() -> redis.Redis | None:
    global _client
    if _client is None:
        _client = redis.Redis.from_url(
            get_settings().redis_url, socket_timeout=0.5, socket_connect_timeout=0.5
        )
    return _client


def hit(key: str, limit: int, window: int) -> None:
    s = get_settings()
    if not s.rate_limit_enabled:
        return
    bucket = int(time.time() // window)
    full_key = f"rl:{key}:{bucket}"
    count: int
    try:
        r = _redis()
        assert r is not None
        pipe = r.pipeline()
        pipe.incr(full_key)
        pipe.expire(full_key, window + 1)
        count = int(pipe.execute()[0])
    except Exception:  # noqa: BLE001 - degrade to local limiting, never fail open silently
        log.warning("rate_limit_redis_unavailable")
        with _lock:
            b, c = _local[full_key]
            c = c + 1 if b == bucket else 1
            _local[full_key] = (bucket, c)
            count = c
    if count > limit:
        raise RateLimited("Too many requests, slow down", details={"retry_after_seconds": window})


def reset_local() -> None:
    _local.clear()
