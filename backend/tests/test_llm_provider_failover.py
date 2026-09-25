"""LLM 双供应商降级路由：主供应商级故障/熔断 → 备胎；业务错误不转移。

主供应商（DeepSeek）是唯一「别人打喷嚏你停摆」的外部单点。降级规矩：
- 只在供应商级故障（5xx/429/网络超时）或主供应商熔断时转移；
- 4xx 业务错误原样抛——换供应商掩盖不了模型名错/上下文超限；
- 备胎地址与密钥两个都配齐才生效（与 vision_override 同规矩）；
- 每次调用先试主供应商（除非熔断开着），主恢复后自动切回。
"""

from __future__ import annotations

import pytest

from libs import qwen_runtime
from libs.integrations import llm_circuit_breaker
from libs.integrations.errors import IntegrationServiceError


@pytest.fixture(autouse=True)
def _no_breaker_redis(monkeypatch):
    """断路器 fail-open：这些测试只验转移逻辑，不掺 Redis。"""
    monkeypatch.setattr(llm_circuit_breaker, "_redis_client", lambda: None)


def _client(monkeypatch, *, fallback_configured: bool = True) -> qwen_runtime.QwenRuntimeClient:
    if fallback_configured:
        monkeypatch.setenv("AICHECK_LLM_FALLBACK_API_BASE", "https://dashscope.example/compatible-mode/v1")
        monkeypatch.setenv("AICHECK_LLM_FALLBACK_API_KEY", "sk-fallback")
    else:
        monkeypatch.delenv("AICHECK_LLM_FALLBACK_API_BASE", raising=False)
        monkeypatch.delenv("AICHECK_LLM_FALLBACK_API_KEY", raising=False)
    config = {
        "mode": "official_api",
        "provider": "DeepSeek",
        "baseUrl": "https://api.deepseek.com",
        "models": {"projectReview": "deepseek-v4-pro"},
        "yamlOfficialModels": {"projectReview": "qwen3.7-plus"},
    }
    return qwen_runtime.QwenRuntimeClient(config=config, server_client=None)


def _provider_fault() -> IntegrationServiceError:
    return IntegrationServiceError("Qwen official API", "chat.completions", status_code=502)


def test_供应商级故障转移到备胎并带降级标记(monkeypatch):
    client = _client(monkeypatch)
    calls: list[dict] = []

    def fake_official(messages, role_or_model, _provider=None, **kwargs):
        calls.append({"provider": _provider, "role": role_or_model})
        if _provider is None:
            raise _provider_fault()
        return {"id": "RESP-FB", "model": kwargs.get("_m", "resolved-later")}

    monkeypatch.setattr(client, "_official_chat_sync", fake_official)
    result = client.chat_sync([{"role": "user", "content": "x"}], model="project-review-large")

    assert len(calls) == 2
    assert calls[0]["provider"] is None  # 先试主供应商
    fallback = calls[1]["provider"]
    assert fallback["baseUrl"] == "https://dashscope.example/compatible-mode/v1"
    assert fallback["models"]["projectReview"] == "qwen3.7-plus"  # yaml 默认值，不是 deepseek 名
    assert result["providerFailover"]["from"] == "DeepSeek"


def test_业务4xx不转移(monkeypatch):
    client = _client(monkeypatch)

    def fake_official(messages, role_or_model, _provider=None, **kwargs):
        raise IntegrationServiceError("Qwen official API", "chat.completions", status_code=400)

    monkeypatch.setattr(client, "_official_chat_sync", fake_official)
    with pytest.raises(IntegrationServiceError) as exc_info:
        client.chat_sync([{"role": "user", "content": "x"}], model="project-review-large")
    assert exc_info.value.status_code == 400  # 原样抛，不被备胎吞掉


