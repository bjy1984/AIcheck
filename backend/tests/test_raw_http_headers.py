"""发出去的 JSON 请求必须带 Content-Type。

2026-08-14 线上：模型链路配好、就绪检查全绿、密钥可用，实际调用 HTTP 415。

原因是这几个发送函数都用 `content=<bytes>` 而不是 `json=`（为了原样留痕），
httpx 只在 `json=` 时才自动补 Content-Type。DashScope 与 LiteLLM 都容忍缺头，
换到 DeepSeek 就直接拒。**能跑通不等于请求是对的**——不合规的请求发了很久，
只是一直遇到宽容的对端。
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from libs.integrations.raw_http_capture import (
    json_request_headers,
    post_json_with_raw_capture,
    post_json_with_raw_capture_async,
)


def test_补上默认的_content_type():
    resolved = json_request_headers({"Authorization": "Bearer sk-x"})
    assert resolved["Content-Type"] == "application/json"
    assert resolved["Authorization"] == "Bearer sk-x"


def test_调用方显式指定时以调用方为准():
    """有的接口要 multipart 或别的类型，不能被这层无条件覆盖。"""
    resolved = json_request_headers({"Content-Type": "application/x-ndjson"})
    assert resolved["Content-Type"] == "application/x-ndjson"


def test_空头也能用():
    assert json_request_headers({})["Content-Type"] == "application/json"


def _echo_transport() -> tuple[httpx.MockTransport, dict[str, Any]]:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["headers"] = dict(request.headers)
        seen["body"] = request.content
        return httpx.Response(200, json={"ok": True})

    return httpx.MockTransport(handler), seen


def test_同步发送真的带上了头():
    transport, seen = _echo_transport()
    with httpx.Client(transport=transport) as client:
        post_json_with_raw_capture(
            client,
            "https://api.example.com/chat/completions",
            headers={"Authorization": "Bearer sk-x"},
            payload={"model": "m", "messages": []},
            capture=None,
            context=None,
            provider="test",
            operation="chat.completions",
        )
    assert seen["headers"]["content-type"] == "application/json"
    # 留痕要的是真正上线的那串字节，不能因为补头就改成 httpx 自己序列化的版本
    assert seen["body"] == b'{"model":"m","messages":[]}'


@pytest.mark.asyncio
async def test_异步发送也带上了头():
    transport, seen = _echo_transport()
    async with httpx.AsyncClient(transport=transport) as client:
        await post_json_with_raw_capture_async(
            client,
            "https://api.example.com/chat/completions",
            headers={"Authorization": "Bearer sk-x"},
            payload={"model": "m", "messages": []},
            capture=None,
            context=None,
            provider="test",
            operation="chat.completions",
        )
    assert seen["headers"]["content-type"] == "application/json"
