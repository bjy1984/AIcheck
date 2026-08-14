from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from libs.integrations.storage import ObjectStorage, object_storage
from libs.raw_vault import (
    DEFAULT_RAW_VAULT_BUCKET,
    GENESIS_HASH,
    RawCaptureContext,
    _event_without_hash,
    utc_timestamp,
)


@dataclass(frozen=True)
class RawOutboxPayload:
    tenant_id: str
    event_id: str
    run_stream_id: str
    payload: bytes
    payload_hash: str
    object_bucket: str
    object_key: str
    payload_media_type: str
    attempts: int
    lease_token: str


@dataclass(frozen=True)
class RawDeliveryResult:
    status: str
    payload_hash: str
    version_id: str | None = None
    etag: str | None = None
    legal_hold: bool = False
    error: str | None = None


def deliver_raw_payload(
    item: RawOutboxPayload,
    storage: ObjectStorage = object_storage,
) -> RawDeliveryResult:
    try:
        stored = storage.put_locked_bytes(
            item.object_bucket,
            item.object_key,
            item.payload,
            content_type=item.payload_media_type,
        )
    except Exception as exc:
        return RawDeliveryResult(
            status="retry_pending",
            payload_hash=item.payload_hash,
            error=type(exc).__name__,
        )
    if (
        stored.sha256 != item.payload_hash
        or stored.byte_length != len(item.payload)
        or not stored.legal_hold
    ):
        return RawDeliveryResult(
            status="hash_mismatch",
            payload_hash=item.payload_hash,
            version_id=stored.version_id,
            etag=stored.etag,
            legal_hold=stored.legal_hold,
            error="stored_payload_hash_mismatch",
        )
    return RawDeliveryResult(
        status="archived",
        payload_hash=stored.sha256,
        version_id=stored.version_id,
        etag=stored.etag,
        legal_hold=stored.legal_hold,
    )


def claim_pending_raw_payloads(dsn: str, *, limit: int = 20) -> list[RawOutboxPayload]:
    import psycopg

    lease_token = uuid4().hex
    lease_until = datetime.now(UTC) + timedelta(seconds=60)
    with psycopg.connect(dsn, autocommit=False) as connection:
        rows = connection.execute(
            """
            SELECT o.tenant_id, o.event_id, o.run_stream_id, o.payload, o.payload_hash,
                   o.object_bucket, o.object_key, e.payload_media_type, o.attempts
            FROM raw_vault_outbox AS o
            JOIN raw_vault_events AS e
              ON e.tenant_id = o.tenant_id AND e.id = o.event_id
            WHERE o.status IN ('pending', 'retry_pending', 'delivering')
              AND (o.status <> 'delivering' OR o.lease_until <= now())
              AND (o.next_attempt_at IS NULL OR o.next_attempt_at <= now())
            ORDER BY o.created_at, o.event_id
            FOR UPDATE OF o SKIP LOCKED
            LIMIT %s
            """,
            (max(1, min(limit, 100)),),
        ).fetchall()
        claimed: list[RawOutboxPayload] = []
        for row in rows:
            connection.execute(
                """
                UPDATE raw_vault_outbox
                SET status = 'delivering', lease_token = %s, lease_until = %s, updated_at = now()
                WHERE tenant_id = %s AND event_id = %s
                """,
                (lease_token, lease_until, str(row[0]), str(row[1])),
            )
            claimed.append(
                RawOutboxPayload(
                    tenant_id=str(row[0]),
                    event_id=str(row[1]),
                    run_stream_id=str(row[2]),
                    payload=bytes(row[3]),
                    payload_hash=str(row[4]),
                    object_bucket=str(row[5]),
                    object_key=str(row[6]),
                    payload_media_type=str(row[7] or "application/octet-stream"),
                    attempts=int(row[8] or 0),
                    lease_token=lease_token,
                )
            )
        connection.commit()
        return claimed