def test_主供应商熔断时直接走备胎(monkeypatch):
    client = _client(monkeypatch)
    dispatch_calls: list[str] = []

    def fake_ensure(host):
        if host == "api.deepseek.com":
            raise IntegrationServiceError("LLM circuit breaker", host, reason="LLM_CIRCUIT_OPEN")

    monkeypatch.setattr(llm_circuit_breaker, "ensure_closed", fake_ensure)

    def fake_official(messages, role_or_model, _provider=None, **kwargs):
        dispatch_calls.append("fallback" if _provider else "primary")
        assert _provider is not None
        return {"id": "RESP-FB"}

    monkeypatch.setattr(client, "_official_chat_sync", fake_official)
    result = client.chat_sync([{"role": "user", "content": "x"}], model="project-review-large")
    assert dispatch_calls == ["fallback"]  # 主供应商连打都没打
    assert result["providerFailover"]["from"] == "DeepSeek"


def test_没配备胎时原样抛(monkeypatch):
    client = _client(monkeypatch, fallback_configured=False)

    def fake_official(messages, role_or_model, _provider=None, **kwargs):
        raise _provider_fault()

    monkeypatch.setattr(client, "_official_chat_sync", fake_official)
    with pytest.raises(IntegrationServiceError) as exc_info:
        client.chat_sync([{"role": "user", "content": "x"}], model="project-review-large")
    assert exc_info.value.status_code == 502


def test_备胎只配一半不生效(monkeypatch):
    monkeypatch.setenv("AICHECK_LLM_FALLBACK_API_BASE", "https://dashscope.example/v1")
    monkeypatch.delenv("AICHECK_LLM_FALLBACK_API_KEY", raising=False)
    assert qwen_runtime.fallback_provider({"yamlOfficialModels": {}}) == {}


def test_备胎模型名可用环境变量覆盖(monkeypatch):
    monkeypatch.setenv("AICHECK_LLM_FALLBACK_API_BASE", "https://dashscope.example/v1")
    monkeypatch.setenv("AICHECK_LLM_FALLBACK_API_KEY", "sk-fallback")
    monkeypatch.setenv("AICHECK_LLM_FALLBACK_MODEL_PROJECT_REVIEW", "qwen3.8-max")
    fallback = qwen_runtime.fallback_provider({"yamlOfficialModels": {"projectReview": "qwen3.7-plus"}})
    assert fallback["models"]["projectReview"] == "qwen3.8-max"


def _rate_limited() -> IntegrationServiceError:
    return IntegrationServiceError("Qwen official API", "chat.completions", status_code=429)


def test_限流429先在主供应商上退避重试_过了就不转移(monkeypatch):
    """2026-09-24 灰度：Token Plan 按分钟限流，一次 429 就转去欠费的备胎，30 个分片落空。"""
    client = _client(monkeypatch)
    calls: list[object] = []
    slept: list[float] = []
    monkeypatch.setenv("AICHECK_LLM_RATE_LIMIT_BACKOFF_SECONDS", "5")
    monkeypatch.setattr(qwen_runtime.time, "sleep", slept.append)

    def fake_official(messages, role_or_model, _provider=None, **kwargs):
        calls.append(_provider)
        if len(calls) < 3:
            raise _rate_limited()
        return {"id": "RESP-PRIMARY"}

    monkeypatch.setattr(client, "_official_chat_sync", fake_official)
    result = client.chat_sync([{"role": "user", "content": "x"}], model="project-review-large")

    assert result["id"] == "RESP-PRIMARY" and "providerFailover" not in result
    assert calls == [None, None, None]  # 三次都打主供应商
    assert len(slept) == 2 and 4 <= slept[0] <= 6 and 8 <= slept[1] <= 12  # 5s、10s，带抖动


def test_限流重试用尽才转移_重试期间不计熔断(monkeypatch):
    client = _client(monkeypatch)
    monkeypatch.setenv("AICHECK_LLM_RATE_LIMIT_RETRIES", "2")
    failures: list[int] = []
    monkeypatch.setattr(llm_circuit_breaker, "record_failure", lambda host, exc: failures.append(exc.status_code))
    providers: list[object] = []

    def fake_official(messages, role_or_model, _provider=None, **kwargs):
        providers.append(_provider)
        if _provider is None:
            raise _rate_limited()
        return {"id": "RESP-FB"}

    monkeypatch.setattr(client, "_official_chat_sync", fake_official)
    result = client.chat_sync([{"role": "user", "content": "x"}], model="project-review-large")

    assert providers[:3] == [None, None, None] and providers[3] is not None
    assert result["providerFailover"]["from"] == "DeepSeek"
    assert failures == [429], "一次调用只记一次主供应商故障，重试不把它熔断"


