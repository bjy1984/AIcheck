from __future__ import annotations

from dataclasses import dataclass

from apps.review_worker.raw_vault_relay import RawOutboxPayload, deliver_raw_payload
from libs.integrations.storage import StoredObjectVersion
from libs.raw_vault import sha256_bytes


@dataclass
class RecordingStorage:
    fail: bool = False
    wrong_hash: bool = False

    def __post_init__(self) -> None:
        self.calls: list[tuple[str, str, bytes, str]] = []

    def put_locked_bytes(
        self,
        bucket: str,
        object_name: str,
        data: bytes,
        *,
        content_type: str,
    ) -> StoredObjectVersion:
        self.calls.append((bucket, object_name, data, content_type))
        if self.fail:
            raise RuntimeError("minio unavailable")
        digest = sha256_bytes(b"different" if self.wrong_hash else data)
        return StoredObjectVersion(
            bucket=bucket,
            object_name=object_name,
            version_id="version-1",
            etag="etag-1",
            byte_length=len(data),
            sha256=digest,
            legal_hold=True,
        )


def outbox_payload() -> RawOutboxPayload:
    payload = b'{ "original": true }\n'
    return RawOutboxPayload(
        tenant_id="TENANT-A",
        event_id="RAWEVT-1",
        run_stream_id="RRUN-1",
        payload=payload,
        payload_hash=sha256_bytes(payload),
        object_bucket="agent-raw-vault",
        object_key="TENANT-A/RRUN-1/000001-RAWEVT-1.json",
        payload_media_type="application/json",
        attempts=0,
        lease_token="lease-1",
    )


def test_delivery_preserves_exact_bytes_and_returns_locked_version() -> None:
    storage = RecordingStorage()

    result = deliver_raw_payload(outbox_payload(), storage)

    assert storage.calls == [
        (
            "agent-raw-vault",
            "TENANT-A/RRUN-1/000001-RAWEVT-1.json",
            b'{ "original": true }\n',
            "application/json",
        )
    ]
    assert result.status == "archived"
    assert result.version_id == "version-1"
    assert result.payload_hash == outbox_payload().payload_hash
    assert result.legal_hold is True


def test_delivery_failure_schedules_retry_without_changing_payload() -> None:
    storage = RecordingStorage(fail=True)
    item = outbox_payload()

    result = deliver_raw_payload(item, storage)

    assert result.status == "retry_pending"
    assert result.error == "RuntimeError"
    assert item.payload == b'{ "original": true }\n'


def test_delivery_rejects_stored_hash_mismatch() -> None:
    result = deliver_raw_payload(outbox_payload(), RecordingStorage(wrong_hash=True))

    assert result.status == "hash_mismatch"
    assert result.error == "stored_payload_hash_mismatch"
