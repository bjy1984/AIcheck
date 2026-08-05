from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4


OCR_JOBS_COLLECTION = "ocr_jobs"
KNOWLEDGE_TASKS_COLLECTION = "knowledge_tasks"


@dataclass(frozen=True)
class ClaimedMinerUJob:
    tenant_id: str
    job_id: str
    lease_token: str
    attempts: int


@dataclass(frozen=True)
class ClaimedKnowledgeTask:
    tenant_id: str
    task_id: str
    task_type: str
    target_id: str
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


def claim_knowledge_tasks(
    dsn: str,
    worker_id: str,
    *,
    limit: int = 1,
    lease_seconds: int = 120,
) -> list[ClaimedKnowledgeTask]:
    """Lease due slice/vector tasks while enforcing slice-before-vector order."""

    import psycopg
    from psycopg.types.json import Jsonb

    bounded_limit = max(1, min(int(limit), 100))
    bounded_lease = max(5, int(lease_seconds))
    with psycopg.connect(dsn, autocommit=False) as connection:
        rows = connection.execute(
            """
            SELECT task.tenant_id, task.object_id, task.payload
            FROM aicheck_state AS task
            WHERE task.collection = %s
              AND task.payload ->> 'taskType' IN ('slice', 'vector')
              AND task.payload ->> 'status' IN ('排队中', '执行中', '运行中')
              AND (
                    task.payload ->> 'status' = '排队中'
                    OR NULLIF(task.payload ->> 'leaseUntil', '')::timestamptz <= now()
                  )
              AND (
                    NULLIF(task.payload ->> 'nextAttemptAt', '') IS NULL
                    OR NULLIF(task.payload ->> 'nextAttemptAt', '')::timestamptz <= now()
                  )
              AND (
                    task.payload ->> 'taskType' = 'slice'
                    OR EXISTS (
                        SELECT 1
                        FROM aicheck_state AS dependency
                        WHERE dependency.tenant_id = task.tenant_id
                          AND dependency.collection = %s
                          AND dependency.payload ->> 'taskType' = 'slice'
                          AND dependency.payload ->> 'targetId' = task.payload ->> 'targetId'
                          AND dependency.payload ->> 'status' = '成功'
                    )
                    OR EXISTS (
                        SELECT 1
                        FROM aicheck_state AS knowledge_file
                        WHERE knowledge_file.tenant_id = task.tenant_id
                          AND knowledge_file.collection = 'knowledge_files'
                          AND knowledge_file.object_id = task.payload ->> 'targetId'
                          AND knowledge_file.payload ->> 'sliceStatus' = '已切片'
                    )
                  )
            ORDER BY
                CASE task.payload ->> 'taskType' WHEN 'slice' THEN 0 ELSE 1 END,
                task.updated_at,
                task.object_id
            FOR UPDATE OF task SKIP LOCKED
            LIMIT %s
            """,
            (KNOWLEDGE_TASKS_COLLECTION, KNOWLEDGE_TASKS_COLLECTION, bounded_limit),
        ).fetchall()
        claimed: list[ClaimedKnowledgeTask] = []
        for tenant_id, object_id, raw_payload in rows:
            lease_token = uuid4().hex
            now = datetime.now(timezone.utc)
            payload = dict(raw_payload)
            attempts = max(0, int(payload.get("attempts") or 0))
            task_type = str(payload.get("taskType") or "")
            target_id = str(payload.get("targetId") or "")
            payload.update(
                {
                    "status": "执行中",
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
                (Jsonb(payload), str(tenant_id), KNOWLEDGE_TASKS_COLLECTION, str(object_id)),
            )
            active_status = "切片中" if task_type == "slice" else "向量化中"
            status_field = "sliceStatus" if task_type == "slice" else "vectorStatus"
            connection.execute(
                """
                UPDATE aicheck_state
                SET payload = jsonb_set(payload, %s, to_jsonb(%s::text), true),
                    revision = revision + 1,
                    updated_at = now()
                WHERE tenant_id = %s AND collection = 'knowledge_files' AND object_id = %s
                """,
                ([status_field], active_status, str(tenant_id), target_id),
            )
            claimed.append(
                ClaimedKnowledgeTask(
                    tenant_id=str(tenant_id),
                    task_id=str(object_id),
                    task_type=task_type,
                    target_id=target_id,
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


def finish_knowledge_claim(dsn: str, claim: ClaimedKnowledgeTask) -> bool:
    return _update_knowledge_claim(dsn, claim, reschedule=None)


def reschedule_knowledge_claim(
    dsn: str,
    claim: ClaimedKnowledgeTask,
    *,
    error_message: str,
    delay_seconds: int,
) -> bool:
    return _update_knowledge_claim(
        dsn,
        claim,
        reschedule={
            "errorMessage": str(error_message),
            "delaySeconds": max(0, int(delay_seconds)),
        },
    )


def fail_knowledge_claim(
    dsn: str,
    claim: ClaimedKnowledgeTask,
    *,
    error_message: str,
) -> bool:
    return _update_knowledge_claim(
        dsn,
        claim,
        reschedule={
            "errorMessage": str(error_message),
            "terminal": True,
        },
    )


def _update_knowledge_claim(
    dsn: str,
    claim: ClaimedKnowledgeTask,
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
            (claim.tenant_id, KNOWLEDGE_TASKS_COLLECTION, claim.task_id),
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
            terminal = bool(reschedule.get("terminal"))
            payload.update(
                {
                    "status": "失败" if terminal else "排队中",
                    "attempts": claim.attempts + 1,
                    "errorMessage": str(reschedule["errorMessage"]),
                }
            )
            if terminal:
                payload.pop("nextAttemptAt", None)
            else:
                payload["nextAttemptAt"] = utc_timestamp(
                    now + timedelta(seconds=int(reschedule["delaySeconds"]))
                )
        connection.execute(
            """
            UPDATE aicheck_state
            SET payload = %s::jsonb, revision = revision + 1, updated_at = now()
            WHERE tenant_id = %s AND collection = %s AND object_id = %s
            """,
            (Jsonb(payload), claim.tenant_id, KNOWLEDGE_TASKS_COLLECTION, claim.task_id),
        )
        if reschedule is not None:
            terminal = bool(reschedule.get("terminal"))
            if claim.task_type == "slice":
                status_field = "sliceStatus"
                next_status = "切片失败" if terminal else "待切片"
            else:
                status_field = "vectorStatus"
                next_status = "向量化失败" if terminal else "待向量化"
            connection.execute(
                """
                UPDATE aicheck_state
                SET payload = jsonb_set(payload, %s, to_jsonb(%s::text), true),
                    revision = revision + 1,
                    updated_at = now()
                WHERE tenant_id = %s AND collection = 'knowledge_files' AND object_id = %s
                """,
                ([status_field], next_status, claim.tenant_id, claim.target_id),
            )
        connection.commit()
        return True


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
