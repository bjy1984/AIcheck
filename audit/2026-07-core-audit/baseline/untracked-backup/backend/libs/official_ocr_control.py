from __future__ import annotations

import os
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator
from uuid import uuid4


class OfficialOcrControlUnavailable(RuntimeError):
    def __init__(self, message: str, *, retry_after: float = 5.0) -> None:
        super().__init__(message)
        self.retry_after = max(float(retry_after), 1.0)


class OfficialOcrBudgetExceeded(RuntimeError):
    pass


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _strict_production() -> bool:
    return _env_bool("AICHECK_STRICT_PRODUCTION", False)


def _redis_url() -> str:
    return str(os.getenv("AICHECK_REDIS_URL") or "").strip()


def _redis_client():
    url = _redis_url()
    if not url:
        raise OfficialOcrControlUnavailable("Redis URL is not configured for official OCR control")
    try:
        import redis

        return redis.Redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
    except Exception as exc:
        raise OfficialOcrControlUnavailable("Redis is unavailable for official OCR control") from exc


_LOCAL_GUARD = threading.Lock()
_LOCAL_SEMAPHORES: dict[tuple[str, int], threading.BoundedSemaphore] = {}
_LOCAL_BUDGETS: dict[str, float] = {}


def _local_semaphore(scope: str, limit: int) -> threading.BoundedSemaphore:
    key = (scope, limit)
    with _LOCAL_GUARD:
        return _LOCAL_SEMAPHORES.setdefault(key, threading.BoundedSemaphore(limit))


@dataclass
class _RedisSlotLease:
    scope: str
    limit: int
    lease_seconds: int
    wait_seconds: float

    def __post_init__(self) -> None:
        self.limit = max(1, int(self.limit))
        self.lease_seconds = max(30, int(self.lease_seconds))
        self.wait_seconds = max(0.0, float(self.wait_seconds))
        self.token = uuid4().hex
        self.key: str | None = None
        self._client: Any | None = None
        self._stop = threading.Event()
        self._heartbeat: threading.Thread | None = None

    def acquire(self) -> None:
        client = _redis_client()
        deadline = time.monotonic() + self.wait_seconds
        while True:
            for index in range(self.limit):
                key = f"aicheck:ocr:capacity:{self.scope}:{index}"
                try:
                    acquired = client.set(key, self.token, nx=True, ex=self.lease_seconds)
                except Exception as exc:
                    raise OfficialOcrControlUnavailable("Redis capacity lease failed") from exc
                if acquired:
                    self.key = key
                    self._client = client
                    self._heartbeat = threading.Thread(
                        target=self._heartbeat_loop,
                        name=f"ocr-{self.scope}-lease",
                        daemon=True,
                    )
                    self._heartbeat.start()
                    return
            if time.monotonic() >= deadline:
                raise OfficialOcrControlUnavailable(
                    f"Official OCR {self.scope} capacity is full",
                    retry_after=max(self.wait_seconds, 5.0),
                )
            time.sleep(0.1)

    def _heartbeat_loop(self) -> None:
        interval = max(5.0, self.lease_seconds / 3.0)
        script = """
        if redis.call('get', KEYS[1]) == ARGV[1] then
          return redis.call('expire', KEYS[1], ARGV[2])
        end
        return 0
        """
        while not self._stop.wait(interval):
            if not self._client or not self.key:
                return
            try:
                self._client.eval(script, 1, self.key, self.token, self.lease_seconds)
            except Exception:
                return

    def release(self) -> None:
        self._stop.set()
        if self._heartbeat:
            self._heartbeat.join(timeout=1)
        if not self._client or not self.key:
            return
        script = """
        if redis.call('get', KEYS[1]) == ARGV[1] then
          return redis.call('del', KEYS[1])
        end
        return 0
        """
        try:
            self._client.eval(script, 1, self.key, self.token)
        except Exception:
            pass


