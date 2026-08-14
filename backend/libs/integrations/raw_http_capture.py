from __future__ import annotations

import json
from typing import Any

import httpx

from libs.raw_vault import RawCapture, RawCaptureContext, canonical_json_bytes


def json_transport_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def json_request_headers(headers: dict[str, str]) -> dict[str, str]:
    """补上 Content-Type: application/json。

    这几个函数都用 `content=<bytes>` 发送而不是 `json=`——为的是原样留痕
    （raw vault 记的必须是真正上线的那串字节）。代价是 httpx 不会自动带
    Content-Type，只有用 `json=` 才会。

    2026-08-14 因此踩坑：DashScope 和 LiteLLM 都容忍缺这个头，换到 DeepSeek
    直接 HTTP 415。**能跑通不等于请求是对的**——之前一直发着不合规的请求，
    只是对端宽容。

    调用方显式给了 Content-Type 就以调用方为准。
    """
    resolved = {"Content-Type": "application/json"}
    resolved.update(headers or {})
    return resolved


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
        response = client.post(url, headers=json_request_headers(headers), content=body)
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
        response = await client.post(url, headers=json_request_headers(headers), content=body)
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


def stream_chat_completion_with_raw_capture(
    client: httpx.Client,
    url: str,
    *,
    headers: dict[str, str],
    payload: dict[str, Any],
    capture: RawCapture | None,
    context: RawCaptureContext | None,
    provider: str,
    operation: str,
    on_delta: Any = None,
) -> dict[str, Any]:
    """以 SSE 串流执行 OpenAI 兼容 chat/completions，组装为一次性响应结构并全程留痕。

    on_delta(kind, text)：kind ∈ {"content", "reasoning"}，仅转发供应商实际返回的增量，
    不伪造任何内容。工具调用分片按 index 聚合还原为完整 tool_calls。
    组装结果带 "streamed": true 标记，usage 依赖供应商支持 stream_options.include_usage。
    """
    body = json_transport_bytes(payload)
    metadata: dict[str, Any] = {"provider": provider, "operation": operation, "stream": True}
    _capture(capture, context, "llm.request.prepared", body, "application/json", metadata)
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    tool_calls_acc: dict[int, dict[str, Any]] = {}
    finish_reason: Any = None
    usage: dict[str, Any] | None = None
    response_id: Any = None
    model_name: Any = None
    try:
        with client.stream("POST", url, headers=json_request_headers(headers), content=body) as response:
            if response.status_code >= 400:
                error_body = response.read()
                _capture(
                    capture,
                    context,
                    "llm.response.error",
                    error_body,
                    response.headers.get("content-type", "application/octet-stream"),
                    {**metadata, "statusCode": response.status_code},
                )
                raise httpx.HTTPStatusError(
                    f"stream request failed with status {response.status_code}",
                    request=response.request,
                    response=response,
                )
            for line in response.iter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if not data or data == "[DONE]":
                    continue
                try:
                    chunk = json.loads(data)
                except ValueError:
                    continue
                if not isinstance(chunk, dict):
                    continue
                response_id = response_id or chunk.get("id")
                model_name = model_name or chunk.get("model")
                if isinstance(chunk.get("usage"), dict):
                    usage = chunk["usage"]
                for choice in chunk.get("choices") or []:
                    if not isinstance(choice, dict):
                        continue
                    finish_reason = choice.get("finish_reason") or finish_reason
                    delta = choice.get("delta") if isinstance(choice.get("delta"), dict) else {}
                    piece = delta.get("content")
                    if piece:
                        content_parts.append(str(piece))
                        if on_delta is not None:
                            on_delta("content", str(piece))
                    reasoning_piece = delta.get("reasoning_content") or delta.get("reasoning")
                    if reasoning_piece:
                        reasoning_parts.append(str(reasoning_piece))
                        if on_delta is not None:
                            on_delta("reasoning", str(reasoning_piece))
                    for fragment in delta.get("tool_calls") or []:
                        if not isinstance(fragment, dict):
                            continue
                        try:
                            index = int(fragment.get("index") or 0)
                        except (TypeError, ValueError):
                            index = 0
                        slot = tool_calls_acc.setdefault(
                            index,
                            {"id": None, "type": "function", "function": {"name": "", "arguments": ""}},
                        )
                        if fragment.get("id"):
                            slot["id"] = fragment["id"]
                        function = (
                            fragment.get("function") if isinstance(fragment.get("function"), dict) else {}
                        )
                        if function.get("name"):
                            slot["function"]["name"] = str(function["name"])
                        if function.get("arguments"):
                            slot["function"]["arguments"] += str(function["arguments"])
    except httpx.HTTPStatusError:
        raise
    except httpx.HTTPError as exc:
        error_body = canonical_json_bytes(
            {"exceptionType": type(exc).__name__, "phase": "transport", "provider": provider, "stream": True}
        )
        _capture(capture, context, "llm.transport.error", error_body, "application/json", metadata)
        raise
    message: dict[str, Any] = {"role": "assistant", "content": "".join(content_parts)}
    if reasoning_parts:
        message["reasoning_content"] = "".join(reasoning_parts)
    if tool_calls_acc:
        message["tool_calls"] = [tool_calls_acc[key] for key in sorted(tool_calls_acc)]
    assembled: dict[str, Any] = {
        "id": response_id,
        "model": model_name,
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
        "streamed": True,
    }
    if usage:
        assembled["usage"] = usage
    _capture(
        capture,
        context,
        "llm.response.assembled_from_stream",
        json_transport_bytes(assembled),
        "application/json",
        {**metadata, "statusCode": 200},
    )
    return assembled
