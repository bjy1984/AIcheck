from __future__ import annotations

import asyncio
import hashlib
import os
import time
from dataclasses import dataclass
from typing import Any

from libs.security.auth import strict_production

try:
    import redis.asyncio as redis_async
except Exception:  # pragma: no cover - validated through readiness in strict mode
    redis_async = None  # type: ignore[assignment]


PAIR_WINDOW_SECONDS = 600
PAIR_FAILURE_LIMIT = 5
IP_FAILURE_LIMIT = 30
LOCK_SECONDS = 900


class SecurityBackendUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class LoginLimit:
    blocked: bool
    retry_after: int = 0


class SecuritySessionStore:
    def __init__(self) -> None:
        self._redis: Any = None
        self._memory: dict[str, tuple[int, float]] = {}
        self._memory_lock = asyncio.Lock()

    def reset_for_tests(self) -> None:
        self._redis = None
        self._memory.clear()

    def _redis_url(self) -> str:
        return os.getenv("AICHECK_REDIS_URL", "redis://localhost:6379/0")

    async def _client(self):
        if not strict_production():
            return None
        if redis_async is None:
            raise SecurityBackendUnavailable("Redis client is unavailable")
        if self._redis is None:
            self._redis = redis_async.from_url(self._redis_url(), decode_responses=True)
        try:
            await self._redis.ping()
        except Exception as exc:
            self._redis = None
            raise SecurityBackendUnavailable("Redis security backend is unavailable") from exc
        return self._redis

    @staticmethod
    def _digest(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def _pair_key(self, ip: str, username: str) -> str:
        return f"aicheck:security:login:pair:{self._digest(ip + '|' + username.lower())}"

    def _ip_key(self, ip: str) -> str:
        return f"aicheck:security:login:ip:{self._digest(ip)}"

    @staticmethod
    def _lock_key(counter_key: str) -> str:
        return counter_key + ":locked"

    async def ready(self) -> bool:
        if not strict_production():
            return True
        try:
            await self._client()
            return True
        except SecurityBackendUnavailable:
            return False

    async def login_limit(self, ip: str, username: str) -> LoginLimit:
        pair_key = self._pair_key(ip, username)
        ip_key = self._ip_key(ip)
        client = await self._client()
        if client is not None:
            pair_ttl, ip_ttl = await client.ttl(self._lock_key(pair_key)), await client.ttl(self._lock_key(ip_key))
            retry_after = max(int(pair_ttl or 0), int(ip_ttl or 0), 0)
            return LoginLimit(retry_after > 0, retry_after)
        async with self._memory_lock:
            now = time.monotonic()
            expiries = [
                self._memory.get(self._lock_key(pair_key), (0, 0))[1],
                self._memory.get(self._lock_key(ip_key), (0, 0))[1],
            ]
            retry_after = max(int(max(expiries) - now), 0)
            return LoginLimit(retry_after > 0, retry_after)

    async def record_login_failure(self, ip: str, username: str) -> LoginLimit:
        pair_key = self._pair_key(ip, username)
        ip_key = self._ip_key(ip)
        client = await self._client()
        if client is not None:
            pipe = client.pipeline()
            pipe.incr(pair_key)
            pipe.expire(pair_key, PAIR_WINDOW_SECONDS)
            pipe.incr(ip_key)
            pipe.expire(ip_key, PAIR_WINDOW_SECONDS)
            pair_count, _, ip_count, _ = await pipe.execute()
            locks: list[str] = []
            if int(pair_count) >= PAIR_FAILURE_LIMIT:
                locks.append(self._lock_key(pair_key))
            if int(ip_count) >= IP_FAILURE_LIMIT:
                locks.append(self._lock_key(ip_key))
            for key in locks:
                await client.set(key, "1", ex=LOCK_SECONDS)
            return LoginLimit(bool(locks), LOCK_SECONDS if locks else 0)
        async with self._memory_lock:
            now = time.monotonic()
            pair_count = self._increment_memory(pair_key, now, PAIR_WINDOW_SECONDS)
            ip_count = self._increment_memory(ip_key, now, PAIR_WINDOW_SECONDS)
            blocked = pair_count >= PAIR_FAILURE_LIMIT or ip_count >= IP_FAILURE_LIMIT
            if pair_count >= PAIR_FAILURE_LIMIT:
                self._memory[self._lock_key(pair_key)] = (1, now + LOCK_SECONDS)
            if ip_count >= IP_FAILURE_LIMIT:
                self._memory[self._lock_key(ip_key)] = (1, now + LOCK_SECONDS)
            return LoginLimit(blocked, LOCK_SECONDS if blocked else 0)

    def _increment_memory(self, key: str, now: float, ttl: int) -> int:
        count, expires = self._memory.get(key, (0, 0))
        if expires <= now:
            count = 0
        count += 1
        self._memory[key] = (count, now + ttl)
        return count

    async def clear_login_failures(self, ip: str, username: str) -> None:
        pair_key = self._pair_key(ip, username)
        client = await self._client()
        if client is not None:
            await client.delete(pair_key, self._lock_key(pair_key))
            return
        async with self._memory_lock:
            self._memory.pop(pair_key, None)
            self._memory.pop(self._lock_key(pair_key), None)

    async def revoke(self, jti: str, expires_at: int) -> None:
        ttl = max(int(expires_at - time.time()), 1)
        key = f"aicheck:security:revoked:{self._digest(jti)}"
        client = await self._client()
        if client is not None:
            await client.set(key, "1", ex=ttl)
            return
        async with self._memory_lock:
            self._memory[key] = (1, time.monotonic() + ttl)

    async def is_revoked(self, jti: str | None) -> bool:
        if not jti:
            return False
        key = f"aicheck:security:revoked:{self._digest(jti)}"
        client = await self._client()
        if client is not None:
            return bool(await client.exists(key))
        async with self._memory_lock:
            _, expires = self._memory.get(key, (0, 0))
            if expires <= time.monotonic():
                self._memory.pop(key, None)
                return False
            return True


security_sessions = SecuritySessionStore()


def request_client_ip(request) -> str:
    direct_ip = str(getattr(request.client, "host", "") or "unknown")
    if os.getenv("AICHECK_TRUST_PROXY", "false").lower() != "true":
        return direct_ip
    trusted = {item.strip() for item in os.getenv("AICHECK_TRUSTED_PROXIES", "").split(",") if item.strip()}
    if direct_ip not in trusted:
        return direct_ip
    forwarded = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    return forwarded or direct_ip
