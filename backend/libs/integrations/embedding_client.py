from __future__ import annotations

import os
from typing import Any

import httpx

from libs.embedding_models import EMBEDDING_DEFAULT_ALIAS, EMBEDDING_DEFAULT_MODEL_ID, embedding_model_spec
from libs.integrations.errors import IntegrationServiceError, safe_reason


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def resolve_embedding_base_url(base_url: str | None = None) -> str:
    configured = str(
        base_url
        or os.getenv("AICHECK_EMBEDDING_API_BASE")
        or os.getenv("AICHECK_EMBEDDING_BASE_URL")
        or ""
    ).strip()
    return configured.rstrip("/")


class EmbeddingClient:
    def __init__(self, base_url: str | None = None, transport: Any | None = None) -> None:
        self.base_url = resolve_embedding_base_url(base_url)
        self.transport = transport
        self.served_model_name = str(os.getenv("AICHECK_EMBEDDING_SERVED_MODEL_NAME") or EMBEDDING_DEFAULT_ALIAS)
        self.model_id = str(os.getenv("AICHECK_EMBEDDING_MODEL_ID") or EMBEDDING_DEFAULT_MODEL_ID)
        self.api_key = str(os.getenv("AICHECK_EMBEDDING_API_KEY") or os.getenv("INFINITY_API_KEY") or "")

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

    def health(self) -> dict[str, Any]:
        if not self.enabled:
            raise RuntimeError("AICHECK_EMBEDDING_API_BASE is not configured")
        client_kwargs: dict[str, Any] = {"timeout": 10}
        if self.transport is not None:
            client_kwargs["transport"] = self.transport
        try:
            with httpx.Client(**client_kwargs) as client:
                response = client.get(f"{self.base_url}/health", headers=self._headers())
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
        try:
            with httpx.Client(**client_kwargs) as client:
                response = client.post(
                    f"{self.base_url}/v1/embeddings",
                    headers=self._headers(),
                    json={"model": self.served_model_name, "input": inputs},
                )
        except httpx.HTTPError as exc:
            raise IntegrationServiceError("Embedding service", "v1/embeddings", reason=exc.__class__.__name__) from exc
        if response.status_code >= 400:
            reason = None
            try:
                payload = response.json()
                reason = payload.get("detail") if isinstance(payload, dict) else None
            except ValueError:
                reason = None
            raise IntegrationServiceError(
                "Embedding service",
                "v1/embeddings",
                status_code=response.status_code,
                reason=safe_reason(reason),
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise IntegrationServiceError("Embedding service", "v1/embeddings", reason="INVALID_JSON") from exc
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list):
            raise IntegrationServiceError("Embedding service", "v1/embeddings", reason="INVALID_RESPONSE")
        vectors: list[dict[str, Any]] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            embedding = item.get("embedding")
            if not isinstance(embedding, list) or not embedding:
                continue
            vectors.append({"index": int(item.get("index") or 0), "embedding": [float(value) for value in embedding]})
        return vectors
