from __future__ import annotations

import os
from copy import deepcopy
from pathlib import Path
from typing import Any

import httpx
import yaml

from libs.integrations.errors import IntegrationServiceError, safe_reason
from libs.integrations.litellm_client import LiteLLMClient
from libs.integrations.raw_http_capture import (
    post_json_with_raw_capture,
    stream_chat_completion_with_raw_capture,
)
from libs.raw_vault import RawCapture, RawCaptureContext, raw_capture_from_environment


CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "qwen_runtime.yaml"
SUPPORTED_MODES = {"server", "official_api"}
MODEL_ROLE_ALIASES = {
    "review-chat": "review",
    "default-chat": "default",
    "compare-fast": "compareFast",
    "qwen-vision-review": "visionReview",
}


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def qwen_runtime_config(path: Path | None = None, env: dict[str, str] | None = None) -> dict[str, Any]:
    source = env if env is not None else os.environ
    config = load_qwen_runtime_config(path or CONFIG_PATH)
    mode_env = str(config.get("modeEnv") or "AICHECK_QWEN_CALL_MODE")
    configured_mode = str(source.get(mode_env) or config.get("defaultMode") or "server").strip()
    if configured_mode not in SUPPORTED_MODES:
        raise RuntimeError(f"Unsupported Qwen runtime mode: {configured_mode}")

    providers = config.get("providers") if isinstance(config.get("providers"), dict) else {}
    provider = providers.get(configured_mode) if isinstance(providers.get(configured_mode), dict) else {}
    fallback = config.get("fallback") if isinstance(config.get("fallback"), dict) else {}
    allow_fallback = env_bool_from_mapping(source, "AICHECK_QWEN_ALLOW_SERVER_FALLBACK", bool(fallback.get("allowFallbackToServer")))

    official_provider = providers.get("official_api") if isinstance(providers.get("official_api"), dict) else {}
    server_provider = providers.get("server") if isinstance(providers.get("server"), dict) else {}
    base_url_env = str(provider.get("baseUrlEnv") or "")
    api_key_env = str(provider.get("apiKeyEnv") or "")
    default_base_url = str(provider.get("defaultBaseUrl") or "")
    base_url = str(source.get(base_url_env) or default_base_url or "").rstrip("/")
    api_key = str(source.get(api_key_env) or "")
    aliases = deepcopy(server_provider.get("aliases") or {})
    models = deepcopy(official_provider.get("models") or {})
    return {
        "schemaVersion": str(config.get("schemaVersion") or "aicheck-qwen-runtime@1"),
        "mode": configured_mode,
        "modeEnv": mode_env,
        "provider": "Model Studio / DashScope" if configured_mode == "official_api" else "server",
        "baseUrl": base_url,
        "baseUrlRedacted": redact_url(base_url),
        "baseUrlEnv": base_url_env,
        "apiKeyEnv": api_key_env,
        "apiKeyConfigured": bool(api_key),
        "aliases": aliases,
        "models": models,
        "allowFallbackToServer": allow_fallback,
        "embeddingOptional": models.get("embeddingOptional"),
        "embeddingSwitchDefault": False,
        "officialProvider": {
            "baseUrlEnv": str(official_provider.get("baseUrlEnv") or "QWEN_API_BASE"),
            "apiKeyEnv": str(official_provider.get("apiKeyEnv") or "QWEN_API_KEY"),
            "defaultBaseUrl": str(official_provider.get("defaultBaseUrl") or ""),
            "models": models,
        },
        "serverProvider": {
            "baseUrlEnv": str(server_provider.get("baseUrlEnv") or "AICHECK_QWEN_SERVER_BASE_URL"),
            "apiKeyEnv": str(server_provider.get("apiKeyEnv") or "AICHECK_QWEN_SERVER_API_KEY"),
            "aliases": aliases,
        },
    }


