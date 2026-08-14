from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor

import pytest

from apps.review_worker.outbox import (
    claim_pending_commands,
    finish_command,
    requeue_unapplied_deliveries,
)
from scripts.migrate_backend import apply_migrations

pytestmark = pytest.mark.skipif(
    not os.getenv("AICHECK_TEST_POSTGRES_URL"),
    reason="AICHECK_TEST_POSTGRES_URL is required for PostgreSQL outbox integration tests",
)


def insert_outbox(connection, *, tenant_id: str, command_id: str) -> None:
    from psycopg.types.json import Jsonb

    payload = {
        "id": command_id,
        "commandId": command_id,
        "tenantId": tenant_id,
        "reviewRunId": "RRUN-OUTBOX",
        "workflowId": "review-run-tenant-RRUN-OUTBOX",
        "commandType": "cancel_review",
        "payloadHash": f"sha256:{command_id}",
        "signalPayload": {"reasonHash": f"sha256:{command_id}"},
        "status": "pending",
        "attempts": 0,
    }
    connection.execute(
        """
        INSERT INTO aicheck_state (tenant_id, collection, object_id, payload)
        VALUES (%s, 'workflow_outbox', %s, %s)
        """,
        (tenant_id, command_id, Jsonb(payload)),
    )


def outbox_payload(connection, tenant_id: str, command_id: str) -> dict:
    return dict(
        connection.execute(
            """
            SELECT payload FROM aicheck_state
            WHERE tenant_id = %s AND collection = 'workflow_outbox' AND object_id = %s
            """,
            (tenant_id, command_id),
        ).fetchone()[0]
    )


def test_activity_commit_before_relay_finish_cannot_downgrade_applied(
    isolated_postgres_url: str,
) -> None:
    import psycopg
    from psycopg.types.json import Jsonb

    apply_migrations(isolated_postgres_url)
    tenant_id = "TENANT-OUTBOX-RACE"
    command_id = "WFCMD-APPLIED-FIRST"
    with psycopg.connect(isolated_postgres_url, autocommit=False) as connection:
        insert_outbox(connection, tenant_id=tenant_id, command_id=command_id)
        connection.commit()
    claimed = claim_pending_commands(isolated_postgres_url, limit=1)
    assert len(claimed) == 1

    with psycopg.connect(isolated_postgres_url, autocommit=False) as connection:
        payload = outbox_payload(connection, tenant_id, command_id)
        payload["status"] = "applied"
        payload["appliedAt"] = "2026-07-13T00:00:00+00:00"
        # Keep the relay lease to reproduce the historical applied -> delivered race exactly.
        connection.execute(
            """
            UPDATE aicheck_state SET payload = %s, updated_at = now()
            WHERE tenant_id = %s AND collection = 'workflow_outbox' AND object_id = %s
            """,
            (Jsonb(payload), tenant_id, command_id),
        )
        connection.execute(
            """
            INSERT INTO aicheck_state (tenant_id, collection, object_id, payload)
            VALUES (%s, 'workflow_inbox', %s, %s)
            """,
            (
                tenant_id,
                command_id,
                Jsonb({"id": command_id, "commandId": command_id, "status": "applied"}),
            ),
        )
        connection.commit()

    finish_command(isolated_postgres_url, claimed[0], delivered=True)

    with psycopg.connect(isolated_postgres_url, autocommit=False) as connection:
        payload = outbox_payload(connection, tenant_id, command_id)
        assert payload["status"] == "applied"
        assert payload["attempts"] == 0
        assert "leaseToken" not in payload
        assert "leaseUntil" not in payload
        connection.rollback()


def test_delivered_without_inbox_is_requeued_for_redelivery(
    isolated_postgres_url: str,
    monkeypatch,
) -> None:
    import psycopg

    apply_migrations(isolated_postgres_url)
    tenant_id = "TENANT-OUTBOX-RECONCILE"
    command_id = "WFCMD-DELIVERED-NO-INBOX"
    with psycopg.connect(isolated_postgres_url, autocommit=False) as connection:
        insert_outbox(connection, tenant_id=tenant_id, command_id=command_id)
        connection.commit()
    claimed = claim_pending_commands(isolated_postgres_url, limit=1)
    finish_command(isolated_postgres_url, claimed[0], delivered=True)
    with psycopg.connect(isolated_postgres_url, autocommit=False) as connection:
        connection.execute(
            """
            UPDATE aicheck_state SET updated_at = now() - interval '30 seconds'
            WHERE tenant_id = %s AND collection = 'workflow_outbox' AND object_id = %s
            """,
            (tenant_id, command_id),
        )
        connection.commit()
    monkeypatch.setenv("AICHECK_OUTBOX_RECONCILE_SECONDS", "10")

    assert requeue_unapplied_deliveries(isolated_postgres_url) == 1

    with psycopg.connect(isolated_postgres_url, autocommit=False) as connection:
        payload = outbox_payload(connection, tenant_id, command_id)
        assert payload["status"] == "retry_pending"
        assert payload["reconciliationCount"] == 1
        assert payload["lastReconciliationReason"] == "delivered_without_durable_inbox"
        connection.rollback()


def test_two_relays_claim_each_command_at_most_once(isolated_postgres_url: str) -> None:
    import psycopg

    apply_migrations(isolated_postgres_url)
    tenant_id = "TENANT-OUTBOX-CLAIM"
    command_ids = [f"WFCMD-CLAIM-{index}" for index in range(10)]
    with psycopg.connect(isolated_postgres_url, autocommit=False) as connection:
        for command_id in command_ids:
            insert_outbox(connection, tenant_id=tenant_id, command_id=command_id)
        connection.commit()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(claim_pending_commands, isolated_postgres_url, limit=6)
            for _ in range(2)
        ]
        claimed = [command for future in futures for command in future.result(timeout=5)]

    claimed_ids = [str(command["commandId"]) for command in claimed]
    assert sorted(claimed_ids) == sorted(command_ids)
    assert len(claimed_ids) == len(set(claimed_ids))
