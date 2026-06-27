from __future__ import annotations

import os
from typing import Any

import httpx


class OcrClient:
    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (base_url or os.getenv("AICHECK_OCR_BASE_URL") or "").rstrip("/")

    @property
    def enabled(self) -> bool:
        return bool(self.base_url)

    def parse_sync(self, storage_key: str, *, file_name: str | None = None) -> dict[str, Any]:
        if not self.enabled:
            raise RuntimeError("AICHECK_OCR_BASE_URL is not configured")
        with httpx.Client(timeout=120) as client:
            response = client.post(
                f"{self.base_url}/internal/ocr/parse",
                json={"storageKey": storage_key, "fileName": file_name},
            )
            response.raise_for_status()
            payload = response.json()
        if payload.get("code") != 0:
            raise RuntimeError(payload.get("message") or "OCR service failed")
        return payload.get("data") or {}
