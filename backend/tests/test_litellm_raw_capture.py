from __future__ import annotations

import httpx
import pytest

from libs.integrations.errors import IntegrationServiceError
from libs.integrations.litellm_client import LiteLLMClient
from libs.raw_vault import InMemoryRawVaultStore, RawCapture, RawCaptureContext


def capture_fixture():
    store = InMemoryRawVaultStore()
    capture = RawCapture(store=store)
    context = RawCaptureContext("TENANT-A", "RRUN-RAW", review_run_id="RRUN-RAW")
    return store, capture, context


def test_sync_chat_captures_byte_exact_transport_bodies() -> None:
    sent: list[bytes] = []
    response_bytes = b'{"choices":[{"message":{"content":"\xe5\xae\x8c\xe6\x95\xb4"}}], "usage": {}}\n'

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request.content)
        return httpx.Response(200, content=response_bytes)

    store, capture, context = capture_fixture()
    client = LiteLLMClient(
        base_url="http://litellm.test",
        api_key="secret-not-archived",
        transport=httpx.MockTransport(handler),
        raw_capture=capture,
    )

    client.chat_sync([{"role": "user", "content": "中文"}], _raw_capture_context=context)

    events = store.events_for_run("TENANT-A", "RRUN-RAW")
    assert [event.event_type for event in events] == [
        "llm.request.prepared",
        "llm.response.received",
    ]
    assert store.payload_for(events[0].id) == sent[0]
    assert store.payload_for(events[1].id) == response_bytes
    assert b"secret-not-archived" not in store.payload_for(events[0].id)
    assert "Authorization" not in str(events[0].metadata)


def test_error_response_body_is_captured_before_raise() -> None:
    body = b' { "error": {"code": "rate_limit"} }\n'
    store, capture, context = capture_fixture()
    client = LiteLLMClient(
        base_url="http://litellm.test",
        api_key="secret",
        transport=httpx.MockTransport(lambda _request: httpx.Response(429, content=body)),
        raw_capture=capture,
    )

    with pytest.raises(IntegrationServiceError):
        client.chat_sync([], _raw_capture_context=context)

    events = store.events_for_run("TENANT-A", "RRUN-RAW")
    assert events[-1].event_type == "llm.response.error"
    assert store.payload_for(events[-1].id) == body


def test_transport_exception_is_captured_without_retrying() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("contains endpoint detail")

    store, capture, context = capture_fixture()
    client = LiteLLMClient(
        base_url="http://litellm.test",
        api_key="secret",
        transport=httpx.MockTransport(handler),
        raw_capture=capture,
    )
    with pytest.raises(IntegrationServiceError):
        client.chat_sync([], _raw_capture_context=context)

    events = store.events_for_run("TENANT-A", "RRUN-RAW")
    assert calls == 1
    assert events[-1].event_type == "llm.transport.error"
    assert b"ConnectError" in (store.payload_for(events[-1].id) or b"")
    assert b"endpoint detail" not in (store.payload_for(events[-1].id) or b"")
