from __future__ import annotations

import json
from pathlib import Path

import httpx

from libs.qwen_runtime import (
    CONFIG_PATH,
    QwenRuntimeClient,
    qwen_runtime_config,
    qwen_runtime_public_config,
)

CONFIG_TEXT = """
schemaVersion: aicheck-qwen-runtime@1
modeEnv: AICHECK_QWEN_CALL_MODE
defaultMode: server
providers:
  server:
    baseUrlEnv: AICHECK_QWEN_SERVER_BASE_URL
    apiKeyEnv: AICHECK_QWEN_SERVER_API_KEY
    aliases:
      review: review-chat
      default: default-chat
      compareFast: compare-fast
      visionReview: qwen-vision-review
  official_api:
    baseUrlEnv: QWEN_API_BASE
    apiKeyEnv: QWEN_API_KEY
    defaultBaseUrl: https://dashscope.aliyuncs.com/compatible-mode/v1
    models:
      review: qwen3.7-max
      default: qwen3.7-plus
      compareFast: qwen3.6-flash
      visionReview: qwen3.7-plus
      coder: qwen3-coder-plus
      embeddingOptional: text-embedding-v4
fallback:
  allowFallbackToServer: false
"""


class FakeServerClient:
    def __init__(self) -> None:
        self.calls = []

    def chat_sync(self, messages, model="default-chat", **kwargs):
        self.calls.append({"messages": messages, "model": model, **kwargs})
        return {"id": "server-chat", "choices": [{"message": {"content": "server ok"}}], "model": model}


def write_config(tmp_path: Path) -> Path:
    path = tmp_path / "qwen_runtime.yaml"
    path.write_text(CONFIG_TEXT, encoding="utf-8")
    return path


def test_qwen_runtime_config_defaults_to_server_and_redacts_key(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("AICHECK_QWEN_CALL_MODE", raising=False)
    monkeypatch.setenv("QWEN_API_KEY", "sk-secret-qwen")
    config = qwen_runtime_config(write_config(tmp_path), env={"QWEN_API_KEY": "sk-secret-qwen"})
    public = qwen_runtime_public_config(env={"QWEN_API_KEY": "sk-secret-qwen"})

    assert config["mode"] == "server"
    assert config["apiKeyConfigured"] is False
    assert public["mode"] == "server"
    assert "sk-secret-qwen" not in json.dumps(public)


def test_repository_runtime_maps_audit_and_vision_to_qwen37_plus() -> None:
    config = qwen_runtime_config(
        CONFIG_PATH,
        env={
            "AICHECK_QWEN_CALL_MODE": "official_api",
            "QWEN_API_BASE": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "QWEN_API_KEY": "sk-test",
        },
    )

    assert config["models"]["review"] == "qwen3.7-plus"
    assert config["models"]["default"] == "qwen3.7-plus"
    assert config["models"]["visionReview"] == "qwen3.7-plus"


def test_qwen_runtime_server_mode_uses_existing_aliases(tmp_path) -> None:
    config = qwen_runtime_config(write_config(tmp_path), env={"AICHECK_QWEN_CALL_MODE": "server"})
    server = FakeServerClient()
    client = QwenRuntimeClient(config=config, server_client=server)

    response = client.chat_sync([{"role": "user", "content": "ping"}], model="review-chat", temperature=0.1)

    assert response["model"] == "review-chat"
    assert server.calls[0]["model"] == "review-chat"
    assert server.calls[0]["temperature"] == 0.1


def test_qwen_runtime_official_mode_calls_openai_compatible_chat_endpoint(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("QWEN_API_KEY", "sk-qwen-test")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["authorization"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.read().decode("utf-8"))
        return httpx.Response(
            200,
            json={"id": "qwen-chat", "choices": [{"message": {"content": "official ok"}}]},
        )

    config = qwen_runtime_config(
        write_config(tmp_path),
        env={"AICHECK_QWEN_CALL_MODE": "official_api", "QWEN_API_BASE": "http://qwen/v1", "QWEN_API_KEY": "sk-qwen-test"},
    )
    client = QwenRuntimeClient(config=config, transport=httpx.MockTransport(handler))

    response = client.chat_sync([{"role": "user", "content": "ping"}], model="review-chat", temperature=0.1)

    assert response["model"] == "qwen3.7-max"
    assert seen["path"] == "/v1/chat/completions"
    assert seen["authorization"] == "Bearer sk-qwen-test"
    assert seen["body"]["model"] == "qwen3.7-max"
    assert seen["body"]["temperature"] == 0.1


def test_qwen_runtime_official_failure_is_fail_closed_by_default(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("QWEN_API_KEY", "sk-qwen-test")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, json={"error": {"code": "UPSTREAM_UNAVAILABLE"}})

    config = qwen_runtime_config(
        write_config(tmp_path),
        env={"AICHECK_QWEN_CALL_MODE": "official_api", "QWEN_API_BASE": "http://qwen/v1", "QWEN_API_KEY": "sk-qwen-test"},
    )
    client = QwenRuntimeClient(config=config, transport=httpx.MockTransport(handler), server_client=FakeServerClient())

    try:
        client.chat_sync([{"role": "user", "content": "ping"}], model="review-chat")
    except RuntimeError as exc:
        assert "Qwen official API" in str(exc)
    else:
        raise AssertionError("official API failures must not fallback by default")


def test_qwen_runtime_explicit_fallback_uses_server_alias(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("QWEN_API_KEY", "sk-qwen-test")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, json={"error": {"code": "UPSTREAM_UNAVAILABLE"}})

    config = qwen_runtime_config(
        write_config(tmp_path),
        env={
            "AICHECK_QWEN_CALL_MODE": "official_api",
            "AICHECK_QWEN_ALLOW_SERVER_FALLBACK": "true",
            "QWEN_API_BASE": "http://qwen/v1",
            "QWEN_API_KEY": "sk-qwen-test",
        },
    )
    server = FakeServerClient()
    client = QwenRuntimeClient(config=config, transport=httpx.MockTransport(handler), server_client=server)

    response = client.chat_sync([{"role": "user", "content": "ping"}], model="review-chat")

    assert response["model"] == "review-chat"
    assert server.calls[0]["model"] == "review-chat"
