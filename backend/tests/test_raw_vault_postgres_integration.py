from __future__ import annotations

import os

import pytest

from libs.raw_vault import PostgresRawVaultStore, RawCapture, RawCaptureContext
from scripts.migrate_backend import apply_migrations


POSTGRES_URL = os.getenv("AICHECK_TEST_POSTGRES_URL")


@pytest.mark.skipif(not POSTGRES_URL, reason="AICHECK_TEST_POSTGRES_URL is required")
def test_postgres_capture_commits_event_and_outbox_atomically(isolated_postgres_url: str) -> None:
    import psycopg

    apply_migrations(isolated_postgres_url)
    capture = RawCapture(store=PostgresRawVaultStore(isolated_postgres_url))
    context = RawCaptureContext(
        tenant_id="TENANT-RAW",
        run_stream_id="RRUN-RAW",
        review_run_id="RRUN-RAW",
    )

    event = capture.capture_bytes(
        context,
        "llm.request.prepared",
        b'{"model":"review-chat"}',
        "application/json",
    )

    with psycopg.connect(isolated_postgres_url, autocommit=True) as connection:
        stored_event = connection.execute(
            "SELECT sequence, payload_hash FROM raw_vault_events WHERE tenant_id=%s AND id=%s",
            ("TENANT-RAW", event.id),
        ).fetchone()
        stored_outbox = connection.execute(
            "SELECT payload, payload_hash FROM raw_vault_outbox WHERE tenant_id=%s AND event_id=%s",
            ("TENANT-RAW", event.id),
        ).fetchone()
    assert stored_event == (1, event.payload_hash)
    assert bytes(stored_outbox[0]) == b'{"model":"review-chat"}'
    assert stored_outbox[1] == event.payload_hash


@pytest.mark.skipif(not POSTGRES_URL, reason="AICHECK_TEST_POSTGRES_URL is required")
def test_postgres_metadata_event_does_not_create_outbox_row(isolated_postgres_url: str) -> None:
    import psycopg

    apply_migrations(isolated_postgres_url)
    capture = RawCapture(store=PostgresRawVaultStore(isolated_postgres_url))
    context = RawCaptureContext(tenant_id="TENANT-RAW", run_stream_id="RRUN-RAW")

    event = capture.append_metadata_event(context, "run.archive.incomplete", {"pendingCount": 1})

    with psycopg.connect(isolated_postgres_url, autocommit=True) as connection:
        count = connection.execute(
            "SELECT count(*) FROM raw_vault_outbox WHERE tenant_id=%s AND event_id=%s",
            ("TENANT-RAW", event.id),
        ).fetchone()[0]
    assert count == 0
