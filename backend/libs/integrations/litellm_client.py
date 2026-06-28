from __future__ import annotations

import os
from typing import Any

import httpx

from libs.integrations.errors import IntegrationServiceError


class LiteLLMClient:
    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        transport: Any | None = None,
    ) -> None:
        self.base_url = (base_url or os.getenv("LITELLM_BASE_URL") or "http://litellm-service:4000").rstrip("/")
        configured_key = api_key or os.getenv("LITELLM_API_KEY")
        if not configured_key and production_mode_enabled():
            raise RuntimeError("LITELLM_API_KEY is required when production flags are enabled")
        self.api_key = configured_key or "sk-aicheck-dev"
        if self.api_key == "sk-aicheck-dev" and production_mode_enabled():
            raise RuntimeError("Default development LiteLLM key is not allowed in production mode")
        self.transport = transport

    async def chat(self, messages: list[dict[str, str]], model: str = "default-chat", **kwargs: Any) -> dict[str, Any]:
        client_kwargs = self._client_kwargs(timeout=60)
        try:
            async with httpx.AsyncClient(**client_kwargs) as client:
                response = await client.post(
                    f"{self.base_url}/v1/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={"model": model, "messages": messages, **kwargs},
                )
        except httpx.HTTPError as exc:
            raise IntegrationServiceError("LiteLLM", "chat.completions", reason=exc.__class__.__name__) from exc
        return self._response_json(response, "chat.completions")

    async def embed(self, inputs: list[str], model: str = "embedding-default") -> dict[str, Any]:
        client_kwargs = self._client_kwargs(timeout=60)
        try:
            async with httpx.AsyncClient(**client_kwargs) as client:
                response = await client.post(
                    f"{self.base_url}/v1/embeddings",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={"model": model, "input": inputs},
                )
        except httpx.HTTPError as exc:
            raise IntegrationServiceError("LiteLLM", "embeddings", reason=exc.__class__.__name__) from exc
        return self._response_json(response, "embeddings")

    def chat_sync(self, messages: list[dict[str, str]], model: str = "default-chat", **kwargs: Any) -> dict[str, Any]:
        client_kwargs = self._client_kwargs(timeout=60)
        try:
            with httpx.Client(**client_kwargs) as client:
                response = client.post(
                    f"{self.base_url}/v1/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={"model": model, "messages": messages, **kwargs},
                )
        except httpx.HTTPError as exc:
            raise IntegrationServiceError("LiteLLM", "chat.completions", reason=exc.__class__.__name__) from exc
        return self._response_json(response, "chat.completions")

    def embed_sync(self, inputs: list[str], model: str = "embedding-default") -> dict[str, Any]:
        client_kwargs = self._client_kwargs(timeout=60)
        try:
            with httpx.Client(**client_kwargs) as client:
                response = client.post(
                    f"{self.base_url}/v1/embeddings",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={"model": model, "input": inputs},
                )
        except httpx.HTTPError as exc:
            raise IntegrationServiceError("LiteLLM", "embeddings", reason=exc.__class__.__name__) from exc
        return self._response_json(response, "embeddings")

    def _client_kwargs(self, *, timeout: int) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"timeout": timeout}
        if self.transport is not None:
            kwargs["transport"] = self.transport
        return kwargs

    def _response_json(self, response: httpx.Response, operation: str) -> dict[str, Any]:
        if response.status_code >= 400:
            raise IntegrationServiceError("LiteLLM", operation, status_code=response.status_code)
        try:
            payload = response.json()
        except ValueError as exc:
            raise IntegrationServiceError("LiteLLM", operation, reason="INVALID_JSON") from exc
        if not isinstance(payload, dict):
            raise IntegrationServiceError("LiteLLM", operation, reason="INVALID_RESPONSE")
        return payload

    @staticmethod
    def first_message_text(response: dict[str, Any]) -> str:
        try:
            return str(response["choices"][0]["message"]["content"])
        except Exception:
            return ""


def production_mode_enabled() -> bool:
    return any(
        os.getenv(name, "").strip().lower() == "true"
        for name in ["AICHECK_REQUIRE_AUTH", "AICHECK_MONGO_TRANSACTIONS", "AICHECK_STRICT_PRODUCTION"]
    )
