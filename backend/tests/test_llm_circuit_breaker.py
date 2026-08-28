"""LLM 断路器：只计供应商级故障；达到阈值熔断；Redis 不可用时 fail-open。"""

from __future__ import annotations

import pytest

from libs.integrations import llm_circuit_breaker as breaker
from libs.integrations.errors import IntegrationServiceError


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, int | str] = {}
        self.ttls: dict[str, int] = {}

    def incr(self, key: str) -> int:
        self.store[key] = int(self.store.get(key, 0)) + 1
        return int(self.store[key])

    def expire(self, key: str, seconds: int) -> None:
        self.ttls[key] = seconds

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.store[key] = value
        if ex is not None:
            self.ttls[key] = ex

    def delete(self, key: str) -> None:
        self.store.pop(key, None)
        self.ttls.pop(key, None)

    def ttl(self, key: str) -> int:
        if key not in self.store:
            return -2
        return self.ttls.get(key, -1)


@pytest.fixture()
def fake_redis(monkeypatch) -> FakeRedis:
    fake = FakeRedis()
    monkeypatch.setattr(breaker, "_redis_client", lambda: fake)
    monkeypatch.delenv("AICHECK_LLM_BREAKER_DISABLED", raising=False)
    return fake


def _provider_fault() -> IntegrationServiceError:
    return IntegrationServiceError("Qwen official API", "chat.completions", status_code=502)


def test_trips_after_threshold_and_fast_fails(fake_redis, monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_LLM_BREAKER_THRESHOLD", "3")
    host = "api.deepseek.com"
    for _ in range(2):
        breaker.record_failure(host, _provider_fault())
        breaker.ensure_closed(host)  # 未达阈值不熔断
    breaker.record_failure(host, _provider_fault())
    with pytest.raises(IntegrationServiceError) as exc_info:
        breaker.ensure_closed(host)
    assert exc_info.value.reason == "LLM_CIRCUIT_OPEN"


def test_business_4xx_does_not_count(fake_redis, monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_LLM_BREAKER_THRESHOLD", "1")
    host = "api.deepseek.com"
    # 模型名错 / 上下文超限是调用方问题，熔断只会掩盖它
    breaker.record_failure(
        host, IntegrationServiceError("Qwen official API", "chat.completions", status_code=400)
    )
    breaker.ensure_closed(host)  # 不应熔断
    # 429 属于供应商侧限流，计数
    breaker.record_failure(
        host, IntegrationServiceError("Qwen official API", "chat.completions", status_code=429)
    )
    with pytest.raises(IntegrationServiceError):
        breaker.ensure_closed(host)


def test_success_resets_failure_window(fake_redis, monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_LLM_BREAKER_THRESHOLD", "2")
    host = "api.deepseek.com"
    breaker.record_failure(host, _provider_fault())
    breaker.record_success(host)
    breaker.record_failure(host, _provider_fault())
    breaker.ensure_closed(host)  # 计数被成功重置过，未达阈值


def test_redis_unavailable_fails_open(monkeypatch) -> None:
    monkeypatch.setattr(breaker, "_redis_client", lambda: None)
    host = "api.deepseek.com"
    breaker.record_failure(host, _provider_fault())
    breaker.ensure_closed(host)  # 断路器不能变成新的单点


def test_network_reason_counts_as_provider_fault() -> None:
    assert breaker.is_provider_fault(
        IntegrationServiceError("Qwen official API", "chat.completions", reason="CONNECTERROR")
    )
    assert not breaker.is_provider_fault(RuntimeError("misc"))
