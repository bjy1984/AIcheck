from __future__ import annotations

import asyncio
import os
import socket
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from temporalio.client import Client

from libs.audit_anchor import write_pending_audit_anchors


OUTBOX_COLLECTION = "workflow_outbox"
COMMAND_SIGNALS = {
    "submit_human_input": "submit_human_input",
    "submit_human_decision": "submit_human_decision",
    "cancel_review": "cancel_review",
}


def database_url() -> str | None:
    return os.getenv("AICHECK_DATABASE_URL") or os.getenv("DATABASE_URL")


def utc_timestamp(value: datetime | None = None) -> str:
    return (value or datetime.now(timezone.utc)).isoformat()


def finalized_command_payload(
    raw_payload: dict[str, Any],
    *,
    lease_token: str,
    delivered: bool,
    inbox_exists: bool = False,
    error: str | None = None,
) -> dict[str, Any] | None:
    """Apply a relay result without ever downgrading an activity-applied command."""

    payload = dict(raw_payload)
    status = str(payload.get("status") or "")
    if status == "applied" or inbox_exists:
        payload["status"] = "applied"
        payload.setdefault("appliedAt", utc_timestamp())
        payload["updatedAt"] = payload["appliedAt"]
        payload.pop("leaseToken", None)
        payload.pop("leaseUntil", None)
        return payload
    if status != "delivering" or str(payload.get("leaseToken") or "") != lease_token:
        return None
    attempts = int(payload.get("attempts") or 0) + 1
    payload["attempts"] = attempts
    payload["updatedAt"] = utc_timestamp()
    payload.pop("leaseToken", None)
    payload.pop("leaseUntil", None)
    if delivered:
        payload["status"] = "delivered"
        payload["deliveredAt"] = payload["updatedAt"]
        payload.pop("nextAttemptAt", None)
        payload.pop("lastError", None)
    else:
        maximum_attempts = max(1, int(os.getenv("AICHECK_OUTBOX_MAX_ATTEMPTS", "10")))
        payload["status"] = "dead_letter" if attempts >= maximum_attempts else "retry_pending"
        payload["lastError"] = str(error or "Temporal signal failed")[:2000]
        if payload["status"] == "retry_pending":
            delay = min(300, 2 ** min(attempts, 8))
            payload["nextAttemptAt"] = utc_timestamp(datetime.now(timezone.utc) + timedelta(seconds=delay))
        else:
            payload["deadLetteredAt"] = payload["updatedAt"]
            payload.pop("nextAttemptAt", None)
    return payload


def claim_pending_commands(dsn: str, *, limit: int = 20) -> list[dict[str, Any]]:
    """Lease pending commands with SKIP LOCKED so multiple relays may run safely."""

    import psycopg

    lease_token = uuid4().hex
    lease_until = utc_timestamp(datetime.now(timezone.utc) + timedelta(seconds=60))
    with psycopg.connect(dsn, autocommit=False) as connection:
        rows = connection.execute(
            """
            SELECT tenant_id, object_id, payload
            FROM aicheck_state
            WHERE collection = %s
              AND payload ->> 'status' IN ('pending', 'retry_pending', 'delivering')
              AND (
                    payload ->> 'status' <> 'delivering'
                    OR NULLIF(payload ->> 'leaseUntil', '')::timestamptz <= now()
                  )
              AND (
                    NULLIF(payload ->> 'nextAttemptAt', '') IS NULL
                    OR NULLIF(payload ->> 'nextAttemptAt', '')::timestamptz <= now()
                  )
            ORDER BY updated_at, object_id
            FOR UPDATE SKIP LOCKED
            LIMIT %s
            """,
            (OUTBOX_COLLECTION, max(1, min(limit, 100))),
        ).fetchall()
        claimed: list[dict[str, Any]] = []
        for tenant_id, object_id, payload in rows:
            command = dict(payload)
            command.update(
                {
                    "status": "delivering",
                    "leaseToken": lease_token,
                    "leaseUntil": lease_until,
                    "updatedAt": utc_timestamp(),
                }
            )
            connection.execute(
                """
                UPDATE aicheck_state
                SET payload = %s::jsonb, revision = revision + 1, updated_at = now()
                WHERE tenant_id = %s AND collection = %s AND object_id = %s
                """,
                (psycopg.types.json.Jsonb(command), str(tenant_id), OUTBOX_COLLECTION, str(object_id)),
            )
            claimed.append({"tenantId": str(tenant_id), "objectId": str(object_id), **command})
        connection.commit()
        return claimed


