from __future__ import annotations

import json
import time
from typing import Any


class MemoryTTLCache:
    def __init__(self):
        self._store: dict[str, tuple[float, str]] = {}

    def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if not entry:
            return None

        expires_at, payload = entry
        if expires_at < time.time():
            self._store.pop(key, None)
            return None

        return json.loads(payload)

    def set(self, key: str, value: Any, ttl: int) -> None:
        self._store[key] = (
            time.time() + ttl,
            json.dumps(value, ensure_ascii=False),
        )


class RedisJSONCache:
    def __init__(self, redis_client):
        self.redis = redis_client

    def get(self, key: str) -> Any | None:
        payload = self.redis.get(key)
        if not payload:
            return None
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8")
        return json.loads(payload)

    def set(self, key: str, value: Any, ttl: int) -> None:
        payload = json.dumps(value, ensure_ascii=False)
        self.redis.setex(key, ttl, payload)


def get_cache(config):
    if config.get("QUEUE_ENABLED"):
        try:
            from redis import Redis

            redis_client = Redis.from_url(config["REDIS_URL"])
            return RedisJSONCache(redis_client)
        except Exception:
            return MemoryTTLCache()

    return MemoryTTLCache()