def server_mode_base_url(config: dict[str, Any] | None = None) -> str:
    """server 模式实际生效的模型地址。

    2026-08-14 发现的坑：qwen_runtime.yaml 把 server 模式的地址写成
    `baseUrlEnv: AICHECK_QWEN_SERVER_BASE_URL`，但没有任何代码路径读它——
    server 模式一律 `LiteLLMClient()` 空参构造，取的是 LITELLM_BASE_URL，
    缺省值 `http://litellm-service:4000` 只在 compose 网络里能解析。

    结果是：运维照配置文件把地址设到 AICHECK_QWEN_SERVER_BASE_URL，设了等于没设，
    调用仍打向一个解析不了的主机名，报 IntegrationServiceError。

    这里让文档里的那个变量真正生效，同时保留 LITELLM_BASE_URL 作为回退，
    使既有部署行为不变。
    """
    resolved = config if config is not None else qwen_runtime_config()
    if str(resolved.get("mode") or "") != "server":
        return ""
    return str(resolved.get("baseUrl") or os.getenv("LITELLM_BASE_URL") or "").rstrip("/")


def build_qwen_runtime_client(client_cls: Any, config: dict[str, Any] | None = None) -> QwenRuntimeClient:
    """按当前配置装配 QwenRuntimeClient。

    execution.py 与 worker/tasks.py 原本各有一份逐字相同的实现；合并到这里，
    省得下次改 server 模式的地址解析要记得改两处（这次差点就漏了一处）。

    `client_cls` 由调用方传入而不是在这里 import，是为了让测试仍能
    monkeypatch 各自模块里的 LiteLLMClient。
    """
    resolved = config if config is not None else qwen_runtime_config()
    if not (resolved["mode"] == "server" or resolved.get("allowFallbackToServer")):
        return QwenRuntimeClient(config=resolved, server_client=None)
    # 只有显式配置过地址时才覆盖；没配就交给 LiteLLMClient 自己的解析顺序，
    # 保持既有部署行为不变。
    base_url = server_mode_base_url(resolved)
    server_client = client_cls(**({"base_url": base_url} if base_url else {}))
    return QwenRuntimeClient(config=resolved, server_client=server_client)


def load_qwen_runtime_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle) or {}
    if not isinstance(loaded, dict):
        raise RuntimeError("Qwen runtime config must be a mapping")
    return loaded


def env_bool_from_mapping(source: dict[str, str], name: str, default: bool) -> bool:
    value = source.get(name)
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def redact_url(value: str) -> str:
    if not value:
        return ""
    return value.split("?", 1)[0]


def qwen_runtime_public_config(env: dict[str, str] | None = None) -> dict[str, Any]:
    runtime = qwen_runtime_config(env=env)
    active_models = runtime["models"] if runtime["mode"] == "official_api" else runtime["aliases"]
    return {
        "schemaVersion": runtime["schemaVersion"],
        "mode": runtime["mode"],
        "modeEnv": runtime["modeEnv"],
        "provider": runtime["provider"],
        "baseUrl": runtime["baseUrlRedacted"],
        "baseUrlEnv": runtime["baseUrlEnv"],
        "apiKeyEnv": runtime["apiKeyEnv"],
        "apiKeyConfigured": runtime["apiKeyConfigured"],
        "activeModels": active_models,
        "allowFallbackToServer": runtime["allowFallbackToServer"],
        "embeddingOptional": runtime["embeddingOptional"],
        "embeddingSwitchDefault": runtime["embeddingSwitchDefault"],
    }