def finish_command(
    dsn: str,
    command: dict[str, Any],
    *,
    delivered: bool,
    error: str | None = None,
) -> None:
    import psycopg

    tenant_id = str(command["tenantId"])
    object_id = str(command["objectId"])
    lease_token = str(command.get("leaseToken") or "")
    with psycopg.connect(dsn, autocommit=False) as connection:
        row = connection.execute(
            """
            SELECT payload
            FROM aicheck_state
            WHERE tenant_id = %s AND collection = %s AND object_id = %s
            FOR UPDATE
            """,
            (tenant_id, OUTBOX_COLLECTION, object_id),
        ).fetchone()
        if not row:
            connection.rollback()
            return
        raw_payload = dict(row[0])
        inbox_exists = False
        if str(raw_payload.get("status") or "") != "applied":
            inbox_exists = bool(
                connection.execute(
                    """
                    SELECT 1
                    FROM aicheck_state
                    WHERE tenant_id = %s AND collection = 'workflow_inbox' AND object_id = %s
                    """,
                    (tenant_id, object_id),
                ).fetchone()
            )
        payload = finalized_command_payload(
            raw_payload,
            lease_token=lease_token,
            delivered=delivered,
            inbox_exists=inbox_exists,
            error=error,
        )
        if payload is None:
            connection.rollback()
            return
        connection.execute(
            """
            UPDATE aicheck_state
            SET payload = %s::jsonb, revision = revision + 1, updated_at = now()
            WHERE tenant_id = %s AND collection = %s AND object_id = %s
            """,
            (psycopg.types.json.Jsonb(payload), tenant_id, OUTBOX_COLLECTION, object_id),
        )
        connection.commit()


def requeue_unapplied_deliveries(dsn: str, *, limit: int = 50) -> int:
    """Re-deliver commands that were signalled but never produced a durable inbox record."""

    import psycopg

    grace_seconds = max(10, int(os.getenv("AICHECK_OUTBOX_RECONCILE_SECONDS", "120")))
    maximum_reconciliations = max(1, int(os.getenv("AICHECK_OUTBOX_MAX_RECONCILIATIONS", "5")))
    with psycopg.connect(dsn, autocommit=False) as connection:
        rows = connection.execute(
            """
            SELECT outbox.tenant_id, outbox.object_id, outbox.payload
            FROM aicheck_state AS outbox
            WHERE outbox.collection = %s
              AND outbox.payload ->> 'status' = 'delivered'
              AND outbox.updated_at <= now() - make_interval(secs => %s)
              AND COALESCE((outbox.payload ->> 'reconciliationCount')::integer, 0) < %s
              AND NOT EXISTS (
                    SELECT 1
                    FROM aicheck_state AS inbox
                    WHERE inbox.tenant_id = outbox.tenant_id
                      AND inbox.collection = 'workflow_inbox'
                      AND inbox.object_id = outbox.object_id
                  )
            ORDER BY outbox.updated_at, outbox.object_id
            FOR UPDATE OF outbox SKIP LOCKED
            LIMIT %s
            """,
            (OUTBOX_COLLECTION, grace_seconds, maximum_reconciliations, max(1, min(limit, 200))),
        ).fetchall()
        for tenant_id, object_id, raw_payload in rows:
            payload = dict(raw_payload)
            payload["status"] = "retry_pending"
            payload["nextAttemptAt"] = utc_timestamp()
            payload["updatedAt"] = payload["nextAttemptAt"]
            payload["reconciliationCount"] = int(payload.get("reconciliationCount") or 0) + 1
            payload["lastReconciliationReason"] = "delivered_without_durable_inbox"
            connection.execute(
                """
                UPDATE aicheck_state
                SET payload = %s::jsonb, revision = revision + 1, updated_at = now()
                WHERE tenant_id = %s AND collection = %s AND object_id = %s
                """,
                (psycopg.types.json.Jsonb(payload), str(tenant_id), OUTBOX_COLLECTION, str(object_id)),
            )
        connection.commit()
        return len(rows)


