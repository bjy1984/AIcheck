from __future__ import annotations

import os
from typing import Any

import httpx

from libs.integrations.errors import IntegrationServiceError, safe_reason


class OcrClient:
    def __init__(self, base_url: str | None = None, transport: Any | None = None) -> None:
        self.base_url = (base_url or os.getenv("AICHECK_OCR_BASE_URL") or "").rstrip("/")
        self.transport = transport

    @property
    def enabled(self) -> bool:
        return bool(self.base_url)

    def parse_sync(self, storage_key: str, *, file_name: str | None = None) -> dict[str, Any]:
        if not self.enabled:
            raise RuntimeError("AICHECK_OCR_BASE_URL is not configured")
        client_kwargs: dict[str, Any] = {"timeout": 120}
        if self.transport is not None:
            client_kwargs["transport"] = self.transport
        try:
            with httpx.Client(**client_kwargs) as client:
                response = client.post(
                    f"{self.base_url}/internal/ocr/parse",
                    json={"storageKey": storage_key, "fileName": file_name},
                )
        except httpx.HTTPError as exc:
            raise IntegrationServiceError("OCR service", "parse", reason=exc.__class__.__name__) from exc
        if response.status_code >= 400:
            raise IntegrationServiceError("OCR service", "parse", status_code=response.status_code)
        try:
            payload = response.json()
        except ValueError as exc:
            raise IntegrationServiceError("OCR service", "parse", reason="INVALID_JSON") from exc
        if not isinstance(payload, dict):
            raise IntegrationServiceError("OCR service", "parse", reason="INVALID_RESPONSE")
        if payload.get("code") != 0:
            data = payload.get("data") if isinstance(payload, dict) else {}
            reason = data.get("reason") if isinstance(data, dict) else None
            raise IntegrationServiceError("OCR service", "parse", reason=safe_reason(reason) or f"CODE_{payload.get('code')}")
        return payload.get("data") or {}
