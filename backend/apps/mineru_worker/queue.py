from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4


OCR_JOBS_COLLECTION = "ocr_jobs"


@dataclass(frozen=True)
class ClaimedMinerUJob:
    tenant_id: str
    job_id: str
    lease_token: str
    attempts: int


def utc_timestamp(value: datetime | None = None) -> str:
    return (value or datetime.now(timezone.utc)).isoformat()


def claim_jobs(
    dsn: str,
    worker_id: str,
    *,
    limit: int = 1,
    lease_seconds: int = 120,
) -> list[ClaimedMinerUJob]:
    """Lease due MinerU jobs without allowing two workers to own the same row."""

    import psycopg
    from psycopg.types.json import Jsonb

    bounded_limit = max(1, min(int(limit), 100))
    bounded_lease = max(5, int(lease_seconds))
    with psycopg.connect(dsn, autocommit=False) as connection:
        rows = connection.execute(
            """
            SELECT tenant_id, object_id, payload
            FROM aicheck_state
            WHERE collection = %s
              AND payload ->> 'provider' = 'mineru'
              AND payload ->> 'status' IN ('queued', 'running')
              AND (
                    payload ->> 'status' = 'queued'
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
            (OCR_JOBS_COLLECTION, bounded_limit),
        ).fetchall()
        claimed: list[ClaimedMinerUJob] = []
        for tenant_id, object_id, raw_payload in rows:
            lease_token = uuid4().hex
            now = datetime.now(timezone.utc)
            payload = dict(raw_payload)
            attempts = max(0, int(payload.get("attempts") or 0))
            payload.update(
                {
                    "status": "running",
                    "stage": "processing",
                    "workerId": worker_id,
                    "leaseToken": lease_token,
                    "leaseUntil": utc_timestamp(now + timedelta(seconds=bounded_lease)),
                    "lastAttemptAt": utc_timestamp(now),
                    "updatedAt": utc_timestamp(now),
                }
            )
            payload.pop("nextAttemptAt", None)
            connection.execute(
                """
                UPDATE aicheck_state
                SET payload = %s::jsonb, revision = revision + 1, updated_at = now()
                WHERE tenant_id = %s AND collection = %s AND object_id = %s
                """,
                (Jsonb(payload), str(tenant_id), OCR_JOBS_COLLECTION, str(object_id)),
            )
            claimed.append(
                ClaimedMinerUJob(
                    tenant_id=str(tenant_id),
                    job_id=str(object_id),
                    lease_token=lease_token,
                    attempts=attempts,
                )
            )
        connection.commit()
        return claimed


def finish_claim(dsn: str, claim: ClaimedMinerUJob) -> bool:
    """Release a claim only while its lease token is still current."""

    return _update_claim(dsn, claim, reschedule=None)


def reschedule_claim(
    dsn: str,
    claim: ClaimedMinerUJob,
    *,
    diagnostics: list[dict[str, Any]],
    delay_seconds: int,
) -> bool:
    """Return a failed claim to the queue after a bounded retry delay."""

    return _update_claim(
        dsn,
        claim,
        reschedule={
            "diagnostics": diagnostics,
            "delaySeconds": max(0, int(delay_seconds)),
        },
    )


def _update_claim(
    dsn: str,
    claim: ClaimedMinerUJob,
    *,
    reschedule: dict[str, Any] | None,
) -> bool:
    import psycopg
    from psycopg.types.json import Jsonb

    with psycopg.connect(dsn, autocommit=False) as connection:
        row = connection.execute(
            """
            SELECT payload
            FROM aicheck_state
            WHERE tenant_id = %s AND collection = %s AND object_id = %s
            FOR UPDATE
            """,
            (claim.tenant_id, OCR_JOBS_COLLECTION, claim.job_id),
        ).fetchone()
        if not row:
            connection.rollback()
            return False
        payload = dict(row[0])
        if str(payload.get("leaseToken") or "") != claim.lease_token:
            connection.rollback()
            return False
        now = datetime.now(timezone.utc)
        payload.pop("leaseToken", None)
        payload.pop("leaseUntil", None)
        payload.pop("workerId", None)
        payload["updatedAt"] = utc_timestamp(now)
        if reschedule is not None:
            payload.update(
                {
                    "status": "queued",
                    "stage": "retry_wait",
                    "attempts": claim.attempts + 1,
                    "diagnostics": list(reschedule["diagnostics"]),
                    "nextAttemptAt": utc_timestamp(
                        now + timedelta(seconds=int(reschedule["delaySeconds"]))
                    ),
                }
            )
        connection.execute(
            """
            UPDATE aicheck_state
            SET payload = %s::jsonb, revision = revision + 1, updated_at = now()
            WHERE tenant_id = %s AND collection = %s AND object_id = %s
            """,
            (Jsonb(payload), claim.tenant_id, OCR_JOBS_COLLECTION, claim.job_id),
        )
        connection.commit()
        return True


def write_heartbeat(dsn: str, worker_id: str, payload: dict[str, Any]) -> None:
    import psycopg
    from psycopg.types.json import Jsonb

    service_id = f"mineru-worker:{worker_id}"
    with psycopg.connect(dsn, autocommit=False) as connection:
        connection.execute(
            """
            INSERT INTO service_heartbeats (service_id, service_role, instance_id, payload, last_seen_at)
            VALUES (%s, 'mineru-worker', %s, %s::jsonb, now())
            ON CONFLICT (service_id)
            DO UPDATE SET
                service_role = EXCLUDED.service_role,
                instance_id = EXCLUDED.instance_id,
                payload = EXCLUDED.payload,
                last_seen_at = now()
            """,
            (service_id, worker_id, Jsonb(dict(payload))),
        )
        connection.commit()