async def deliver_command(client: Client, command: dict[str, Any]) -> None:
    command_type = str(command.get("commandType") or "")
    signal_name = COMMAND_SIGNALS.get(command_type)
    if not signal_name:
        raise ValueError(f"Unsupported ReviewRun workflow command: {command_type}")
    workflow_id = str(command.get("workflowId") or f"review-run-{command.get('reviewRunId')}")
    signal_payload = {
        "commandId": command.get("commandId") or command.get("objectId"),
        "commandType": command_type,
        "tenantId": command.get("tenantId"),
        "reviewRunId": command.get("reviewRunId"),
        "payloadHash": command.get("payloadHash"),
    }
    await client.get_workflow_handle(workflow_id).signal(signal_name, signal_payload)


async def run_outbox_relay(client: Client) -> None:
    dsn = database_url()
    if not dsn:
        return
    interval = max(0.2, float(os.getenv("AICHECK_OUTBOX_POLL_SECONDS", "1")))
    batch_size = max(1, int(os.getenv("AICHECK_OUTBOX_BATCH_SIZE", "20")))
    while True:
        await asyncio.to_thread(requeue_unapplied_deliveries, dsn, limit=batch_size * 2)
        commands = await asyncio.to_thread(claim_pending_commands, dsn, limit=batch_size)
        for command in commands:
            try:
                await deliver_command(client, command)
            except Exception as exc:
                await asyncio.to_thread(finish_command, dsn, command, delivered=False, error=str(exc))
            else:
                await asyncio.to_thread(finish_command, dsn, command, delivered=True)
        await asyncio.sleep(interval if not commands else 0)


async def run_audit_anchor_loop() -> None:
    dsn = database_url()
    if not dsn:
        return
    interval = max(30, int(os.getenv("AICHECK_AUDIT_ANCHOR_INTERVAL_SECONDS", "300")))
    while True:
        await asyncio.to_thread(write_pending_audit_anchors, dsn)
        await asyncio.sleep(interval)


def write_worker_heartbeat(dsn: str) -> None:
    import psycopg

    instance_id = os.getenv("HOSTNAME") or socket.gethostname()
    service_id = f"review-worker:{instance_id}"
    payload = {
        "taskQueue": os.getenv("AICHECK_REVIEW_WORKFLOW_TASK_QUEUE", "review.workflow"),
        "outboxRelay": True,
        "auditAnchorWriter": True,
        "rawVaultRelay": True,
    }
    with psycopg.connect(dsn, autocommit=False) as connection:
        connection.execute(
            """
            INSERT INTO service_heartbeats (service_id, service_role, instance_id, payload, last_seen_at)
            VALUES (%s, 'review-worker', %s, %s::jsonb, now())
            ON CONFLICT (service_id)
            DO UPDATE SET payload = EXCLUDED.payload, instance_id = EXCLUDED.instance_id, last_seen_at = now()
            """,
            (service_id, instance_id, psycopg.types.json.Jsonb(payload)),
        )
        connection.commit()


async def run_worker_heartbeat_loop() -> None:
    dsn = database_url()
    if not dsn:
        return
    interval = max(5, int(os.getenv("AICHECK_WORKER_HEARTBEAT_SECONDS", "10")))
    while True:
        await asyncio.to_thread(write_worker_heartbeat, dsn)
        await asyncio.sleep(interval)
