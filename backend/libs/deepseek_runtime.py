from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx
import yaml

from libs.integrations.errors import IntegrationServiceError, safe_reason
from libs.integrations.litellm_client import LiteLLMClient

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "audit_model_comparison.yaml"
SUPPORTED_MODES = {"off", "shadow"}


def load_comparison_config(path: Path | None = None) -> dict[str, Any]:
    with (path or CONFIG_PATH).open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    if not isinstance(payload, dict):
        raise RuntimeError("Audit model comparison config must be a mapping")
    return payload


def _bounded_float(value: Any, default: float, minimum: float, maximum: float) -> float:
    try:
        return max(minimum, min(maximum, float(value)))
    except (TypeError, ValueError):
        return default


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        return max(minimum, min(maximum, int(value)))
    except (TypeError, ValueError):
        return default


def deepseek_runtime_config(
    path: Path | None = None,
    *,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    source = env if env is not None else os.environ
    config = load_comparison_config(path)
    mode_env = str(config.get("modeEnv") or "AICHECK_AUDIT_MODEL_COMPARISON_MODE")
    mode = str(source.get(mode_env) or config.get("defaultMode") or "off").strip().lower()
    if mode not in SUPPORTED_MODES:
        raise RuntimeError(f"Unsupported audit model comparison mode: {mode}")
    primary = config.get("primary") if isinstance(config.get("primary"), dict) else {}
    challenger = config.get("challenger") if isinstance(config.get("challenger"), dict) else {}
    sampling = config.get("sampling") if isinstance(config.get("sampling"), dict) else {}
    fallback = config.get("fallback") if isinstance(config.get("fallback"), dict) else {}
    base_url_env = str(challenger.get("baseUrlEnv") or "DEEPSEEK_API_BASE")
    api_key_env = str(challenger.get("apiKeyEnv") or "DEEPSEEK_API_KEY")
    model_env = str(challenger.get("modelEnv") or "AICHECK_DEEPSEEK_AUDIT_MODEL")
    rate_env = str(sampling.get("rateEnv") or "AICHECK_AUDIT_MODEL_COMPARISON_SAMPLE_RATE")
    thinking = challenger.get("thinking") if isinstance(challenger.get("thinking"), dict) else {}
    primary_base_url_env = str(primary.get("baseUrlEnv") or "QWEN_API_BASE")
    primary_api_key_env = str(primary.get("apiKeyEnv") or "QWEN_API_KEY")
    primary_model_env = str(primary.get("modelEnv") or "AICHECK_QWEN_VL_AUDIT_MODEL")
    primary_base_url = str(source.get(primary_base_url_env) or primary.get("defaultBaseUrl") or "").rstrip("/")
    primary_api_key = str(source.get(primary_api_key_env) or "").strip()
    primary_model = str(source.get(primary_model_env) or primary.get("defaultModel") or "qwen3.7-plus").strip()
    base_url = str(source.get(base_url_env) or challenger.get("defaultBaseUrl") or "").rstrip("/")
    api_key = str(source.get(api_key_env) or "").strip()
    model = str(source.get(model_env) or challenger.get("defaultModel") or "deepseek-v4-pro").strip()
    return {
        "schemaVersion": str(config.get("schemaVersion") or "aicheck-audit-model-comparison@1"),
        "mode": mode,
        "modeEnv": mode_env,
        "enabled": mode == "shadow",
        "primaryPipelineId": str(primary.get("pipelineId") or "qwen_vl_audit_v1"),
        "primaryProvider": str(primary.get("provider") or "qwen_official"),
        "primaryBaseUrl": primary_base_url,
        "primaryBaseUrlRedacted": primary_base_url.split("?", 1)[0],
        "primaryBaseUrlEnv": primary_base_url_env,
        "primaryApiKey": primary_api_key,
        "primaryApiKeyEnv": primary_api_key_env,
        "primaryApiKeyConfigured": bool(primary_api_key),
        "primaryModel": primary_model,
        "primaryModelEnv": primary_model_env,
        "primaryMaxTokens": _bounded_int(primary.get("maxTokens"), 2400, 256, 8192),
        "primaryTimeoutSeconds": _bounded_float(primary.get("timeoutSeconds"), 180.0, 30.0, 300.0),
        "challengerPipelineId": str(challenger.get("pipelineId") or "paddle_nuextract_deepseek_v1"),
        "challengerProvider": str(challenger.get("provider") or "deepseek_official"),
        "baseUrl": base_url,
        "baseUrlRedacted": base_url.split("?", 1)[0],
        "baseUrlEnv": base_url_env,
        "apiKey": api_key,
        "apiKeyEnv": api_key_env,
        "apiKeyConfigured": bool(api_key),
        "model": model,
        "modelEnv": model_env,
        "thinkingType": str(thinking.get("type") or "enabled"),
        "reasoningEffort": str(thinking.get("reasoningEffort") or "high"),
        "maxTokens": _bounded_int(
            source.get("AICHECK_DEEPSEEK_AUDIT_MAX_TOKENS") or challenger.get("maxTokens"),
            2400,
            256,
            8192,
        ),
        "timeoutSeconds": _bounded_float(
            source.get("AICHECK_DEEPSEEK_AUDIT_TIMEOUT_SECONDS") or challenger.get("timeoutSeconds"),
            180.0,
            30.0,
            300.0,
        ),
        "sampleRate": _bounded_float(
            source.get(rate_env) or sampling.get("defaultRate"),
            1.0,
            0.0,
            1.0,
        ),
        "sampleRateEnv": rate_env,
        "allowChallengerToReplacePrimary": bool(fallback.get("allowChallengerToReplacePrimary", False)),
        "allowProviderFallback": bool(fallback.get("allowProviderFallback", False)),
    }


def deepseek_runtime_public_config(env: dict[str, str] | None = None) -> dict[str, Any]:
    config = deepseek_runtime_config(env=env)
    return {
        key: config[key]
        for key in [
            "schemaVersion",
            "mode",
            "modeEnv",
            "enabled",
            "primaryPipelineId",
            "primaryProvider",
            "primaryBaseUrlRedacted",
            "primaryBaseUrlEnv",
            "primaryApiKeyEnv",
            "primaryApiKeyConfigured",
            "primaryModel",
            "primaryModelEnv",
            "primaryMaxTokens",
            "primaryTimeoutSeconds",
            "challengerPipelineId",
            "challengerProvider",
            "baseUrlRedacted",
            "baseUrlEnv",
            "apiKeyEnv",
            "apiKeyConfigured",
            "model",
            "modelEnv",
            "thinkingType",
            "reasoningEffort",
            "maxTokens",
            "timeoutSeconds",
            "sampleRate",
            "sampleRateEnv",
            "allowChallengerToReplacePrimary",
            "allowProviderFallback",
        ]
    }


class DeepSeekAuditClient:
    def __init__(
        self,
        *,
        config: dict[str, Any] | None = None,
        transport: Any | None = None,
    ) -> None:
        self.config = config or deepseek_runtime_config()
        self.transport = transport

    @property
    def enabled(self) -> bool:
        return bool(self.config.get("enabled") and self.config.get("baseUrl") and self.config.get("apiKey"))

    def chat_sync(
        self,
        messages: list[dict[str, str]],
        *,
        thinking_type: str | None = None,
    ) -> dict[str, Any]:
        if not self.enabled:
            raise RuntimeError("DeepSeek audit comparison is not configured")
        effective_thinking = thinking_type or self.config["thinkingType"]
        if effective_thinking not in {"enabled", "disabled"}:
            raise RuntimeError(f"Unsupported DeepSeek thinking type: {effective_thinking}")
        request_body = {
            "model": self.config["model"],
            "messages": messages,
            "stream": False,
            "response_format": {"type": "json_object"},
            "thinking": {"type": effective_thinking},
            "max_tokens": self.config["maxTokens"],
        }
        if effective_thinking == "enabled":
            request_body["reasoning_effort"] = self.config["reasoningEffort"]
        client_kwargs: dict[str, Any] = {"timeout": self.config["timeoutSeconds"]}
        if self.transport is not None:
            client_kwargs["transport"] = self.transport
        try:
            with httpx.Client(**client_kwargs) as client:
                response = client.post(
                    f"{self.config['baseUrl']}/chat/completions",
                    headers={"Authorization": f"Bearer {self.config['apiKey']}"},
                    json=request_body,
                )
        except httpx.HTTPError as exc:
            raise IntegrationServiceError(
                "DeepSeek official API",
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
                "DeepSeek official API",
                "chat.completions",
                status_code=response.status_code,
                reason=safe_reason(reason),
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise IntegrationServiceError("DeepSeek official API", "chat.completions", reason="INVALID_JSON") from exc
        if not isinstance(payload, dict):
            raise IntegrationServiceError("DeepSeek official API", "chat.completions", reason="INVALID_RESPONSE")
        payload.setdefault("model", self.config["model"])
        payload.setdefault("provider", self.config["challengerProvider"])
        return payload

    @staticmethod
    def first_message_text(response: dict[str, Any]) -> str:
        return LiteLLMClient.first_message_text(response)
