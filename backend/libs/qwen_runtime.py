from __future__ import annotations

import os
from copy import deepcopy
from pathlib import Path
from typing import Any

import httpx
import yaml

from libs.integrations.errors import IntegrationServiceError, safe_reason
from libs.integrations.litellm_client import LiteLLMClient


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
    ) -> None:
        self.config = config or qwen_runtime_config()
        self.transport = transport
        self.server_client = server_client

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
        client = self.server_client or LiteLLMClient()
        return client.chat_sync(messages, model=model, **kwargs)

    def _official_chat_sync(self, messages: list[dict[str, Any]], role_or_model: str, **kwargs: Any) -> dict[str, Any]:
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
        try:
            with httpx.Client(**client_kwargs) as client:
                response = client.post(
                    f"{base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={"model": model, "messages": messages, **kwargs},
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
