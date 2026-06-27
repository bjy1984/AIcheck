from __future__ import annotations

import os
from typing import Any

import httpx


class LiteLLMClient:
    def __init__(self, base_url: str | None = None, api_key: str | None = None) -> None:
        self.base_url = (base_url or os.getenv("LITELLM_BASE_URL") or "http://litellm-service:4000").rstrip("/")
        self.api_key = api_key or os.getenv("LITELLM_API_KEY") or "sk-aicheck-dev"

    async def chat(self, messages: list[dict[str, str]], model: str = "default-chat", **kwargs: Any) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{self.base_url}/v1/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": model, "messages": messages, **kwargs},
            )
            response.raise_for_status()
            return response.json()

    async def embed(self, inputs: list[str], model: str = "embedding-default") -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{self.base_url}/v1/embeddings",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": model, "input": inputs},
            )
            response.raise_for_status()
            return response.json()

    def chat_sync(self, messages: list[dict[str, str]], model: str = "default-chat", **kwargs: Any) -> dict[str, Any]:
        with httpx.Client(timeout=60) as client:
            response = client.post(
                f"{self.base_url}/v1/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": model, "messages": messages, **kwargs},
            )
            response.raise_for_status()
            return response.json()

    def embed_sync(self, inputs: list[str], model: str = "embedding-default") -> dict[str, Any]:
        with httpx.Client(timeout=60) as client:
            response = client.post(
                f"{self.base_url}/v1/embeddings",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": model, "input": inputs},
            )
            response.raise_for_status()
            return response.json()

    @staticmethod
    def first_message_text(response: dict[str, Any]) -> str:
        try:
            return str(response["choices"][0]["message"]["content"])
        except Exception:
            return ""
