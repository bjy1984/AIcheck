from __future__ import annotations

import hashlib
import io
import json
import os
from urllib.parse import parse_qs, urlparse

import pytest

from libs import audit_anchor
from libs.integrations.storage import ObjectStorage
from scripts.migrate_backend import apply_migrations

pytestmark = pytest.mark.skipif(
    not os.getenv("AICHECK_TEST_POSTGRES_URL") or not os.getenv("AICHECK_TEST_MINIO_ENDPOINT"),
    reason="AICHECK_TEST_POSTGRES_URL and AICHECK_TEST_MINIO_ENDPOINT are required",
)


def test_audit_anchor_records_and_preserves_exact_compliance_version(
    isolated_postgres_url: str,
    monkeypatch,
) -> None:
    import psycopg
    from minio.error import S3Error

    endpoint = os.environ["AICHECK_TEST_MINIO_ENDPOINT"]
    monkeypatch.setenv("AICHECK_MINIO_ENDPOINT", endpoint)
    monkeypatch.setenv("AICHECK_MINIO_PUBLIC_ENDPOINT", endpoint)
    monkeypatch.setenv(
        "AICHECK_MINIO_ACCESS_KEY",
        os.getenv("AICHECK_TEST_MINIO_ACCESS_KEY", "aicheck-probe"),
    )
    monkeypatch.setenv(
        "AICHECK_MINIO_SECRET_KEY",
        os.getenv("AICHECK_TEST_MINIO_SECRET_KEY", "AicheckProbeSecret-2026"),
    )
    monkeypatch.setenv("AICHECK_MINIO_SECURE", "false")
    monkeypatch.setenv("AICHECK_AUDIT_ANCHOR_OBJECT_LOCK", "true")
    monkeypatch.setenv("AICHECK_AUDIT_ANCHOR_RETENTION_DAYS", "1")
    bucket_prefix = os.getenv("AICHECK_TEST_MINIO_BUCKET_PREFIX", "aicheck-anchor-live")
    monkeypatch.setenv("AICHECK_MINIO_BUCKET_PREFIX", bucket_prefix)
    storage = ObjectStorage()
    monkeypatch.setattr(audit_anchor, "object_storage", storage)

    tenant_id = "TENANT-ANCHOR-LIVE"
    event_hash = "sha256:" + hashlib.sha256(b"audit-event-live").hexdigest()
    object_name = f"{tenant_id}/{1:020d}-{event_hash.removeprefix('sha256:')}.json"
    storage.ensure_buckets()
    client = storage.client()
    assert client is not None
    physical_bucket = storage.bucket_name("audit-anchors")
    physical_object_name = storage.object_name(object_name)
    if os.getenv("AICHECK_TEST_MINIO_EXPECT_EXISTING_ANCHOR", "false").lower() == "true":
        existing_versions = [
            item
            for item in client.list_objects(
                physical_bucket,
                prefix=physical_object_name,
                recursive=True,
                include_version=True,
            )
            if item.object_name == physical_object_name and item.version_id
        ]
        assert existing_versions
        retained_modes = []
        for item in existing_versions:
            retention = client.get_object_retention(
                physical_bucket,
                physical_object_name,
                version_id=item.version_id,
            )
            retained_modes.append(retention.mode if retention is not None else None)
        assert "COMPLIANCE" in retained_modes

    apply_migrations(isolated_postgres_url)
    with psycopg.connect(isolated_postgres_url, autocommit=False) as connection:
        connection.execute(
            """
            INSERT INTO audit_events (
                tenant_id, id, sequence, previous_hash, event_hash, payload
            ) VALUES (%s, 'AUD-ANCHOR-LIVE', 1, 'GENESIS', %s, %s::jsonb)
            """,
            (
                tenant_id,
                event_hash,
                psycopg.types.json.Jsonb(
                    {
                        "id": "AUD-ANCHOR-LIVE",
                        "tenantId": tenant_id,
                        "sequence": 1,
                        "previousHash": "GENESIS",
                        "eventHash": event_hash,
                    }
                ),
            ),
        )
        connection.commit()

    written = audit_anchor.write_pending_audit_anchors(isolated_postgres_url)
    assert len(written) == 1
    assert audit_anchor.write_pending_audit_anchors(isolated_postgres_url) == []
    sink_reference = str(written[0]["sinkReference"])
    parsed = urlparse(sink_reference)
    query = parse_qs(parsed.query)
    version_id = query["versionId"][0]
    assert query["etag"][0]

    with psycopg.connect(isolated_postgres_url, autocommit=False) as connection:
        persisted = connection.execute(
            """
            SELECT sink_reference FROM audit_chain_anchors
            WHERE tenant_id = %s AND head_sequence = 1
            """,
            (tenant_id,),
        ).fetchone()[0]
        assert persisted == sink_reference
        connection.rollback()

    bucket = parsed.netloc
    object_name = parsed.path.lstrip("/")
    retention = client.get_object_retention(bucket, object_name, version_id=version_id)
    assert retention is not None and retention.mode == "COMPLIANCE"
    response = client.get_object(bucket, object_name, version_id=version_id)
    try:
        envelope = json.loads(response.read())
    finally:
        response.close()
        response.release_conn()
    envelope_hash = envelope.pop("envelopeHash")
    canonical = json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode("utf-8")
    assert envelope_hash == "sha256:" + hashlib.sha256(canonical).hexdigest()
    assert envelope["headHash"] == event_hash

    with pytest.raises(S3Error):
        client.remove_object(bucket, object_name, version_id=version_id)

    replacement = client.put_object(
        bucket,
        object_name,
        io.BytesIO(b"replacement"),
        length=len(b"replacement"),
        content_type="application/json",
    )
    assert replacement.version_id != version_id
    response = client.get_object(bucket, object_name, version_id=version_id)
    try:
        original = json.loads(response.read())
    finally:
        response.close()
        response.release_conn()
    assert original["envelopeHash"] == envelope_hash
