from __future__ import annotations

import json
from typing import Any

import httpx

from libs.raw_vault import RawCapture, RawCaptureContext, canonical_json_bytes


def json_transport_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _capture(
    capture: RawCapture | None,
    context: RawCaptureContext | None,
    event_type: str,
    payload: bytes,
    media_type: str,
    metadata: dict[str, Any],
) -> None:
    if capture is not None and context is not None:
        capture.capture_best_effort(context, event_type, payload, media_type, metadata)


def post_json_with_raw_capture(
    client: httpx.Client,
    url: str,
    *,
    headers: dict[str, str],
    payload: dict[str, Any],
    capture: RawCapture | None,
    context: RawCaptureContext | None,
    provider: str,
    operation: str,
) -> httpx.Response:
    body = json_transport_bytes(payload)
    metadata = {"provider": provider, "operation": operation}
    _capture(capture, context, "llm.request.prepared", body, "application/json", metadata)
    try:
        response = client.post(url, headers=headers, content=body)
    except httpx.HTTPError as exc:
        error_body = canonical_json_bytes(
            {"exceptionType": type(exc).__name__, "phase": "transport", "provider": provider}
        )
        _capture(capture, context, "llm.transport.error", error_body, "application/json", metadata)
        raise
    response_type = response.headers.get("content-type", "application/octet-stream")
    response_event = "llm.response.error" if response.status_code >= 400 else "llm.response.received"
    _capture(
        capture,
        context,
        response_event,
        response.content,
        response_type,
        {**metadata, "statusCode": response.status_code},
    )
    return response


async def post_json_with_raw_capture_async(
    client: httpx.AsyncClient,
    url: str,
    *,
    headers: dict[str, str],
    payload: dict[str, Any],
    capture: RawCapture | None,
    context: RawCaptureContext | None,
    provider: str,
    operation: str,
) -> httpx.Response:
    body = json_transport_bytes(payload)
    metadata = {"provider": provider, "operation": operation}
    _capture(capture, context, "llm.request.prepared", body, "application/json", metadata)
    try:
        response = await client.post(url, headers=headers, content=body)
    except httpx.HTTPError as exc:
        error_body = canonical_json_bytes(
            {"exceptionType": type(exc).__name__, "phase": "transport", "provider": provider}
        )
        _capture(capture, context, "llm.transport.error", error_body, "application/json", metadata)
        raise
    response_type = response.headers.get("content-type", "application/octet-stream")
    response_event = "llm.response.error" if response.status_code >= 400 else "llm.response.received"
    _capture(
        capture,
        context,
        response_event,
        response.content,
        response_type,
        {**metadata, "statusCode": response.status_code},
    )
    return response
