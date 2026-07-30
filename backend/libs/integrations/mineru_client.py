from __future__ import annotations

import os
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx


_RETRYABLE_PROVIDER_CODES = {"-10001", "-60007", "-60009"}
_OPTION_NAMES = {
    "language": "language",
    "pageRanges": "page_ranges",
    "noCache": "no_cache",
    "cacheTolerance": "cache_tolerance",
}


class MinerUError(RuntimeError):
    def __init__(
        self,
        code: str,
        safe_message: str,
        *,
        retryable: bool = False,
    ) -> None:
        super().__init__(safe_message)
        self.code = code
        self.retryable = retryable


class MinerUProtocolError(MinerUError):
    pass


class MinerUJobFailed(MinerUError):
    pass


@dataclass(frozen=True)
class MinerUConfig:
    base_url: str
    api_key: str
    model_version: str
    request_timeout_seconds: float
    poll_interval_seconds: float
    job_timeout_seconds: float
    max_download_bytes: int


def load_mineru_config(
    env: Mapping[str, str] | None = None,
    *,
    validate: bool = True,
) -> MinerUConfig:
    source = env if env is not None else os.environ
    try:
        config = MinerUConfig(
            base_url=str(
                source.get("AICHECK_MINERU_BASE_URL") or "https://mineru.net"
            ).rstrip("/"),
            api_key=str(source.get("AICHECK_MINERU_API_KEY") or ""),
            model_version=str(
                source.get("AICHECK_MINERU_MODEL_VERSION") or "vlm"
            ),
            request_timeout_seconds=float(
                source.get("AICHECK_MINERU_TIMEOUT_SECONDS") or 60
            ),
            poll_interval_seconds=max(
                float(
                    source.get("AICHECK_MINERU_POLL_INTERVAL_SECONDS") or 3
                ),
                0,
            ),
            job_timeout_seconds=float(
                source.get("AICHECK_MINERU_JOB_TIMEOUT_SECONDS") or 1800
            ),
            max_download_bytes=int(
                source.get("AICHECK_MINERU_MAX_DOWNLOAD_BYTES") or 536870912
            ),
        )
    except (TypeError, ValueError) as exc:
        raise MinerUProtocolError(
            "MINERU_CONFIG_INVALID",
            "MinerU configuration is invalid.",
        ) from exc
    if validate and not config.api_key:
        raise MinerUProtocolError(
            "MINERU_NOT_CONFIGURED",
            "MinerU API key is not configured.",
        )
    if config.model_version != "vlm":
        raise MinerUProtocolError(
            "MINERU_MODEL_INVALID",
            "MinerU model must be vlm.",
        )
    if (
        config.request_timeout_seconds <= 0
        or config.job_timeout_seconds <= 0
        or config.max_download_bytes <= 0
    ):
        raise MinerUProtocolError(
            "MINERU_CONFIG_INVALID",
            "MinerU configuration is invalid.",
        )
    return config


def mineru_request_options(options: Mapping[str, Any]) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model_version": "vlm",
        "is_ocr": True,
        "enable_formula": True,
        "enable_table": True,
    }
    for source_name, target_name in _OPTION_NAMES.items():
        value = options.get(source_name)
        if value is not None:
            body[target_name] = value
    return body


