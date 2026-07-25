from __future__ import annotations

from dataclasses import replace

from libs.raw_vault import (
    InMemoryRawVaultStore,
    RawCapture,
    RawCaptureContext,
    RawCaptureFailure,
    verify_event_chain,
)


def context() -> RawCaptureContext:
    return RawCaptureContext(
        tenant_id="TENANT-A",
        run_stream_id="RRUN-1",
        review_run_id="RRUN-1",
        project_id="P-1",
        stage="review_generate_findings",
    )


def test_capture_preserves_exact_bytes_and_chains_events() -> None:
    store = InMemoryRawVaultStore()
    capture = RawCapture(store=store)

    first = capture.capture_bytes(
        context(),
        "llm.request.prepared",
        b'{ "request": "\xe5\xae\x8c\xe6\x95\xb4" }\n',
        "application/json",
    )
    second = capture.capture_bytes(
        context(),
        "llm.response.received",
        b'{"ok":true, "spacing": 1}',
        "application/json",
    )

    assert store.payload_for(first.id) == b'{ "request": "\xe5\xae\x8c\xe6\x95\xb4" }\n'
    assert store.payload_for(second.id) == b'{"ok":true, "spacing": 1}'
    assert first.sequence == 1
    assert first.previous_event_hash == "GENESIS"
    assert second.sequence == 2
    assert second.previous_event_hash == first.event_hash
    assert second.object_key.endswith(f"000002-{second.id}.json")
    assert verify_event_chain(store.events_for_run("TENANT-A", "RRUN-1"), store.payload_for).status == "verified"


def test_metadata_event_participates_in_chain_without_outbox_payload() -> None:
    store = InMemoryRawVaultStore()
    capture = RawCapture(store=store)

    source = capture.capture_bytes(context(), "llm.response.received", b"raw", "application/octet-stream")
    receipt = capture.append_metadata_event(
        context(),
        "archive.payload.archived",
        {"sourceEventId": source.id, "objectVersionId": "version-1"},
    )

    assert receipt.has_payload is False
    assert receipt.payload_hash is None
    assert store.payload_for(receipt.id) is None
    assert store.pending_event_ids() == [source.id]
    assert verify_event_chain(store.events_for_run("TENANT-A", "RRUN-1"), store.payload_for).status == "verified"


def test_verifier_reports_modified_payload_and_broken_sequence() -> None:
    store = InMemoryRawVaultStore()
    capture = RawCapture(store=store)
    first = capture.capture_bytes(context(), "llm.request.prepared", b"request", "application/json")
    second = capture.capture_bytes(context(), "llm.response.received", b"response", "application/json")

    payload_result = verify_event_chain(
        store.events_for_run("TENANT-A", "RRUN-1"),
        lambda event_id: b"tampered" if event_id == second.id else store.payload_for(event_id),
    )
    assert payload_result.status == "hash_mismatch"
    assert payload_result.findings == [{"eventId": second.id, "reason": "payload_hash_mismatch"}]

    broken = [first, replace(second, sequence=3)]
    sequence_result = verify_event_chain(broken)
    assert sequence_result.status == "hash_mismatch"
    assert sequence_result.findings[0]["reason"] == "sequence_mismatch"


def test_capture_best_effort_returns_gap_without_repeating_operation() -> None:
    class FailingStore(InMemoryRawVaultStore):
        def append(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            raise RuntimeError("database unavailable")

    failures: list[dict[str, str]] = []
    capture = RawCapture(store=FailingStore(), failure_reporter=failures.append)

    result = capture.capture_best_effort(
        context(),
        "llm.request.prepared",
        b"request",
        "application/json",
    )

    assert isinstance(result, RawCaptureFailure)
    assert result.reason == "RuntimeError"
    assert result.event_type == "llm.request.prepared"
    assert failures == [
        {
            "eventType": "llm.request.prepared",
            "reason": "RuntimeError",
            "runStreamId": "RRUN-1",
            "tenantId": "TENANT-A",
        }
    ]
