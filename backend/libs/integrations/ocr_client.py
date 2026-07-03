from __future__ import annotations

import os
import time
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

    def create_parse_job(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request_enveloped("POST", "/internal/document-parse/jobs", json=payload, timeout=30)

    def get_parse_job(self, job_id: str) -> dict[str, Any]:
        return self._request_enveloped("GET", f"/internal/document-parse/jobs/{job_id}", timeout=30)

    def retry_parse_job(self, job_id: str) -> dict[str, Any]:
        return self._request_enveloped("POST", f"/internal/document-parse/jobs/{job_id}/retry", timeout=30)

    def get_parse_result(self, parse_result_id: str) -> dict[str, Any]:
        return self._request_enveloped("GET", f"/internal/document-parse/results/{parse_result_id}", timeout=30)

    def runtime_doctor(self) -> dict[str, Any]:
        return self._request_enveloped("GET", "/internal/ocr/doctor", timeout=10)

    def page_preview(self, payload: dict[str, Any], *, timeout: float = 30) -> tuple[bytes, str]:
        if not self.enabled:
            raise RuntimeError("AICHECK_OCR_BASE_URL is not configured")
        client_kwargs: dict[str, Any] = {"timeout": timeout}
        if self.transport is not None:
            client_kwargs["transport"] = self.transport
        try:
            with httpx.Client(**client_kwargs) as client:
                response = client.post(f"{self.base_url}/internal/ocr/page-preview", json=payload)
        except httpx.HTTPError as exc:
            raise IntegrationServiceError("OCR service", "page-preview", reason=exc.__class__.__name__) from exc
        if response.status_code >= 400:
            raise IntegrationServiceError("OCR service", "page-preview", status_code=response.status_code)
        content_type = response.headers.get("content-type") or "image/png"
        if "application/json" in content_type:
            try:
                payload = response.json()
            except ValueError as exc:
                raise IntegrationServiceError("OCR service", "page-preview", reason="INVALID_JSON") from exc
            if isinstance(payload, dict) and payload.get("code") != 0:
                data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
                raise IntegrationServiceError(
                    "OCR service",
                    "page-preview",
                    reason=safe_reason(data.get("reason")) or f"CODE_{payload.get('code')}",
                )
            raise IntegrationServiceError("OCR service", "page-preview", reason="INVALID_CONTENT_TYPE")
        if not response.content:
            raise IntegrationServiceError("OCR service", "page-preview", reason="EMPTY_RESPONSE")
        return response.content, content_type

    def parse_via_job_sync(
        self,
        payload: dict[str, Any],
        *,
        timeout_seconds: float = 120,
        poll_interval: float = 0.5,
    ) -> dict[str, Any]:
        job = self.create_parse_job(payload)
        job_id = str(job.get("jobId") or "")
        if not job_id:
            raise IntegrationServiceError("OCR service", "document-parse/jobs", reason="MISSING_JOB_ID")
        deadline = time.monotonic() + timeout_seconds
        last_job = job
        while time.monotonic() < deadline:
            last_job = self.get_parse_job(job_id)
            status = str(last_job.get("status") or "")
            if status == "success":
                parse_result_id = str(last_job.get("parseResultId") or "")
                result = self.get_parse_result(parse_result_id) if parse_result_id else {}
                result["jobId"] = job_id
                result["externalJobId"] = job_id
                return result
            if status in {"failed", "cancelled"}:
                return {
                    "jobId": job_id,
                    "externalJobId": job_id,
                    "parseResultId": last_job.get("parseResultId"),
                    "storageKey": payload.get("storageKey"),
                    "fileName": payload.get("fileName"),
                    "status": "failed",
                    "fragments": [],
                    "fields": [],
                    "seals": [],
                    "tables": [],
                    "diagnostics": last_job.get("diagnostics") or [f"OCR job {status}"],
                    "engineRuns": last_job.get("engineRuns") or [],
                }
            time.sleep(poll_interval)
        return {
            "jobId": job_id,
            "externalJobId": job_id,
            "storageKey": payload.get("storageKey"),
            "fileName": payload.get("fileName"),
            "status": "failed",
            "fragments": [],
            "fields": [],
            "seals": [],
            "tables": [],
            "diagnostics": [f"OCR job timeout after {timeout_seconds:g}s"],
            "engineRuns": last_job.get("engineRuns") or [],
        }

    def _request_enveloped(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        if not self.enabled:
            raise RuntimeError("AICHECK_OCR_BASE_URL is not configured")
        client_kwargs: dict[str, Any] = {"timeout": kwargs.pop("timeout", 120)}
        if self.transport is not None:
            client_kwargs["transport"] = self.transport
        try:
            with httpx.Client(**client_kwargs) as client:
                response = client.request(method, f"{self.base_url}{path}", **kwargs)
        except httpx.HTTPError as exc:
            raise IntegrationServiceError("OCR service", path, reason=exc.__class__.__name__) from exc
        if response.status_code >= 400:
            raise IntegrationServiceError("OCR service", path, status_code=response.status_code)
        try:
            payload = response.json()
        except ValueError as exc:
            raise IntegrationServiceError("OCR service", path, reason="INVALID_JSON") from exc
        if not isinstance(payload, dict):
            raise IntegrationServiceError("OCR service", path, reason="INVALID_RESPONSE")
        if payload.get("code") != 0:
            data = payload.get("data") if isinstance(payload, dict) else {}
            reason = data.get("reason") if isinstance(data, dict) else None
            raise IntegrationServiceError("OCR service", path, reason=safe_reason(reason) or f"CODE_{payload.get('code')}")
        return payload.get("data") or {}
