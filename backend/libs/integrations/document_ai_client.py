from __future__ import annotations

import json
import os
from base64 import urlsafe_b64encode
from pathlib import Path
from typing import Any

import httpx

from libs.integrations.errors import IntegrationServiceError, safe_reason


def resolve_document_ai_base_url(base_url: str | None = None) -> str:
    return str(base_url or os.getenv("AICHECK_DOCUMENT_AI_BASE_URL") or "").strip().rstrip("/")


def resolve_document_ai_timeout(timeout_seconds: float | None = None) -> float:
    configured = timeout_seconds if timeout_seconds is not None else os.getenv("AICHECK_DOCUMENT_AI_TIMEOUT_SECONDS", "180")
    try:
        return max(1.0, min(float(configured), 180.0))
    except (TypeError, ValueError):
        return 180.0


class DocumentAiClient:
    def __init__(
        self,
        base_url: str | None = None,
        *,
        api_key: str | None = None,
        timeout_seconds: float | None = None,
        transport: Any | None = None,
    ) -> None:
        self.base_url = resolve_document_ai_base_url(base_url)
        self.api_key = str(api_key if api_key is not None else os.getenv("AICHECK_DOCUMENT_AI_API_KEY") or "").strip()
        self.timeout_seconds = resolve_document_ai_timeout(timeout_seconds)
        self.transport = transport

    @property
    def enabled(self) -> bool:
        return bool(self.base_url and self.api_key)

    def public_config(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "baseUrl": self._redacted_base_url(),
            "apiKeyConfigured": bool(self.api_key),
            "timeoutSeconds": self.timeout_seconds,
        }

    def health(self) -> dict[str, Any]:
        return self._request_json("GET", "/healthz", timeout=10)

    def ready(self) -> dict[str, Any]:
        return self._request_json("GET", "/readyz", timeout=15)

    def doctor(self) -> dict[str, Any]:
        return self._request_json("GET", "/internal/doctor", timeout=30)

    def extract_upload_sync(self, path: str | os.PathLike[str], payload: dict[str, Any]) -> dict[str, Any]:
        if not self.enabled:
            raise RuntimeError("Document AI shadow service is not configured")
        source_path = Path(path)
        if not source_path.is_file():
            raise IntegrationServiceError("Document AI service", "hybrid-extract", reason="LOCAL_FILE_MISSING")
        metadata = urlsafe_b64encode(json.dumps(payload, ensure_ascii=False).encode("utf-8")).decode("ascii")
        headers = {
            **self._auth_headers(),
            "Content-Type": "application/octet-stream",
            "X-AICheck-Document-Ai-Metadata-B64": metadata,
        }
        client_kwargs: dict[str, Any] = {"timeout": self.timeout_seconds}
        if self.transport is not None:
            client_kwargs["transport"] = self.transport
        try:
            with source_path.open("rb") as handle:
                with httpx.Client(**client_kwargs) as client:
                    response = client.post(
                        f"{self.base_url}/v1/hybrid/extract",
                        headers=headers,
                        content=handle.read(),
                    )
        except httpx.HTTPError as exc:
            raise IntegrationServiceError(
                "Document AI service",
                "hybrid-extract",
                reason=exc.__class__.__name__.upper(),
            ) from exc
        return self._decode_response(response, "hybrid-extract")

    def _request_json(self, method: str, path: str, *, timeout: float) -> dict[str, Any]:
        if not self.enabled:
            raise RuntimeError("Document AI shadow service is not configured")
        client_kwargs: dict[str, Any] = {"timeout": timeout}
        if self.transport is not None:
            client_kwargs["transport"] = self.transport
        try:
            with httpx.Client(**client_kwargs) as client:
                response = client.request(method, f"{self.base_url}{path}", headers=self._auth_headers())
        except httpx.HTTPError as exc:
            raise IntegrationServiceError(
                "Document AI service",
                path.strip("/") or "request",
                reason=exc.__class__.__name__.upper(),
            ) from exc
        return self._decode_response(response, path.strip("/") or "request")

    def _decode_response(self, response: httpx.Response, operation: str) -> dict[str, Any]:
        if response.status_code >= 400:
            reason = None
            try:
                error_payload = response.json()
                if isinstance(error_payload, dict):
                    reason = error_payload.get("reason") or error_payload.get("detail")
                    if isinstance(reason, dict):
                        reason = reason.get("code") or reason.get("reason")
            except ValueError:
                reason = None
            raise IntegrationServiceError(
                "Document AI service",
                operation,
                status_code=response.status_code,
                reason=safe_reason(reason),
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise IntegrationServiceError("Document AI service", operation, reason="INVALID_JSON") from exc
        if not isinstance(payload, dict):
            raise IntegrationServiceError("Document AI service", operation, reason="INVALID_RESPONSE")
        if "code" in payload:
            if payload.get("code") != 0:
                data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
                raise IntegrationServiceError(
                    "Document AI service",
                    operation,
                    reason=safe_reason(data.get("reason")) or f"CODE_{payload.get('code')}",
                )
            data = payload.get("data")
            if not isinstance(data, dict):
                raise IntegrationServiceError("Document AI service", operation, reason="INVALID_RESPONSE")
            return data
        return payload

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    def _redacted_base_url(self) -> str | None:
        if not self.base_url:
            return None
        try:
            parsed = httpx.URL(self.base_url)
            host = parsed.host or "configured"
            port = f":{parsed.port}" if parsed.port else ""
            return f"{parsed.scheme}://{host}{port}"
        except Exception:
            return "configured"
