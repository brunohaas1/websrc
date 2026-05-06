from __future__ import annotations

import json
import time
from typing import Any

_MAX_MEMORY_ENTRIES = 512


class MemoryTTLCache:
    def __init__(self) -> None:
        self._store: dict[str, tuple[float, str]] = {}
        self._hits = 0
        self._misses = 0

    def _evict_expired(self) -> None:
        now = time.time()
        expired = [k for k, (exp, _) in self._store.items() if exp < now]
        for k in expired:
            self._store.pop(k, None)

    def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if not entry:
            self._misses += 1
            return None

        expires_at, payload = entry
        if expires_at < time.time():
            self._store.pop(key, None)
            self._misses += 1
            return None

        self._hits += 1
        return json.loads(payload)

    def set(self, key: str, value: Any, ttl: int) -> None:
        if len(self._store) >= _MAX_MEMORY_ENTRIES:
            self._evict_expired()
        self._store[key] = (
            time.time() + ttl,
            json.dumps(value, ensure_ascii=False),
        )

    def delete(self, key: str) -> None:
        self._store.pop(key, None)

    def delete_prefix(self, prefix: str) -> None:
        keys = [k for k in self._store.keys() if k.startswith(prefix)]
        for key in keys:
            self._store.pop(key, None)

    def get_stats(self) -> dict[str, Any]:
        total = self._hits + self._misses
        hit_rate = (self._hits / total) if total else 0.0
        return {
            "backend": "memory",
            "hits": self._hits,
            "misses": self._misses,
            "total": total,
            "hit_rate": round(hit_rate, 4),
            "size": len(self._store),
            "max_entries": _MAX_MEMORY_ENTRIES,
        }


class RedisJSONCache:
    def __init__(self, redis_client):
        self.redis = redis_client
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> Any | None:
        try:
            payload = self.redis.get(key)
            if not payload:
                self._misses += 1
                return None
            if isinstance(payload, bytes):
                payload = payload.decode("utf-8")
            self._hits += 1
            return json.loads(payload)
        except Exception:
            try:
                self.redis.delete(key)
            except Exception:
                pass
            self._misses += 1
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

    def delete_prefix(self, prefix: str) -> None:
        try:
            keys = list(self.redis.scan_iter(match=f"{prefix}*"))
            if keys:
                self.redis.delete(*keys)
        except Exception:
            pass

    def get_stats(self) -> dict[str, Any]:
        total = self._hits + self._misses
        hit_rate = (self._hits / total) if total else 0.0
        return {
            "backend": "redis",
            "hits": self._hits,
            "misses": self._misses,
            "total": total,
            "hit_rate": round(hit_rate, 4),
        }


_shared_redis = None


def get_redis_client(config: dict[str, Any]) -> Any:
    """Return a shared Redis client, creating it once."""
    global _shared_redis
    if _shared_redis is None:
        from redis import Redis
        _shared_redis = Redis.from_url(config["REDIS_URL"])
    return _shared_redis


def get_cache(config: dict[str, Any]) -> MemoryTTLCache | RedisJSONCache:
    if config.get("QUEUE_ENABLED"):
        try:
            redis_client = get_redis_client(config)
            return RedisJSONCache(redis_client)
        except Exception:
            return MemoryTTLCache()

    return MemoryTTLCache()