class MinerUClient:
    def __init__(
        self,
        config: MinerUConfig | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.config = config or load_mineru_config()
        kwargs: dict[str, Any] = {
            "base_url": self.config.base_url,
            "timeout": self.config.request_timeout_seconds,
        }
        if transport is not None:
            kwargs["transport"] = transport
        self.client = httpx.Client(**kwargs)

    def submit_url(
        self,
        url: str,
        *,
        data_id: str,
        options: Mapping[str, Any],
    ) -> dict[str, Any]:
        body = mineru_request_options(options)
        body.update({"url": url, "data_id": data_id})
        payload = self._request_json(
            "POST",
            "/api/v4/extract/task",
            json=body,
        )
        task_id = str((payload.get("data") or {}).get("task_id") or "")
        if not task_id:
            raise MinerUProtocolError(
                "MINERU_TASK_ID_MISSING",
                "MinerU response omitted task_id.",
            )
        return {"kind": "task", "providerTaskId": task_id}

    def submit_file(
        self,
        path: Path,
        *,
        data_id: str,
        options: Mapping[str, Any],
    ) -> dict[str, Any]:
        body = mineru_request_options(options)
        body["files"] = [
            {"name": path.name, "data_id": data_id, "is_ocr": True}
        ]
        payload = self._request_json(
            "POST",
            "/api/v4/file-urls/batch",
            json=body,
        )
        data = payload.get("data") or {}
        batch_id = str(data.get("batch_id") or "")
        upload_urls = data.get("file_urls") or []
        if not batch_id or not isinstance(upload_urls, list) or len(upload_urls) != 1:
            raise MinerUProtocolError(
                "MINERU_UPLOAD_URL_MISSING",
                "MinerU response omitted upload data.",
            )
        try:
            upload = self.client.put(
                str(upload_urls[0]),
                content=path.read_bytes(),
            )
        except (OSError, httpx.HTTPError) as exc:
            raise MinerUProtocolError(
                "MINERU_UPLOAD_FAILED",
                "MinerU file upload failed.",
                retryable=True,
            ) from exc
        if upload.status_code >= 400:
            raise MinerUProtocolError(
                "MINERU_UPLOAD_FAILED",
                "MinerU file upload failed.",
                retryable=(
                    upload.status_code == 429 or upload.status_code >= 500
                ),
            )
        return {"kind": "batch", "providerTaskId": batch_id}

    def wait_for_result(
        self,
        submission: Mapping[str, Any],
        *,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + self.config.job_timeout_seconds
        while time.monotonic() < deadline:
            status = self._task_status(submission)
            if progress_callback is not None:
                progress_callback(status)
            if status["state"] == "done":
                return status
            if status["state"] == "failed":
                raise MinerUJobFailed(
                    "MINERU_JOB_FAILED",
                    "MinerU parsing failed.",
                )
            if self.config.poll_interval_seconds:
                time.sleep(self.config.poll_interval_seconds)
        raise MinerUJobFailed(
            "MINERU_JOB_TIMEOUT",
            "MinerU parsing timed out.",
            retryable=True,
        )

    def download_result(self, url: str) -> bytes:
        chunks: list[bytes] = []
        total = 0
        try:
            with self.client.stream("GET", url) as response:
                if response.status_code >= 400:
                    raise MinerUProtocolError(
                        "MINERU_DOWNLOAD_FAILED",
                        "MinerU result download failed.",
                        retryable=(
                            response.status_code == 429
                            or response.status_code >= 500
                        ),
                    )
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > self.config.max_download_bytes:
                        raise MinerUProtocolError(
                            "MINERU_DOWNLOAD_TOO_LARGE",
                            "MinerU result exceeded the download limit.",
                        )
                    chunks.append(chunk)
        except MinerUProtocolError:
            raise
        except httpx.HTTPError as exc:
            raise MinerUProtocolError(
                "MINERU_DOWNLOAD_FAILED",
                "MinerU result download failed.",
                retryable=True,
            ) from exc
        return b"".join(chunks)

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        json: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            response = self.client.request(
                method,
                path,
                headers={"Authorization": f"Bearer {self.config.api_key}"},
                json=json,
            )
        except httpx.HTTPError as exc:
            raise MinerUProtocolError(
                "MINERU_REQUEST_FAILED",
                "MinerU request failed.",
                retryable=True,
            ) from exc
        if response.status_code >= 400:
            raise MinerUProtocolError(
                f"HTTP_{response.status_code}",
                "MinerU request failed.",
                retryable=(
                    response.status_code == 429 or response.status_code >= 500
                ),
            )
        try:
            payload = response.json()
        except (ValueError, TypeError) as exc:
            raise MinerUProtocolError(
                "MINERU_RESPONSE_INVALID",
                "MinerU returned an invalid response.",
            ) from exc
        if not isinstance(payload, dict):
            raise MinerUProtocolError(
                "MINERU_RESPONSE_INVALID",
                "MinerU returned an invalid response.",
            )
        code = str(payload.get("code", ""))
        if code not in {"0", ""}:
            raise MinerUProtocolError(
                code,
                "MinerU rejected the request.",
                retryable=code in _RETRYABLE_PROVIDER_CODES,
            )
        return payload

    def _task_status(
        self,
        submission: Mapping[str, Any],
    ) -> dict[str, Any]:
        provider_task_id = str(submission.get("providerTaskId") or "")
        kind = str(submission.get("kind") or "")
        if not provider_task_id or kind not in {"task", "batch"}:
            raise MinerUProtocolError(
                "MINERU_SUBMISSION_INVALID",
                "MinerU submission metadata is invalid.",
            )
        if kind == "task":
            payload = self._request_json(
                "GET",
                f"/api/v4/extract/task/{provider_task_id}",
            )
            data = payload.get("data") or {}
        else:
            payload = self._request_json(
                "GET",
                f"/api/v4/extract-results/batch/{provider_task_id}",
            )
            batch_data = payload.get("data") or {}
            results = batch_data.get("extract_result") or []
            if not isinstance(results, list) or len(results) != 1:
                raise MinerUProtocolError(
                    "MINERU_BATCH_RESULT_INVALID",
                    "MinerU returned invalid batch status.",
                )
            data = results[0]
        if not isinstance(data, Mapping):
            raise MinerUProtocolError(
                "MINERU_STATUS_INVALID",
                "MinerU returned invalid task status.",
            )
        state = str(data.get("state") or "").lower()
        if state == "waiting-file":
            state = "pending"
        if state not in {"pending", "running", "converting", "done", "failed"}:
            raise MinerUProtocolError(
                "MINERU_STATUS_INVALID",
                "MinerU returned invalid task status.",
            )
        full_zip_url = str(data.get("full_zip_url") or "")
        if state == "done" and not full_zip_url:
            raise MinerUProtocolError(
                "MINERU_RESULT_URL_MISSING",
                "MinerU response omitted the result URL.",
            )
        return {
            "state": state,
            "full_zip_url": full_zip_url or None,
            "extract_progress": data.get("extract_progress"),
        }
