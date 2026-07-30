from __future__ import annotations

import os
from typing import Any

import httpx

from libs.integrations.errors import IntegrationServiceError, safe_reason

RERANK_DEFAULT_MODEL_ID = "BAAI/bge-reranker-v2-m3"


class RerankerClient:
    """Cross-encoder reranker over an Infinity-compatible /rerank endpoint.

    Configure with:
      AICHECK_RERANK_API_BASE          e.g. http://embedding-service:7997 (can be the
                                       same Infinity deployment that serves embeddings)
      AICHECK_RERANK_MODEL_ID          default BAAI/bge-reranker-v2-m3
      AICHECK_RERANK_SERVED_MODEL_NAME served model name if aliased
      AICHECK_RERANK_API_KEY           optional bearer token (falls back to INFINITY_API_KEY)
    """

    def __init__(self, base_url: str | None = None, transport: Any | None = None) -> None:
        self.base_url = str(
            base_url
            or os.getenv("AICHECK_RERANK_API_BASE")
            or os.getenv("AICHECK_RERANK_BASE_URL")
            or ""
        ).strip().rstrip("/")
        self.model_id = str(os.getenv("AICHECK_RERANK_MODEL_ID") or RERANK_DEFAULT_MODEL_ID)
        self.served_model_name = str(os.getenv("AICHECK_RERANK_SERVED_MODEL_NAME") or self.model_id)
        self.api_key = str(os.getenv("AICHECK_RERANK_API_KEY") or os.getenv("INFINITY_API_KEY") or "")
        self.transport = transport

    @property
    def enabled(self) -> bool:
        return bool(self.base_url)

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            return {}
        return {"Authorization": f"Bearer {self.api_key}"}

    def rerank(
        self,
        query: str,
        documents: list[str],
        *,
        timeout: float = 20,
    ) -> list[dict[str, Any]]:
        """Return [{"index": i, "relevanceScore": s}] sorted by score descending."""
        if not self.enabled:
            raise RuntimeError("AICHECK_RERANK_API_BASE is not configured")
        if not documents:
            return []
        client_kwargs: dict[str, Any] = {"timeout": timeout}
        if self.transport is not None:
            client_kwargs["transport"] = self.transport
        try:
            with httpx.Client(**client_kwargs) as client:
                response = client.post(
                    f"{self.base_url}/rerank",
                    headers=self._headers(),
                    json={
                        "model": self.served_model_name,
                        "query": str(query or ""),
                        "documents": [str(item or "") for item in documents],
                        "return_documents": False,
                    },
                )
        except httpx.HTTPError as exc:
            raise IntegrationServiceError("Reranker service", "rerank", reason=exc.__class__.__name__) from exc
        if response.status_code >= 400:
            reason = None
            try:
                payload = response.json()
                if isinstance(payload, dict):
                    error = payload.get("error")
                    reason = error.get("code") if isinstance(error, dict) else payload.get("detail")
            except ValueError:
                reason = None
            raise IntegrationServiceError(
                "Reranker service",
                "rerank",
                status_code=response.status_code,
                reason=safe_reason(reason),
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise IntegrationServiceError("Reranker service", "rerank", reason="INVALID_JSON") from exc
        results = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(results, list):
            raise IntegrationServiceError("Reranker service", "rerank", reason="INVALID_RESPONSE")
        parsed: list[dict[str, Any]] = []
        for item in results:
            if not isinstance(item, dict):
                continue
            index = item.get("index")
            score = item.get("relevance_score", item.get("relevanceScore", item.get("score")))
            try:
                parsed.append({"index": int(index), "relevanceScore": float(score)})
            except (TypeError, ValueError):
                continue
        parsed.sort(key=lambda item: item["relevanceScore"], reverse=True)
        return parsed