@contextmanager
def official_ocr_capacity_slot(
    scope: str,
    *,
    limit: int,
    lease_seconds: int,
    wait_seconds: float,
) -> Iterator[None]:
    distributed = _env_bool("AICHECK_OCR_DISTRIBUTED_CONTROL", True)
    if distributed and _redis_url():
        lease = _RedisSlotLease(scope, limit, lease_seconds, wait_seconds)
        lease.acquire()
        try:
            yield
        finally:
            lease.release()
        return
    if distributed and _strict_production():
        raise OfficialOcrControlUnavailable("Redis is required for official OCR capacity control")
    semaphore = _local_semaphore(scope, max(1, int(limit)))
    acquired = semaphore.acquire(timeout=max(0.0, float(wait_seconds)))
    if not acquired:
        raise OfficialOcrControlUnavailable(f"Official OCR {scope} capacity is full")
    try:
        yield
    finally:
        semaphore.release()


@contextmanager
def official_ocr_call_slot(runtime: dict[str, Any]) -> Iterator[None]:
    control = runtime.get("control") if isinstance(runtime.get("control"), dict) else {}
    with official_ocr_capacity_slot(
        "provider-call",
        limit=int(control.get("globalCallConcurrency") or 4),
        lease_seconds=int(control.get("callLeaseSeconds") or 180),
        wait_seconds=float(control.get("capacityWaitSeconds") or 5),
    ):
        yield


@contextmanager
def official_ocr_document_slot(runtime: dict[str, Any]) -> Iterator[None]:
    control = runtime.get("control") if isinstance(runtime.get("control"), dict) else {}
    with official_ocr_capacity_slot(
        "document",
        limit=int(control.get("globalDocumentConcurrency") or 2),
        lease_seconds=int(control.get("documentLeaseSeconds") or 300),
        wait_seconds=float(control.get("capacityWaitSeconds") or 5),
    ):
        yield


class RedisOfficialOcrCircuitBreaker:
    def __init__(self, failure_threshold: int, open_seconds: int) -> None:
        self.failure_threshold = max(1, int(failure_threshold))
        self.open_seconds = max(1, int(open_seconds))
        self.prefix = "aicheck:ocr:circuit:aliyun"

    def _client(self):
        return _redis_client()

    def before_call(self) -> None:
        try:
            client = self._client()
            ttl = int(client.ttl(f"{self.prefix}:open") or -1)
            if ttl > 0:
                raise OfficialOcrControlUnavailable("Aliyun OCR circuit is open", retry_after=ttl)
            failures = int(client.get(f"{self.prefix}:failures") or 0)
            if failures < self.failure_threshold:
                return
            half_open = client.set(
                f"{self.prefix}:half-open",
                uuid4().hex,
                nx=True,
                ex=max(self.open_seconds, 30),
            )
            if not half_open:
                raise OfficialOcrControlUnavailable(
                    "Aliyun OCR circuit is waiting for a half-open probe",
                    retry_after=self.open_seconds,
                )
        except OfficialOcrControlUnavailable:
            raise
        except Exception as exc:
            if _strict_production():
                raise OfficialOcrControlUnavailable("Redis circuit breaker is unavailable") from exc

    def success(self) -> None:
        try:
            self._client().delete(
                f"{self.prefix}:failures",
                f"{self.prefix}:open",
                f"{self.prefix}:half-open",
                f"{self.prefix}:last-error",
            )
        except Exception:
            # The provider response is already complete. The next capacity acquisition
            # will fail closed if Redis remains unavailable.
            return

    def failure(self, reason: str) -> None:
        try:
            client = self._client()
            failures = int(client.incr(f"{self.prefix}:failures"))
            client.expire(f"{self.prefix}:failures", max(self.open_seconds * 4, 120))
            client.set(f"{self.prefix}:last-error", str(reason)[:120], ex=max(self.open_seconds * 4, 120))
            client.delete(f"{self.prefix}:half-open")
            if failures >= self.failure_threshold:
                client.set(f"{self.prefix}:open", "1", ex=self.open_seconds)
        except Exception:
            return

    def public_status(self) -> dict[str, Any]:
        try:
            client = self._client()
            ttl = int(client.ttl(f"{self.prefix}:open") or -1)
            return {
                "distributed": True,
                "ready": True,
                "open": ttl > 0,
                "failureCount": int(client.get(f"{self.prefix}:failures") or 0),
                "failureThreshold": self.failure_threshold,
                "retryAfterSeconds": max(ttl, 0),
                "lastError": client.get(f"{self.prefix}:last-error"),
            }
        except Exception:
            return {
                "distributed": True,
                "ready": False,
                "open": _strict_production(),
                "failureCount": 0,
                "failureThreshold": self.failure_threshold,
                "retryAfterSeconds": 0,
                "lastError": "redis_unavailable",
            }


