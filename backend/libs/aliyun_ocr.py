from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import threading
import time
import unicodedata
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from PIL import Image

from libs.ocr_runtime import ocr_runtime_config


RETRYABLE_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}
SEAL_TEXT_RE = re.compile(
    r"(?:专用章|公章|审核章|审查章|检验章|检测章|设计章|竣工章|TS\s*\d{6,}|A\d{8,})",
    re.IGNORECASE,
)


class AliyunOcrError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        reason: str | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.reason = reason
        self.retry_after = retry_after


class AliyunOcrRetryableError(AliyunOcrError):
    pass


class AliyunOcrCircuitOpen(AliyunOcrRetryableError):
    pass


@dataclass
class EncodedOcrImage:
    data_url: str
    width: int
    height: int
    mime_type: str
    byte_count: int
    sha256: str
    max_pixels: int


class OfficialOcrCircuitBreaker:
    def __init__(self, failure_threshold: int, open_seconds: int) -> None:
        self.failure_threshold = max(1, int(failure_threshold))
        self.open_seconds = max(1, int(open_seconds))
        self._lock = threading.Lock()
        self._failures = 0
        self._opened_at: float | None = None
        self._last_error: str | None = None

    def before_call(self) -> None:
        with self._lock:
            if self._opened_at is None:
                return
            elapsed = time.monotonic() - self._opened_at
            if elapsed >= self.open_seconds:
                self._opened_at = None
                self._failures = 0
                return
            raise AliyunOcrCircuitOpen(
                "Aliyun OCR circuit is open",
                reason="CIRCUIT_OPEN",
                retry_after=max(self.open_seconds - elapsed, 1.0),
            )

    def success(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_at = None
            self._last_error = None

    def failure(self, reason: str) -> None:
        with self._lock:
            self._failures += 1
            self._last_error = reason
            if self._failures >= self.failure_threshold:
                self._opened_at = time.monotonic()

    def public_status(self) -> dict[str, Any]:
        with self._lock:
            opened = self._opened_at is not None and time.monotonic() - self._opened_at < self.open_seconds
            retry_after = (
                max(self.open_seconds - (time.monotonic() - self._opened_at), 0.0)
                if opened and self._opened_at is not None
                else 0.0
            )
            return {
                "open": opened,
                "failureCount": self._failures,
                "failureThreshold": self.failure_threshold,
                "retryAfterSeconds": round(retry_after, 1),
                "lastError": self._last_error,
            }


_CIRCUIT_LOCK = threading.Lock()
_CIRCUIT: OfficialOcrCircuitBreaker | None = None
_CIRCUIT_KEY: tuple[int, int] | None = None


def official_ocr_circuit_breaker(runtime: dict[str, Any] | None = None) -> OfficialOcrCircuitBreaker:
    global _CIRCUIT, _CIRCUIT_KEY
    current = runtime or ocr_runtime_config()
    official = current["official"]
    key = (int(official["circuitFailureThreshold"]), int(official["circuitOpenSeconds"]))
    with _CIRCUIT_LOCK:
        if _CIRCUIT is None or _CIRCUIT_KEY != key:
            _CIRCUIT = OfficialOcrCircuitBreaker(*key)
            _CIRCUIT_KEY = key
        return _CIRCUIT


def _adaptive_image_payload(path: Path, runtime: dict[str, Any]) -> EncodedOcrImage:
    render = runtime["render"]
    max_long_side = int(render["maxLongSide"])
    jpeg_quality = max(78, min(int(render["jpegQuality"]), 95))
    with Image.open(path) as source:
        source.load()
        image = source.convert("RGB")
        if max(image.size) > max_long_side:
            image.thumbnail((max_long_side, max_long_side), Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        image.save(
            buffer,
            format="JPEG",
            quality=jpeg_quality,
            optimize=True,
            progressive=True,
            subsampling=0,
        )
        payload = buffer.getvalue()
        width, height = image.size
    digest = hashlib.sha256(payload).hexdigest()
    encoded = base64.b64encode(payload).decode("ascii")
    return EncodedOcrImage(
        data_url=f"data:image/jpeg;base64,{encoded}",
        width=int(width),
        height=int(height),
        mime_type="image/jpeg",
        byte_count=len(payload),
        sha256=digest,
        max_pixels=int(width * height),
    )


def _response_error_reason(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return f"HTTP_{response.status_code}"
    if not isinstance(payload, dict):
        return f"HTTP_{response.status_code}"
    error = payload.get("error")
    if isinstance(error, dict):
        return str(error.get("code") or error.get("type") or f"HTTP_{response.status_code}")
    return str(payload.get("code") or f"HTTP_{response.status_code}")


def _retry_after(response: httpx.Response) -> float | None:
    raw = response.headers.get("Retry-After")
    if not raw:
        return None
    try:
        return max(float(raw), 0.0)
    except ValueError:
        return None


def _compatible_endpoint(base_url: str) -> bool:
    clean = base_url.rstrip("/")
    return "compatible-mode" in clean or clean.endswith("/chat/completions")


def _endpoint(base_url: str) -> str:
    clean = base_url.rstrip("/")
    if _compatible_endpoint(clean):
        if clean.endswith("/chat/completions"):
            return clean
        return f"{clean}/chat/completions"
    if clean.endswith("/generation"):
        return clean
    if clean.endswith("/api/v1"):
        return f"{clean}/services/aigc/multimodal-generation/generation"
    return clean


def _content_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    output = payload.get("output") if isinstance(payload.get("output"), dict) else {}
    choices = output.get("choices") if isinstance(output.get("choices"), list) else []
    if not choices and isinstance(payload.get("choices"), list):
        choices = payload["choices"]
    if not choices:
        return []
    message = choices[0].get("message") if isinstance(choices[0], dict) else {}
    content = message.get("content") if isinstance(message, dict) else []
    if isinstance(content, dict):
        return [content]
    if isinstance(content, str):
        return [{"text": content}]
    return [item for item in content or [] if isinstance(item, dict)]


def response_ocr_result(payload: dict[str, Any]) -> Any:
    for item in _content_items(payload):
        if item.get("ocr_result") is not None:
            return item.get("ocr_result")
    return None


def response_text(payload: dict[str, Any]) -> str:
    values = [str(item.get("text") or "") for item in _content_items(payload) if item.get("text")]
    return "\n".join(value for value in values if value).strip()


def response_usage(payload: dict[str, Any]) -> dict[str, int]:
    raw = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    input_tokens = int(raw.get("input_tokens") or raw.get("prompt_tokens") or 0)
    output_tokens = int(raw.get("output_tokens") or raw.get("completion_tokens") or 0)
    details = raw.get("input_tokens_details") if isinstance(raw.get("input_tokens_details"), dict) else {}
    image_tokens = int(raw.get("image_tokens") or details.get("image_tokens") or 0)
    return {
        "inputTokens": input_tokens,
        "outputTokens": output_tokens,
        "imageTokens": image_tokens,
        "totalTokens": int(raw.get("total_tokens") or input_tokens + output_tokens),
    }


def ocr_cost_cny(model: str, usage: dict[str, int]) -> float:
    if str(model).startswith("qwen-vl-ocr"):
        input_rate, output_rate = 0.3, 0.5
    else:
        input_rate, output_rate = 0.5, 2.0
    return round(
        (
            int(usage.get("inputTokens") or 0) * input_rate
            + int(usage.get("outputTokens") or 0) * output_rate
        )
        / 1_000_000,
        6,
    )


def _request_payload(
    base_url: str,
    *,
    model: str,
    encoded: EncodedOcrImage,
    ocr_options: dict[str, Any],
    max_tokens: int,
) -> dict[str, Any]:
    min_pixels = 32 * 32 * 3
    max_pixels = max(min_pixels, encoded.max_pixels)
    if _compatible_endpoint(base_url):
        return {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": encoded.data_url},
                            "min_pixels": min_pixels,
                            "max_pixels": max_pixels,
                            "enable_rotate": False,
                        }
                    ],
                }
            ],
            "ocr_options": ocr_options,
            "max_tokens": int(max_tokens),
        }
    return {
        "model": model,
        "input": {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "image": encoded.data_url,
                            "min_pixels": min_pixels,
                            "max_pixels": max_pixels,
                            "enable_rotate": False,
                        }
                    ],
                }
            ]
        },
        "parameters": {"ocr_options": ocr_options, "max_tokens": int(max_tokens)},
    }


