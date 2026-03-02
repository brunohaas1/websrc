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

    def delete(self, key: str) -> None:
        self._store.pop(key, None)


class RedisJSONCache:
    def __init__(self, redis_client):
        self.redis = redis_client

    def get(self, key: str) -> Any | None:
        try:
            payload = self.redis.get(key)
            if not payload:
                return None
            if isinstance(payload, bytes):
                payload = payload.decode("utf-8")
            return json.loads(payload)
        except Exception:
            try:
                self.redis.delete(key)
            except Exception:
                pass
            return None

    def set(self, key: str, value: Any, ttl: int) -> None:
        try:
            payload = json.dumps(value, ensure_ascii=False)
            self.redis.setex(key, ttl, payload)
        except Exception:
            pass

    def delete(self, key: str) -> None:
        try:
            self.redis.delete(key)
        except Exception:
            pass


def get_cache(config):
    if config.get("QUEUE_ENABLED"):
        try:
            from redis import Redis

            redis_client = Redis.from_url(config["REDIS_URL"])
            return RedisJSONCache(redis_client)
        except Exception:
            return MemoryTTLCache()

    return MemoryTTLCache()