def test_备胎欠费402时报主供应商的真实原因(monkeypatch):
    client = _client(monkeypatch)
    monkeypatch.setenv("AICHECK_LLM_RATE_LIMIT_RETRIES", "0")

    def fake_official(messages, role_or_model, _provider=None, **kwargs):
        if _provider is None:
            raise _rate_limited()
        raise IntegrationServiceError("Qwen official API", "chat.completions", status_code=402)

    monkeypatch.setattr(client, "_official_chat_sync", fake_official)
    with pytest.raises(IntegrationServiceError) as exc_info:
        client.chat_sync([{"role": "user", "content": "x"}], model="project-review-large")
    assert exc_info.value.status_code == 429


def test_备胎熔断时不转移_报主供应商原错误(monkeypatch):
    client = _client(monkeypatch)
    monkeypatch.setenv("AICHECK_LLM_RATE_LIMIT_RETRIES", "0")

    def fallback_open(host):
        if host == "dashscope.example":
            raise IntegrationServiceError("LLM circuit breaker", host, reason="LLM_CIRCUIT_OPEN")

    monkeypatch.setattr(llm_circuit_breaker, "ensure_closed", fallback_open)
    providers: list[object] = []

    def fake_official(messages, role_or_model, _provider=None, **kwargs):
        providers.append(_provider)
        raise _rate_limited()

    monkeypatch.setattr(client, "_official_chat_sync", fake_official)
    with pytest.raises(IntegrationServiceError) as exc_info:
        client.chat_sync([{"role": "user", "content": "x"}], model="project-review-large")
    assert exc_info.value.status_code == 429
    assert providers == [None], "备胎熔断中就别再打它"


def test_非限流错误不重试(monkeypatch):
    client = _client(monkeypatch, fallback_configured=False)
    calls: list[object] = []

    def fake_official(messages, role_or_model, _provider=None, **kwargs):
        calls.append(_provider)
        raise _provider_fault()

    monkeypatch.setattr(client, "_official_chat_sync", fake_official)
    with pytest.raises(IntegrationServiceError):
        client.chat_sync([{"role": "user", "content": "x"}], model="project-review-large")
    assert len(calls) == 1


def _quota_exhausted() -> IntegrationServiceError:
    return IntegrationServiceError("Qwen official API", "chat.completions", status_code=429, reason="INSUFFICIENT_QUOTA")


def test_额度用尽的429不重试_直接转移(monkeypatch):
    """2026-09-25：Token Plan 额度用完回 429 insufficient_quota，每次都白等三轮退避。"""
    client = _client(monkeypatch)
    slept: list[float] = []
    monkeypatch.setenv("AICHECK_LLM_RATE_LIMIT_BACKOFF_SECONDS", "5")
    monkeypatch.setattr(qwen_runtime.time, "sleep", slept.append)
    providers: list[object] = []

    def fake_official(messages, role_or_model, _provider=None, **kwargs):
        providers.append(_provider)
        if _provider is None:
            raise _quota_exhausted()
        return {"id": "RESP-FB"}

    monkeypatch.setattr(client, "_official_chat_sync", fake_official)
    result = client.chat_sync([{"role": "user", "content": "x"}], model="project-review-large")
    assert providers[0] is None and providers[1] is not None and len(providers) == 2
    assert slept == []
    assert result["id"] == "RESP-FB"


def test_串流失败时从响应体取错误码() -> None:
    import httpx

    body = b'{"error":{"message":"Your token-plan quota has been exhausted.","code":"insufficient_quota"}}'
    response = httpx.Response(429, content=body)
    assert qwen_runtime._error_code(response) == "INSUFFICIENT_QUOTA"
    assert qwen_runtime._error_code(httpx.Response(429, content=b"not json")) is None