def official_ocr_control_status(runtime: dict[str, Any]) -> dict[str, Any]:
    control = runtime.get("control") if isinstance(runtime.get("control"), dict) else {}
    status: dict[str, Any] = {
        "distributed": _env_bool("AICHECK_OCR_DISTRIBUTED_CONTROL", True),
        "globalCallConcurrency": int(control.get("globalCallConcurrency") or 4),
        "globalDocumentConcurrency": int(control.get("globalDocumentConcurrency") or 2),
        "ready": True,
        "activeCallSlots": None,
        "activeDocumentSlots": None,
    }
    if not status["distributed"] or not _redis_url():
        status["ready"] = not _strict_production()
        return status
    try:
        client = _redis_client()
        status["activeCallSlots"] = len(client.keys("aicheck:ocr:capacity:provider-call:*"))
        status["activeDocumentSlots"] = len(client.keys("aicheck:ocr:capacity:document:*"))
    except Exception:
        status["ready"] = False
    return status


def reserve_official_ocr_cost(budget_key: str, amount: float, limit: float) -> float:
    amount = max(float(amount), 0.0)
    limit = max(float(limit), 0.01)
    redis_key = f"aicheck:ocr:budget:{budget_key}"
    distributed = _env_bool("AICHECK_OCR_DISTRIBUTED_CONTROL", True)
    if distributed and _redis_url():
        script = """
        local current = tonumber(redis.call('get', KEYS[1]) or '0')
        local requested = tonumber(ARGV[1])
        local limit = tonumber(ARGV[2])
        if current + requested > limit then
          return {-1, tostring(current)}
        end
        local updated = redis.call('incrbyfloat', KEYS[1], requested)
        redis.call('expire', KEYS[1], ARGV[3])
        return {1, tostring(updated)}
        """
        try:
            result = _redis_client().eval(script, 1, redis_key, amount, limit, 172800)
            if int(result[0]) != 1:
                raise OfficialOcrBudgetExceeded(f"Official OCR document cost limit {limit:.2f} CNY exceeded")
            return float(result[1])
        except OfficialOcrBudgetExceeded:
            raise
        except Exception as exc:
            if _strict_production():
                raise OfficialOcrControlUnavailable("Redis OCR cost budget is unavailable") from exc
    elif distributed and _strict_production():
        raise OfficialOcrControlUnavailable("Redis is required for official OCR cost budgets")
    with _LOCAL_GUARD:
        current = float(_LOCAL_BUDGETS.get(budget_key, 0.0))
        if current + amount > limit:
            raise OfficialOcrBudgetExceeded(f"Official OCR document cost limit {limit:.2f} CNY exceeded")
        updated = current + amount
        _LOCAL_BUDGETS[budget_key] = updated
        return updated


def adjust_official_ocr_cost(budget_key: str, delta: float) -> float:
    redis_key = f"aicheck:ocr:budget:{budget_key}"
    distributed = _env_bool("AICHECK_OCR_DISTRIBUTED_CONTROL", True)
    if distributed and _redis_url():
        try:
            client = _redis_client()
            updated = float(client.incrbyfloat(redis_key, float(delta)))
            if updated < 0:
                client.set(redis_key, "0", ex=172800)
                return 0.0
            client.expire(redis_key, 172800)
            return updated
        except Exception as exc:
            if _strict_production():
                raise OfficialOcrControlUnavailable("Redis OCR cost budget update failed") from exc
    elif distributed and _strict_production():
        raise OfficialOcrControlUnavailable("Redis is required for official OCR cost budgets")
    with _LOCAL_GUARD:
        updated = max(0.0, float(_LOCAL_BUDGETS.get(budget_key, 0.0)) + float(delta))
        _LOCAL_BUDGETS[budget_key] = updated
        return updated