def _append_receipt(
    connection,
    item: RawOutboxPayload,
    result: RawDeliveryResult,
) -> None:
    from psycopg.types.json import Jsonb

    connection.execute(
        "SELECT pg_advisory_xact_lock(hashtext(%s))",
        (f"aicheck:raw-vault:{item.tenant_id}:{item.run_stream_id}",),
    )
    head = connection.execute(
        """
        SELECT sequence, event_hash
        FROM raw_vault_events
        WHERE tenant_id = %s AND run_stream_id = %s
        ORDER BY sequence DESC LIMIT 1
        """,
        (item.tenant_id, item.run_stream_id),
    ).fetchone()
    sequence = int(head[0]) + 1 if head else 1
    context_row = connection.execute(
        """
        SELECT project_id, review_run_id, ai_run_id, model_call_attempt_id, stage, turn
        FROM raw_vault_events
        WHERE tenant_id = %s AND id = %s
        """,
        (item.tenant_id, item.event_id),
    ).fetchone()
    if context_row is None:
        return
    event_type = (
        "archive.payload.archived"
        if result.status == "archived"
        else "archive.payload.hash_mismatch"
    )
    metadata = {
        "sourceEventId": item.event_id,
        "payloadHash": item.payload_hash,
        "objectBucket": item.object_bucket,
        "objectKey": item.object_key,
        "versionId": result.version_id,
        "etag": result.etag,
        "legalHold": result.legal_hold,
        "status": result.status,
    }
    event = _event_without_hash(
        RawCaptureContext(
            tenant_id=item.tenant_id,
            run_stream_id=item.run_stream_id,
            project_id=context_row[0],
            review_run_id=context_row[1],
            ai_run_id=context_row[2],
            model_call_attempt_id=context_row[3],
            stage=context_row[4],
            turn=context_row[5],
        ),
        event_id=f"RAWEVT-{uuid4().hex[:16].upper()}",
        event_type=event_type,
        sequence=sequence,
        previous_event_hash=str(head[1]) if head else GENESIS_HASH,
        metadata=metadata,
        created_at=utc_timestamp(),
        payload=None,
        media_type=None,
        bucket=DEFAULT_RAW_VAULT_BUCKET,
    )
    connection.execute(
        """
        INSERT INTO raw_vault_events (
          tenant_id, id, run_stream_id, project_id, review_run_id, ai_run_id,
          model_call_attempt_id, provider_tool_call_id, stage, event_type, turn,
          sequence, has_payload, payload_media_type, payload_byte_length, payload_hash,
          object_bucket, object_key, previous_event_hash, event_hash, metadata, created_at
        ) VALUES (
          %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,false,NULL,NULL,NULL,NULL,NULL,%s,%s,%s::jsonb,%s
        )
        """,
        (
            event.tenant_id, event.id, event.run_stream_id, event.project_id,
            event.review_run_id, event.ai_run_id, event.model_call_attempt_id,
            event.provider_tool_call_id, event.stage, event.event_type, event.turn,
            event.sequence, event.previous_event_hash, event.event_hash,
            Jsonb(event.metadata), event.created_at,
        ),
    )


def finish_raw_payload(dsn: str, item: RawOutboxPayload, result: RawDeliveryResult) -> None:
    import psycopg

    with psycopg.connect(dsn, autocommit=False) as connection:
        row = connection.execute(
            """
            SELECT status, lease_token, attempts
            FROM raw_vault_outbox
            WHERE tenant_id = %s AND event_id = %s
            FOR UPDATE
            """,
            (item.tenant_id, item.event_id),
        ).fetchone()
        if row is None or str(row[0]) != "delivering" or str(row[1] or "") != item.lease_token:
            connection.rollback()
            return
        attempts = int(row[2] or 0) + 1
        if result.status in {"archived", "hash_mismatch"}:
            _append_receipt(connection, item, result)
            if result.status == "archived":
                connection.execute(
                    "DELETE FROM raw_vault_outbox WHERE tenant_id = %s AND event_id = %s",
                    (item.tenant_id, item.event_id),
                )
            else:
                connection.execute(
                    """
                    UPDATE raw_vault_outbox
                    SET status = 'hash_mismatch', attempts = %s, lease_token = NULL,
                        lease_until = NULL, last_error = %s, updated_at = now()
                    WHERE tenant_id = %s AND event_id = %s
                    """,
                    (attempts, result.error, item.tenant_id, item.event_id),
                )
        else:
            delay = min(300, 2 ** min(attempts, 8))
            connection.execute(
                """
                UPDATE raw_vault_outbox
                SET status = 'retry_pending', attempts = %s, lease_token = NULL,
                    lease_until = NULL, next_attempt_at = now() + make_interval(secs => %s),
                    last_error = %s, updated_at = now()
                WHERE tenant_id = %s AND event_id = %s
                """,
                (attempts, delay, result.error, item.tenant_id, item.event_id),
            )
        connection.commit()


async def run_raw_vault_relay() -> None:
    dsn = os.getenv("AICHECK_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not dsn:
        return
    poll_seconds = max(0.25, float(os.getenv("AICHECK_RAW_VAULT_POLL_SECONDS", "1")))
    batch_size = max(1, int(os.getenv("AICHECK_RAW_VAULT_BATCH_SIZE", "20")))
    while True:
        items = await asyncio.to_thread(claim_pending_raw_payloads, dsn, limit=batch_size)
        for item in items:
            result = await asyncio.to_thread(deliver_raw_payload, item)
            await asyncio.to_thread(finish_raw_payload, dsn, item, result)
        await asyncio.sleep(poll_seconds if not items else 0)