class QwenRuntimeClient:
    def __init__(
        self,
        *,
        config: dict[str, Any] | None = None,
        transport: Any | None = None,
        server_client: LiteLLMClient | None = None,
        raw_capture: RawCapture | None = None,
    ) -> None:
        self.config = config or qwen_runtime_config()
        self.transport = transport
        self.server_client = server_client
        self.raw_capture = raw_capture if raw_capture is not None else raw_capture_from_environment()

    def chat_sync(self, messages: list[dict[str, Any]], model: str = "default-chat", **kwargs: Any) -> dict[str, Any]:
        if self.config["mode"] == "server":
            return self._server_chat_sync(messages, model=model, **kwargs)
        if self.config["mode"] == "official_api":
            try:
                return self._official_chat_sync(messages, role_or_model=model, **kwargs)
            except Exception:
                if not self.config.get("allowFallbackToServer"):
                    raise
                return self._server_chat_sync(messages, model=model, **kwargs)
        raise RuntimeError(f"Unsupported Qwen runtime mode: {self.config['mode']}")

    @staticmethod
    def first_message_text(response: dict[str, Any]) -> str:
        return LiteLLMClient.first_message_text(response)

    def _server_chat_sync(self, messages: list[dict[str, Any]], model: str, **kwargs: Any) -> dict[str, Any]:
        base_url = server_mode_base_url(self.config)
        client = self.server_client or LiteLLMClient(
            **({"base_url": base_url} if base_url else {}),
            raw_capture=self.raw_capture,
        )
        return client.chat_sync(messages, model=model, **kwargs)

    def _official_chat_sync(self, messages: list[dict[str, Any]], role_or_model: str, **kwargs: Any) -> dict[str, Any]:
        raw_context: RawCaptureContext | None = kwargs.pop("_raw_capture_context", None)
        stream_handler = kwargs.pop("stream_handler", None)
        base_url = str(self.config.get("baseUrl") or "").rstrip("/")
        api_key_env = str(self.config.get("apiKeyEnv") or "QWEN_API_KEY")
        api_key = os.getenv(api_key_env)
        if not base_url:
            raise RuntimeError("Qwen official API base URL is not configured")
        if not api_key:
            raise RuntimeError(f"{api_key_env} is required for Qwen official API mode")
        model = self._official_model_for(role_or_model)
        client_kwargs: dict[str, Any] = {"timeout": float(kwargs.pop("timeout", 60))}
        if self.transport is not None:
            client_kwargs["transport"] = self.transport
        if stream_handler is not None:
            # SSE 串流模式：与 LiteLLM 分支同构，组装结果保持非串流响应结构。
            stream_payload: dict[str, Any] = {"model": model, "messages": messages, "stream": True, **kwargs}
            if os.getenv("AICHECK_LLM_STREAM_INCLUDE_USAGE", "true").strip().lower() != "false":
                stream_payload.setdefault("stream_options", {"include_usage": True})
            try:
                with httpx.Client(**client_kwargs) as client:
                    payload = stream_chat_completion_with_raw_capture(
                        client,
                        f"{base_url}/chat/completions",
                        headers={"Authorization": f"Bearer {api_key}"},
                        payload=stream_payload,
                        capture=self.raw_capture,
                        context=raw_context,
                        provider="Qwen official API",
                        operation="chat.completions",
                        on_delta=stream_handler,
                    )
            except httpx.HTTPStatusError as exc:
                raise IntegrationServiceError(
                    "Qwen official API",
                    "chat.completions",
                    status_code=exc.response.status_code,
                ) from exc
            except httpx.HTTPError as exc:
                raise IntegrationServiceError(
                    "Qwen official API",
                    "chat.completions",
                    reason=exc.__class__.__name__.upper(),
                ) from exc
            payload.setdefault("model", model)
            payload.setdefault("provider", self.config.get("provider"))
            return payload
        try:
            with httpx.Client(**client_kwargs) as client:
                response = post_json_with_raw_capture(
                    client,
                    f"{base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    payload={"model": model, "messages": messages, **kwargs},
                    capture=self.raw_capture,
                    context=raw_context,
                    provider="Qwen official API",
                    operation="chat.completions",
                )
        except httpx.HTTPError as exc:
            raise IntegrationServiceError(
                "Qwen official API",
                "chat.completions",
                reason=exc.__class__.__name__.upper(),
            ) from exc
        if response.status_code >= 400:
            reason = None
            try:
                payload = response.json()
                error = payload.get("error") if isinstance(payload, dict) else None
                reason = (error or {}).get("code") if isinstance(error, dict) else None
            except ValueError:
                reason = None
            raise IntegrationServiceError(
                "Qwen official API",
                "chat.completions",
                status_code=response.status_code,
                reason=safe_reason(reason),
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise IntegrationServiceError("Qwen official API", "chat.completions", reason="INVALID_JSON") from exc
        if not isinstance(payload, dict):
            raise IntegrationServiceError("Qwen official API", "chat.completions", reason="INVALID_RESPONSE")
        payload.setdefault("model", model)
        payload.setdefault("provider", self.config.get("provider"))
        return payload

    def _official_model_for(self, role_or_model: str) -> str:
        role = MODEL_ROLE_ALIASES.get(role_or_model, role_or_model)
        models = self.config.get("models") if isinstance(self.config.get("models"), dict) else {}
        resolved = models.get(role) or models.get(role_or_model) or role_or_model
        if not resolved:
            raise RuntimeError(f"Qwen official API model is not configured for {role_or_model}")
        return str(resolved)
