from __future__ import annotations

import json

import httpx

from libs.model_capabilities import apply_model_capabilities, capabilities_for, pricing_for
from libs.model_usage import model_cost_cny
from libs.qwen_runtime import QwenRuntimeClient, qwen_runtime_config
from tests.test_qwen_runtime import write_config


def test_capability_table_matches_longest_prefix_and_provider_label() -> None:
    assert capabilities_for("qwen3-8b")["maxOutputTokens"] == 8192
    assert capabilities_for("qwen3-30b-a3b-instruct-2507")["maxOutputTokens"] == 32768
    assert capabilities_for("official_api:qwen-plus")["maxOutputTokens"] == 32768
    assert capabilities_for("qwen3.8-max")["needsThinkingOff"] is False
    assert capabilities_for("some-unknown-model") is None


def test_apply_model_capabilities_clamps_and_injects_thinking_flag() -> None:
    adjusted, changes = apply_model_capabilities(
        "qwen-plus", {"max_tokens": 48000, "temperature": 0.1}
    )
    assert adjusted["max_tokens"] == 32768
    assert adjusted["temperature"] == 0.1
    assert changes["maxTokens"] == {"requested": 48000, "applied": 32768}

    adjusted, changes = apply_model_capabilities("qwen3-8b", {"max_tokens": 4000})
    assert adjusted["enable_thinking"] is False
    assert "maxTokens" not in changes
    assert changes["enableThinking"]["applied"] is False

    # 流式请求不注入 enable_thinking；调用方显式给了的也不覆盖
    adjusted, changes = apply_model_capabilities("qwen3-8b", {"max_tokens": 4000}, streaming=True)
    assert "enable_thinking" not in adjusted
    adjusted, _ = apply_model_capabilities("qwen3-8b", {"enable_thinking": True})
    assert adjusted["enable_thinking"] is True

    # 表里没有的模型原样放行
    adjusted, changes = apply_model_capabilities("gpt-x", {"max_tokens": 999999})
    assert adjusted["max_tokens"] == 999999
    assert changes == {}


def test_official_chat_clamps_request_and_records_change(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("QWEN_API_KEY", "sk-qwen-test")
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.read().decode("utf-8"))
        return httpx.Response(200, json={"id": "x", "choices": [{"message": {"content": "ok"}}]})

    config = qwen_runtime_config(
        write_config(tmp_path),
        env={
            "AICHECK_QWEN_CALL_MODE": "official_api",
            "QWEN_API_BASE": "http://qwen/v1",
            "QWEN_API_KEY": "sk-qwen-test",
        },
    )
    client = QwenRuntimeClient(config=config, transport=httpx.MockTransport(handler))
    response = client.chat_sync(
        [{"role": "user", "content": "ping"}], model="qwen3-8b", max_tokens=48000
    )

    assert seen["body"]["model"] == "qwen3-8b"
    assert seen["body"]["max_tokens"] == 8192
    assert seen["body"]["enable_thinking"] is False
    assert response["modelCapabilities"]["maxTokens"] == {"requested": 48000, "applied": 8192}


def test_model_cost_uses_per_model_pricing_when_known(monkeypatch) -> None:
    usage = {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000}
    default = model_cost_cny(usage)
    assert default["priceSource"] == "default"
    assert default["priceVersion"] == "env-configured-model-pricing-2026-07"

    priced = model_cost_cny(usage, model="qwen-flash")
    assert priced["priceSource"] == "table"
    assert priced["priceVersion"] == "per-model-pricing-2026-09"
    assert priced["model"] == "qwen-flash"
    assert priced["total"] == round(0.15 + 1.5, 6)

    monkeypatch.setenv(
        "AICHECK_MODEL_PRICING_JSON", json.dumps({"qwen-flash": {"input": 1, "output": 1}})
    )
    overridden = model_cost_cny(usage, model="official_api:qwen-flash")
    assert overridden["total"] == 2.0
    assert pricing_for("qwen-flash")["input"] == 1.0
