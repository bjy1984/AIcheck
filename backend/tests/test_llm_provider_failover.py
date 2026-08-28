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