class AliyunQwenOcrClient:
    def __init__(
        self,
        *,
        runtime: dict[str, Any] | None = None,
        transport: httpx.BaseTransport | None = None,
        circuit_breaker: OfficialOcrCircuitBreaker | None = None,
    ) -> None:
        self.runtime = runtime or ocr_runtime_config(validate=True)
        self.transport = transport
        self.circuit_breaker = circuit_breaker or official_ocr_circuit_breaker(self.runtime)

    def call(
        self,
        image_path: Path,
        *,
        task: str,
        page_no: int,
        result_schema: dict[str, Any] | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        official = self.runtime["official"]
        self.circuit_breaker.before_call()
        encoded = _adaptive_image_payload(image_path, self.runtime)
        selected_model = str(model or official["primaryModel"])
        ocr_options: dict[str, Any] = {"task": task}
        if result_schema:
            ocr_options["task_config"] = {"result_schema": result_schema}
        request_payload = _request_payload(
            str(official["baseUrl"]),
            model=selected_model,
            encoded=encoded,
            ocr_options=ocr_options,
            max_tokens=int(official["maxOutputTokens"]),
        )
        timeout = httpx.Timeout(float(official["timeoutSeconds"]), connect=10.0)
        client_kwargs: dict[str, Any] = {"timeout": timeout}
        if self.transport is not None:
            client_kwargs["transport"] = self.transport
        started = time.monotonic()
        try:
            with httpx.Client(**client_kwargs) as client:
                response = client.post(
                    _endpoint(str(official["baseUrl"])),
                    headers={"Authorization": f"Bearer {official['apiKey']}"},
                    json=request_payload,
                )
        except httpx.HTTPError as exc:
            reason = exc.__class__.__name__.upper()
            self.circuit_breaker.failure(reason)
            raise AliyunOcrRetryableError("Aliyun OCR request failed", reason=reason) from exc
        elapsed_ms = round((time.monotonic() - started) * 1000)
        if response.status_code >= 400:
            reason = _response_error_reason(response)
            self.circuit_breaker.failure(reason)
            error_class = AliyunOcrRetryableError if response.status_code in RETRYABLE_STATUS_CODES else AliyunOcrError
            raise error_class(
                "Aliyun OCR returned an error",
                status_code=response.status_code,
                reason=reason,
                retry_after=_retry_after(response),
            )
        try:
            payload = response.json()
        except ValueError as exc:
            self.circuit_breaker.failure("INVALID_JSON")
            raise AliyunOcrRetryableError("Aliyun OCR returned invalid JSON", reason="INVALID_JSON") from exc
        if not isinstance(payload, dict):
            self.circuit_breaker.failure("INVALID_RESPONSE")
            raise AliyunOcrRetryableError("Aliyun OCR returned an invalid response", reason="INVALID_RESPONSE")
        self.circuit_breaker.success()
        usage = response_usage(payload)
        request_id = str(
            payload.get("request_id")
            or payload.get("requestId")
            or payload.get("id")
            or response.headers.get("x-request-id")
            or ""
        )
        return {
            "provider": "aliyun_model_studio",
            "model": selected_model,
            "task": task,
            "pageNo": int(page_no),
            "requestId": request_id or None,
            "ocrResult": response_ocr_result(payload),
            "text": response_text(payload),
            "usage": usage,
            "costCny": ocr_cost_cny(selected_model, usage),
            "durationMs": elapsed_ms,
            "input": {
                "width": encoded.width,
                "height": encoded.height,
                "mimeType": encoded.mime_type,
                "byteCount": encoded.byte_count,
                "sha256": encoded.sha256,
                "maxPixels": encoded.max_pixels,
            },
        }


def _bbox_from_location(location: Any) -> tuple[list[float] | None, list[float] | None]:
    if not isinstance(location, (list, tuple)) or len(location) < 8:
        return None, None
    try:
        values = [float(value) for value in location[:8]]
    except (TypeError, ValueError):
        return None, None
    xs = values[0::2]
    ys = values[1::2]
    return [min(xs), min(ys), max(xs), max(ys)], values


def _candidate_id(page_no: int, text: str, polygon: list[float] | None) -> str:
    digest = hashlib.sha256(
        json.dumps(
            {"pageNo": page_no, "text": text, "polygon": polygon or []},
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()[:16].upper()
    return f"OCR-CAND-{digest}"


def advanced_fragments(call: dict[str, Any]) -> list[dict[str, Any]]:
    result = call.get("ocrResult")
    words = result.get("words_info") if isinstance(result, dict) else None
    fragments: list[dict[str, Any]] = []
    for item in words or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        bbox, polygon = _bbox_from_location(item.get("location"))
        candidate_id = _candidate_id(int(call["pageNo"]), text, polygon)
        fragments.append(
            {
                "candidateId": candidate_id,
                "pageNo": int(call["pageNo"]),
                "text": text,
                "bbox": bbox,
                "polygon": polygon,
                "rotateRect": item.get("rotate_rect"),
                "coordinateSystem": "rendered_pixels",
                "sourceEngine": "aliyun_qwen_ocr_advanced",
                "sourceCandidateIds": [candidate_id],
                "formalEvidenceEligible": bool(bbox),
                "providerConfidenceReported": False,
            }
        )
    if not fragments and str(call.get("text") or "").strip():
        text = str(call["text"]).strip()
        candidate_id = _candidate_id(int(call["pageNo"]), text, None)
        fragments.append(
            {
                "candidateId": candidate_id,
                "pageNo": int(call["pageNo"]),
                "text": text,
                "bbox": None,
                "polygon": None,
                "coordinateSystem": "rendered_pixels",
                "sourceEngine": "aliyun_qwen_ocr_advanced",
                "sourceCandidateIds": [candidate_id],
                "formalEvidenceEligible": False,
                "advisoryOnly": True,
                "providerConfidenceReported": False,
            }
        )
    return fragments


def normalize_match_text(value: Any) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).lower()
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", normalized)


def _empty_value(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _flatten_values(value: Any, prefix: str = "") -> dict[str, Any]:
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        for key, item in value.items():
            name = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(item, dict):
                output.update(_flatten_values(item, name))
            else:
                output[name] = item
        return output
    if isinstance(value, list):
        return {prefix or "value": value}
    return {prefix or "value": value}


def kie_values(call: dict[str, Any]) -> dict[str, Any]:
    result = call.get("ocrResult")
    if isinstance(result, dict):
        raw = result.get("kv_result")
        if raw is None:
            raw = result.get("result")
        if isinstance(raw, dict):
            return _flatten_values(raw)
        if isinstance(raw, list):
            merged: dict[str, Any] = {}
            for item in raw:
                if isinstance(item, dict):
                    merged.update(_flatten_values(item))
            if merged:
                return merged
    text = str(call.get("text") or "").strip()
    if text:
        cleaned = text.removeprefix("```json").removesuffix("```").strip()
        try:
            payload = json.loads(cleaned)
        except ValueError:
            return {}
        if isinstance(payload, dict):
            return _flatten_values(payload)
    return {}


def _union_bbox(items: list[dict[str, Any]]) -> list[float] | None:
    boxes = [item.get("bbox") for item in items if isinstance(item.get("bbox"), list) and len(item["bbox"]) >= 4]
    if not boxes:
        return None
    return [
        min(float(box[0]) for box in boxes),
        min(float(box[1]) for box in boxes),
        max(float(box[2]) for box in boxes),
        max(float(box[3]) for box in boxes),
    ]


def _value_matches_fragment(needle: str, candidate: str) -> bool:
    if not needle or not candidate:
        return False
    if needle == candidate:
        return True
    if len(needle) >= 3 and needle in candidate:
        return True
    return len(candidate) >= max(3, int(len(needle) * 0.7)) and candidate in needle


def match_value_to_fragments(value: Any, fragments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    needle = normalize_match_text(value)
    if not needle:
        return []
    exact = [
        item
        for item in fragments
        if _value_matches_fragment(needle, normalize_match_text(item.get("text")))
    ]
    if exact:
        exact.sort(
            key=lambda item: (
                normalize_match_text(item.get("text")) != needle,
                abs(len(normalize_match_text(item.get("text"))) - len(needle)),
            )
        )
        return exact[:3]
    by_page: dict[int, list[dict[str, Any]]] = {}
    for item in fragments:
        by_page.setdefault(int(item.get("pageNo") or 1), []).append(item)
    for rows in by_page.values():
        for width in (2, 3):
            for index in range(0, max(len(rows) - width + 1, 0)):
                group = rows[index : index + width]
                combined = normalize_match_text("".join(str(item.get("text") or "") for item in group))
                if _value_matches_fragment(needle, combined):
                    return group
    return []


def grounded_kie_fields(
    calls: list[dict[str, Any]],
    fragments: list[dict[str, Any]],
    *,
    field_labels: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    labels = field_labels or {}
    for call in calls:
        for code, value in kie_values(call).items():
            if _empty_value(value):
                continue
            matched = match_value_to_fragments(value, fragments)
            candidate_ids = [str(item.get("candidateId")) for item in matched if item.get("candidateId")]
            bbox = _union_bbox(matched)
            page_no = (
                int(matched[0].get("pageNo") or call.get("pageNo") or 1)
                if matched
                else int(call.get("pageNo") or 1)
            )
            formal = bool(candidate_ids and bbox)
            output[str(code)] = {
                "fieldCode": str(code),
                "fieldName": str(labels.get(str(code)) or code),
                "fieldValue": value,
                "value": value,
                "pageNo": page_no,
                "bbox": bbox,
                "sourceCandidateIds": candidate_ids,
                "sourceEngine": "aliyun_qwen_ocr_kie",
                "formalEvidenceEligible": formal,
                "advisoryOnly": not formal,
                "providerConfidenceReported": False,
            }
    return list(output.values())


def table_from_call(call: dict[str, Any], table_code: str) -> dict[str, Any] | None:
    raw = call.get("ocrResult")
    text = str(call.get("text") or "").strip()
    if _empty_value(raw) and not text:
        return None
    return {
        "tableId": f"ALIYUN-TABLE-{call.get('pageNo')}-{hashlib.sha256(str(table_code).encode()).hexdigest()[:8]}",
        "tableCode": table_code,
        "pageNo": int(call.get("pageNo") or 1),
        "content": deepcopy(raw) if not _empty_value(raw) else text,
        "html": text if "<table" in text.lower() else None,
        "cells": [],
        "bbox": None,
        "sourceEngine": "aliyun_qwen_ocr_table",
        "formalEvidenceEligible": False,
        "advisoryOnly": True,
        "qualityFlags": ["table_structure_requires_cell_grounding"],
    }


def seal_candidates_from_fragments(fragments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for item in fragments:
        text = str(item.get("text") or "")
        if not SEAL_TEXT_RE.search(text):
            continue
        bbox = item.get("bbox")
        candidate_id = str(item.get("candidateId") or "")
        output.append(
            {
                "sealId": f"SEAL-{candidate_id or hashlib.sha256(text.encode()).hexdigest()[:12]}",
                "sealName": text,
                "text": text,
                "pageNo": int(item.get("pageNo") or 1),
                "bbox": bbox,
                "sourceCandidateIds": [candidate_id] if candidate_id else [],
                "sourceEngine": "aliyun_qwen_ocr_advanced",
                "sealEvidenceLevel": "official_ocr_text_candidate",
                "canSatisfyRequiredSeal": False,
                "formalEvidenceEligible": False,
                "advisoryOnly": True,
            }
        )
    return output
