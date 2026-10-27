"""skill 网页授权：浏览器里已登录的监检或管理员点「授权」，平台把一次性授权码回调给本机的 skill，
skill 再用只有它知道的 PKCE 校验码把授权码换成令牌。口令从不经过 skill 和助手。

- 回调地址只认本机：http://127.0.0.1:<端口>/callback（localhost、[::1] 同理），授权码不会被送到别的主机；
- 授权码 120 秒内有效、只能换一次，服务器只存它的 sha256；
- 换令牌要出示与授权时 code_challenge 对应的 code_verifier（S256），截获授权码的人换不到令牌。

严格生产模式下授权码放 Redis（多个 API 进程共享，连不上就拒绝，不退回内存）；
否则放进程内字典（本地开发、测试），与 libs/security/session.py 同一套规矩。
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
import re
import time
from typing import Any
from urllib.parse import urlsplit

from libs.security.auth import strict_production
from libs.security.session import SecurityBackendUnavailable

try:
    import redis.asyncio as redis_async
except ImportError:  # pragma: no cover - validated through readiness in strict mode
    redis_async = None  # type: ignore[assignment]

CODE_TTL_SECONDS = 120
ALLOWED_ROLES = frozenset({"inspection", "admin"})
CLIENT_NAME = "AIcheck 节点审计 skill"
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
_CHALLENGE_RE = re.compile(r"[A-Za-z0-9_-]{43}")
_VERIFIER_RE = re.compile(r"[A-Za-z0-9._~-]{43,128}")
_CODE_RE = re.compile(r"[A-Za-z0-9_-]{20,100}")


def loopback_redirect_uri(value: Any) -> str | None:
    """只接受本机回调地址，原样返回；其余一律 None。"""
    if not isinstance(value, str) or len(value) > 100:
        return None
    parts = urlsplit(value)
    if parts.scheme != "http" or parts.username or parts.password or parts.query or parts.fragment:
        return None
    if parts.hostname not in LOOPBACK_HOSTS or parts.path != "/callback":
        return None
    try:
        port = parts.port
    except ValueError:
        return None
    if not port or port < 1024:
        return None
    return value


def valid_challenge(value: Any) -> bool:
    return isinstance(value, str) and bool(_CHALLENGE_RE.fullmatch(value))


def valid_verifier(value: Any) -> bool:
    return isinstance(value, str) and bool(_VERIFIER_RE.fullmatch(value))


def valid_code(value: Any) -> bool:
    return isinstance(value, str) and bool(_CODE_RE.fullmatch(value))


def pkce_challenge(verifier: str) -> str:
    """RFC 7636 S256：base64url(sha256(verifier))，去掉末尾的 =。"""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def pkce_matches(verifier: str, challenge: str) -> bool:
    return hmac.compare_digest(pkce_challenge(verifier), challenge)


class SkillAuthCodeStore:
    def __init__(self) -> None:
        self._redis: Any = None
        self._memory: dict[str, tuple[float, str]] = {}
        self._memory_lock = asyncio.Lock()

    def reset_for_tests(self) -> None:
        self._redis = None
        self._memory.clear()

    async def _client(self):
        if not strict_production():
            return None
        if redis_async is None:
            raise SecurityBackendUnavailable("Redis client is unavailable")
        if self._redis is None:
            self._redis = redis_async.from_url(os.getenv("AICHECK_REDIS_URL", "redis://localhost:6379/0"), decode_responses=True)
        try:
            await self._redis.ping()
        except Exception as exc:
            self._redis = None
            raise SecurityBackendUnavailable("Redis security backend is unavailable") from exc
        return self._redis

    @staticmethod
    def _key(code: str) -> str:
        return "aicheck:security:skill-auth:code:" + hashlib.sha256(code.encode("utf-8")).hexdigest()

    async def put(self, code: str, record: dict[str, Any]) -> None:
        payload = json.dumps(record, ensure_ascii=False)
        client = await self._client()
        if client is not None:
            await client.set(self._key(code), payload, ex=CODE_TTL_SECONDS)
            return
        async with self._memory_lock:
            now = time.time()
            for key in [key for key, (expires, _) in self._memory.items() if expires <= now]:
                self._memory.pop(key, None)
            self._memory[self._key(code)] = (now + CODE_TTL_SECONDS, payload)

    async def take(self, code: str) -> dict[str, Any] | None:
        """取出并删除：一次性。过期、不存在都返回 None。"""
        key = self._key(code)
        client = await self._client()
        if client is not None:
            async with client.pipeline(transaction=True) as pipe:
                pipe.get(key)
                pipe.delete(key)
                payload, _ = await pipe.execute()
        else:
            async with self._memory_lock:
                expires, payload = self._memory.pop(key, (0.0, None))
                if expires <= time.time():
                    payload = None
        return json.loads(payload) if payload else None


skill_auth_codes = SkillAuthCodeStore()
