from __future__ import annotations

import os
from typing import Any

import httpx

from libs.embedding_models import (
    EMBEDDING_DEFAULT_ALIAS,
    EMBEDDING_DEFAULT_MODEL_ID,
    embedding_model_spec,
)
from libs.integrations.errors import IntegrationServiceError, safe_reason


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def resolve_embedding_base_url(base_url: str | None = None) -> str:
    provider = str(os.getenv("AICHECK_EMBEDDING_PROVIDER") or "local").strip().lower()
    official = provider in {"official", "official_api", "qwen_official", "dashscope"}
    configured = str(
        base_url
        or os.getenv("AICHECK_EMBEDDING_API_BASE")
        or os.getenv("AICHECK_EMBEDDING_BASE_URL")
        or (os.getenv("QWEN_API_BASE") if official else "")
        or ""
    ).strip()
    return configured.rstrip("/")


class EmbeddingClient:
    def __init__(self, base_url: str | None = None, transport: Any | None = None) -> None:
        self.provider = str(os.getenv("AICHECK_EMBEDDING_PROVIDER") or "local").strip().lower()
        self.official = self.provider in {"official", "official_api", "qwen_official", "dashscope"}
        self.base_url = resolve_embedding_base_url(base_url)
        self.transport = transport
        self.served_model_name = str(os.getenv("AICHECK_EMBEDDING_SERVED_MODEL_NAME") or EMBEDDING_DEFAULT_ALIAS)
        self.model_id = str(os.getenv("AICHECK_EMBEDDING_MODEL_ID") or EMBEDDING_DEFAULT_MODEL_ID)
        self.api_key = str(
            os.getenv("AICHECK_EMBEDDING_API_KEY")
            or (os.getenv("QWEN_API_KEY") if self.official else "")
            or os.getenv("INFINITY_API_KEY")
            or ""
        )
        default_batch_size = 10 if self.official else 32
        self.batch_size = max(1, int(os.getenv("AICHECK_EMBEDDING_BATCH_SIZE") or default_batch_size))

    @property
    def enabled(self) -> bool:
        return bool(self.base_url)

    @property
    def index_version(self) -> str:
        return str(embedding_model_spec(self.model_id).get("indexVersion") or "")

    @property
    def dimensions(self) -> int:
        return int(embedding_model_spec(self.model_id).get("dimensions") or 0)

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            return {}
        return {"Authorization": f"Bearer {self.api_key}"}

    def _resource_url(self, resource: str) -> str:
        suffix = resource.lstrip("/")
        if not self.official:
            return f"{self.base_url}/{suffix}"
        if self.base_url.endswith("/v1"):
            return f"{self.base_url}/{suffix}"
        return f"{self.base_url}/v1/{suffix}"

    def health(self) -> dict[str, Any]:
        if not self.enabled:
            raise RuntimeError("AICHECK_EMBEDDING_API_BASE is not configured")
        client_kwargs: dict[str, Any] = {"timeout": 10}
        if self.transport is not None:
            client_kwargs["transport"] = self.transport
        try:
            with httpx.Client(**client_kwargs) as client:
                resource = "models" if self.official else "health"
                response = client.get(self._resource_url(resource), headers=self._headers())
        except httpx.HTTPError as exc:
            raise IntegrationServiceError("Embedding service", "health", reason=exc.__class__.__name__) from exc
        if response.status_code >= 400:
            raise IntegrationServiceError("Embedding service", "health", status_code=response.status_code)
        try:
            payload = response.json()
        except ValueError as exc:
            raise IntegrationServiceError("Embedding service", "health", reason="INVALID_JSON") from exc
        return payload if isinstance(payload, dict) else {}

    def embed_sync(self, texts: list[str], *, timeout: float = 120) -> list[dict[str, Any]]:
        if not self.enabled:
            raise RuntimeError("AICHECK_EMBEDDING_API_BASE is not configured")
        inputs = [str(item or "") for item in texts]
        if not inputs:
            return []
        client_kwargs: dict[str, Any] = {"timeout": timeout}
        if self.transport is not None:
            client_kwargs["transport"] = self.transport
        vectors: list[dict[str, Any]] = []
        try:
            with httpx.Client(**client_kwargs) as client:
                for offset in range(0, len(inputs), self.batch_size):
                    payload: dict[str, Any] = {
                        "model": self.served_model_name,
                        "input": inputs[offset : offset + self.batch_size],
                    }
                    if self.official:
                        payload["dimensions"] = self.dimensions
                    response = client.post(
                        self._resource_url("embeddings"),
                        headers=self._headers(),
                        json=payload,
                    )
                    if response.status_code >= 400:
                        reason = None
                        try:
                            error_payload = response.json()
                            error = error_payload.get("error") if isinstance(error_payload, dict) else None
                            reason = (
                                error.get("code")
                                if isinstance(error, dict)
                                else error_payload.get("detail") if isinstance(error_payload, dict) else None
                            )
                        except ValueError:
                            reason = None
                        raise IntegrationServiceError(
                            "Embedding service",
                            "embeddings",
                            status_code=response.status_code,
                            reason=safe_reason(reason),
                        )
                    try:
                        response_payload = response.json()
                    except ValueError as exc:
                        raise IntegrationServiceError("Embedding service", "embeddings", reason="INVALID_JSON") from exc
                    data = response_payload.get("data") if isinstance(response_payload, dict) else None
                    if not isinstance(data, list):
                        raise IntegrationServiceError("Embedding service", "embeddings", reason="INVALID_RESPONSE")
                    for item in data:
                        if not isinstance(item, dict):
                            continue
                        embedding = item.get("embedding")
                        if not isinstance(embedding, list) or len(embedding) != self.dimensions:
                            raise IntegrationServiceError(
                                "Embedding service",
                                "embeddings",
                                reason="VECTOR_DIMENSION_MISMATCH",
                            )
                        vectors.append(
                            {
                                "index": offset + int(item.get("index") or 0),
                                "embedding": [float(value) for value in embedding],
                            }
                        )
        except httpx.HTTPError as exc:
            raise IntegrationServiceError("Embedding service", "embeddings", reason=exc.__class__.__name__) from exc
        return vectors
