"""LLM 连续失败断路器（Redis 共享，跨 worker/API 进程）。

## 为什么需要

供应商整体故障时，每个任务各自把重试烧完（单次模型调用超时可配到 600 秒），
队列被一单一单拖死。断路器把「供应商挂了」变成快速失败：滑动窗口内
供应商级故障达到阈值 → 冷却期内直接拒绝外呼（LLM_CIRCUIT_OPEN），
上层的既有失败路径（落 failed 终态、可重试）自然接住。

## 三条设计约束

1. 只认**供应商级**故障：网络错误、超时、HTTP 5xx/429。4xx 业务错误
   （模型名错、上下文超限）不计数——那是调用方的问题，熔断只会掩盖它。
2. Redis 不可用时降级为**不熔断**（fail-open）：断路器是保护，
   不能让保护装置本身变成新的单点。
3. 状态放 Redis 而不是进程内存：四个 worker 容器 + API 各自进程，
   进程内计数永远数不满阈值。

环境变量（都有默认值，不配即生效）：
AICHECK_LLM_BREAKER_THRESHOLD=5 / _WINDOW_SECONDS=120 / _COOLDOWN_SECONDS=60
AICHECK_LLM_BREAKER_DISABLED=true 一键停用。
"""

from __future__ import annotations

import logging
import os
from typing import Any

from libs.integrations.errors import IntegrationServiceError

LOGGER = logging.getLogger(__name__)

# 供应商级故障的 reason 集合（httpx 异常类名大写化后的形态）
_PROVIDER_FAULT_REASONS = {
    "CONNECTERROR",
    "CONNECTTIMEOUT",
    "READTIMEOUT",
    "WRITETIMEOUT",
    "POOLTIMEOUT",
    "TIMEOUTEXCEPTION",
    "REMOTEPROTOCOLERROR",
    "PROXYERROR",
}


def _redis_client():
    try:
        import redis  # noqa: PLC0415 - 依赖 celery[redis]，按需加载

        return redis.Redis.from_url(
            os.getenv("AICHECK_CELERY_BROKER_URL", "redis://aicheck-redis:6379/0"),
            socket_connect_timeout=0.5,
            socket_timeout=0.5,
        )
    except Exception:  # noqa: BLE001 - fail-open
        return None


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _enabled() -> bool:
    return os.getenv("AICHECK_LLM_BREAKER_DISABLED", "").strip().lower() not in {
        "1",
        "true",
        "yes",
    }


def is_provider_fault(exc: Exception) -> bool:
    """供应商级故障才计数；4xx 业务错误不计（熔断只会掩盖调用方问题）。"""
    if not isinstance(exc, IntegrationServiceError):
        return False
    status = exc.status_code
    if status is not None:
        return status >= 500 or status == 429
    return (exc.reason or "") in _PROVIDER_FAULT_REASONS


def ensure_closed(host: str) -> None:
    """熔断打开时抛 LLM_CIRCUIT_OPEN 快速失败；否则无事发生。"""
    if not _enabled() or not host:
        return
    client = _redis_client()
    if client is None:
        return
    try:
        opened = client.ttl(f"llm:breaker:{host}:open")
    except Exception:  # noqa: BLE001 - fail-open
        return
    if opened and opened > 0:
        raise IntegrationServiceError(
            "LLM circuit breaker",
            host,
            reason="LLM_CIRCUIT_OPEN",
        )


def record_failure(host: str, exc: Exception) -> None:
    if not _enabled() or not host or not is_provider_fault(exc):
        return
    client = _redis_client()
    if client is None:
        return
    threshold = _int_env("AICHECK_LLM_BREAKER_THRESHOLD", 5)
    window = _int_env("AICHECK_LLM_BREAKER_WINDOW_SECONDS", 120)
    cooldown = _int_env("AICHECK_LLM_BREAKER_COOLDOWN_SECONDS", 60)
    try:
        key = f"llm:breaker:{host}:failures"
        count = client.incr(key)
        if count == 1:
            client.expire(key, window)
        if int(count) >= threshold:
            client.set(f"llm:breaker:{host}:open", "1", ex=cooldown)
            client.delete(key)
            LOGGER.warning(
                "LLM 断路器熔断：%s 在 %ss 内供应商级故障 %s 次，冷却 %ss",
                host,
                window,
                count,
                cooldown,
            )
    except Exception:  # noqa: BLE001 - fail-open
        return


def record_success(host: str) -> None:
    if not _enabled() or not host:
        return
    client = _redis_client()
    if client is None:
        return
    try:
        client.delete(f"llm:breaker:{host}:failures")
    except Exception:  # noqa: BLE001 - fail-open
        return


def breaker_host(config: dict[str, Any]) -> str:
    base = str(config.get("baseUrl") or "")
    return base.split("//", 1)[-1].split("/", 1)[0].split(":", 1)[0]
