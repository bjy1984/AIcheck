from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from apps.mineru_worker.queue import (
    claim_knowledge_tasks,
    claim_jobs,
    finish_knowledge_claim,
    finish_claim,
    reschedule_knowledge_claim,
    reschedule_claim,
    write_heartbeat,
)
from scripts.migrate_backend import apply_migrations


pytestmark = pytest.mark.skipif(
    not os.getenv("AICHECK_TEST_POSTGRES_URL"),
    reason="AICHECK_TEST_POSTGRES_URL is required for PostgreSQL queue integration tests",
)


def insert_job(dsn: str, *, tenant_id: str, job_id: str, status: str = "queued") -> None:
    import psycopg
    from psycopg.types.json import Jsonb

    with psycopg.connect(dsn, autocommit=False) as connection:
        connection.execute(
            """
            INSERT INTO aicheck_state (tenant_id, collection, object_id, payload)
            VALUES (%s, 'ocr_jobs', %s, %s)
            """,
            (
                tenant_id,
                job_id,
                Jsonb(
                    {
                        "id": job_id,
                        "tenantId": tenant_id,
                        "provider": "mineru",
                        "status": status,
                        "stage": "queued",
                        "attempts": 0,
                    }
                ),
            ),
        )
        connection.commit()


def read_payload(dsn: str, tenant_id: str, job_id: str) -> dict:
    import psycopg

    with psycopg.connect(dsn) as connection:
        row = connection.execute(
            """
            SELECT payload FROM aicheck_state
            WHERE tenant_id = %s AND collection = 'ocr_jobs' AND object_id = %s
            """,
            (tenant_id, job_id),
        ).fetchone()
    assert row is not None
    return dict(row[0])


def insert_knowledge_task(
    dsn: str,
    *,
    tenant_id: str,
    task_id: str,
    task_type: str,
    target_id: str = "KF-QUEUE",
    status: str = "排队中",
) -> None:
    import psycopg
    from psycopg.types.json import Jsonb

    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute(
            """
            INSERT INTO aicheck_state (tenant_id, collection, object_id, payload)
            VALUES (%s, 'knowledge_tasks', %s, %s)
            """,
            (
                tenant_id,
                task_id,
                Jsonb(
                    {
                        "id": task_id,
                        "tenantId": tenant_id,
                        "taskType": task_type,
                        "targetId": target_id,
                        "status": status,
                        "progress": 0,
                    }
                ),
            ),
        )


def read_knowledge_task(dsn: str, tenant_id: str, task_id: str) -> dict:
    import psycopg

    with psycopg.connect(dsn) as connection:
        row = connection.execute(
            """
            SELECT payload FROM aicheck_state
            WHERE tenant_id = %s AND collection = 'knowledge_tasks' AND object_id = %s
            """,
            (tenant_id, task_id),
        ).fetchone()
    assert row is not None
    return dict(row[0])


def test_claim_has_single_owner_and_finish_checks_token(isolated_postgres_url: str) -> None:
    apply_migrations(isolated_postgres_url)
    insert_job(isolated_postgres_url, tenant_id="TENANT-MINERU-CLAIM", job_id="OCRJOB-CLAIM")

    first = claim_jobs(isolated_postgres_url, "worker-a", limit=1, lease_seconds=60)
    second = claim_jobs(isolated_postgres_url, "worker-b", limit=1, lease_seconds=60)

    assert [claim.job_id for claim in first] == ["OCRJOB-CLAIM"]
    assert second == []
    assert finish_claim(isolated_postgres_url, replace(first[0], lease_token="wrong")) is False
    assert finish_claim(isolated_postgres_url, first[0]) is True
    payload = read_payload(isolated_postgres_url, "TENANT-MINERU-CLAIM", "OCRJOB-CLAIM")
    assert "leaseToken" not in payload
    assert "leaseUntil" not in payload


def test_concurrent_claim_uses_skip_locked(isolated_postgres_url: str) -> None:
    apply_migrations(isolated_postgres_url)
    insert_job(isolated_postgres_url, tenant_id="TENANT-MINERU-RACE", job_id="OCRJOB-RACE")

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(claim_jobs, isolated_postgres_url, worker_id, limit=1, lease_seconds=60)
            for worker_id in ("worker-a", "worker-b")
        ]
        claims = [claim for future in futures for claim in future.result(timeout=5)]

    assert [claim.job_id for claim in claims] == ["OCRJOB-RACE"]


def test_expired_lease_is_reclaimed(isolated_postgres_url: str) -> None:
    import psycopg

    apply_migrations(isolated_postgres_url)
    insert_job(isolated_postgres_url, tenant_id="TENANT-MINERU-EXPIRED", job_id="OCRJOB-EXPIRED")
    first = claim_jobs(isolated_postgres_url, "worker-a", limit=1, lease_seconds=60)[0]
    with psycopg.connect(isolated_postgres_url, autocommit=True) as connection:
        connection.execute(
            """
            UPDATE aicheck_state
            SET payload = jsonb_set(payload, '{leaseUntil}', to_jsonb('2020-01-01T00:00:00+00:00'::text))
            WHERE tenant_id = %s AND collection = 'ocr_jobs' AND object_id = %s
            """,
            (first.tenant_id, first.job_id),
        )

    reclaimed = claim_jobs(isolated_postgres_url, "worker-b", limit=1, lease_seconds=60)

    assert len(reclaimed) == 1
    assert reclaimed[0].job_id == first.job_id
    assert reclaimed[0].lease_token != first.lease_token


def test_reschedule_honors_due_time_and_heartbeat_is_persisted(isolated_postgres_url: str) -> None:
    import psycopg

    apply_migrations(isolated_postgres_url)
    insert_job(isolated_postgres_url, tenant_id="TENANT-MINERU-RETRY", job_id="OCRJOB-RETRY")
    claim = claim_jobs(isolated_postgres_url, "worker-retry", limit=1, lease_seconds=60)[0]

    assert reschedule_claim(
        isolated_postgres_url,
        claim,
        diagnostics=[{"code": "MINERU_TIMEOUT", "retryable": True}],
        delay_seconds=30,
    ) is True
    assert claim_jobs(isolated_postgres_url, "worker-other", limit=1, lease_seconds=60) == []
    payload = read_payload(isolated_postgres_url, claim.tenant_id, claim.job_id)
    assert payload["status"] == "queued"
    assert payload["stage"] == "retry_wait"
    assert payload["attempts"] == 1
    assert datetime.fromisoformat(payload["nextAttemptAt"]) > datetime.now(timezone.utc)

    with psycopg.connect(isolated_postgres_url, autocommit=True) as connection:
        connection.execute(
            """
            UPDATE aicheck_state
            SET payload = jsonb_set(payload, '{nextAttemptAt}', to_jsonb('2020-01-01T00:00:00+00:00'::text))
            WHERE tenant_id = %s AND collection = 'ocr_jobs' AND object_id = %s
            """,
            (claim.tenant_id, claim.job_id),
        )
    assert len(claim_jobs(isolated_postgres_url, "worker-other", limit=1, lease_seconds=60)) == 1

    write_heartbeat(isolated_postgres_url, "worker-retry", {"activeCount": 1, "lastError": None})
    with psycopg.connect(isolated_postgres_url) as connection:
        row = connection.execute(
            """
            SELECT service_role, instance_id, payload
            FROM service_heartbeats WHERE service_id = %s
            """,
            ("mineru-worker:worker-retry",),
        ).fetchone()
    assert row is not None
    assert row[0] == "mineru-worker"
    assert row[1] == "worker-retry"
    assert dict(row[2])["activeCount"] == 1


def test_knowledge_task_claim_is_exclusive_and_vector_waits_for_slice(
    isolated_postgres_url: str,
) -> None:
    apply_migrations(isolated_postgres_url)
    tenant_id = "TENANT-KNOWLEDGE-ORDER"
    insert_knowledge_task(
        isolated_postgres_url,
        tenant_id=tenant_id,
        task_id="KT-SLICE",
        task_type="slice",
    )
    insert_knowledge_task(
        isolated_postgres_url,
        tenant_id=tenant_id,
        task_id="KT-VECTOR",
        task_type="vector",
    )

    first = claim_knowledge_tasks(
        isolated_postgres_url,
        "worker-a",
        limit=2,
        lease_seconds=60,
    )
    competing = claim_knowledge_tasks(
        isolated_postgres_url,
        "worker-b",
        limit=2,
        lease_seconds=60,
    )

    assert [(claim.task_id, claim.task_type) for claim in first] == [("KT-SLICE", "slice")]
    assert competing == []
    assert finish_knowledge_claim(isolated_postgres_url, first[0]) is True

    import psycopg

    with psycopg.connect(isolated_postgres_url, autocommit=True) as connection:
        connection.execute(
            """
            UPDATE aicheck_state
            SET payload = jsonb_set(payload, '{status}', to_jsonb('成功'::text))
            WHERE tenant_id = %s AND collection = 'knowledge_tasks' AND object_id = 'KT-SLICE'
            """,
            (tenant_id,),
        )

    vector = claim_knowledge_tasks(
        isolated_postgres_url,
        "worker-b",
        limit=2,
        lease_seconds=60,
    )
    assert [(claim.task_id, claim.task_type) for claim in vector] == [("KT-VECTOR", "vector")]


def test_knowledge_task_expired_lease_and_retry_due_time(
    isolated_postgres_url: str,
) -> None:
    import psycopg

    apply_migrations(isolated_postgres_url)
    tenant_id = "TENANT-KNOWLEDGE-RETRY"
    insert_knowledge_task(
        isolated_postgres_url,
        tenant_id=tenant_id,
        task_id="KT-RETRY",
        task_type="slice",
    )
    first = claim_knowledge_tasks(isolated_postgres_url, "worker-a", lease_seconds=60)[0]
    with psycopg.connect(isolated_postgres_url, autocommit=True) as connection:
        connection.execute(
            """
            UPDATE aicheck_state
            SET payload = jsonb_set(payload, '{leaseUntil}', to_jsonb('2020-01-01T00:00:00+00:00'::text))
            WHERE tenant_id = %s AND collection = 'knowledge_tasks' AND object_id = %s
            """,
            (tenant_id, first.task_id),
        )
    reclaimed = claim_knowledge_tasks(isolated_postgres_url, "worker-b", lease_seconds=60)[0]
    assert reclaimed.lease_token != first.lease_token

    assert reschedule_knowledge_claim(
        isolated_postgres_url,
        reclaimed,
        error_message="temporary embedding failure",
        delay_seconds=30,
    ) is True
    assert claim_knowledge_tasks(isolated_postgres_url, "worker-c", lease_seconds=60) == []
    payload = read_knowledge_task(isolated_postgres_url, tenant_id, reclaimed.task_id)
    assert payload["status"] == "排队中"
    assert payload["attempts"] == 1
    assert payload["errorMessage"] == "temporary embedding failure"
    assert datetime.fromisoformat(payload["nextAttemptAt"]) > datetime.now(timezone.utc)


def test_legacy_running_knowledge_task_without_lease_is_reclaimed(
    isolated_postgres_url: str,
) -> None:
    apply_migrations(isolated_postgres_url)
    insert_knowledge_task(
        isolated_postgres_url,
        tenant_id="TENANT-KNOWLEDGE-LEGACY",
        task_id="KT-LEGACY-RUNNING",
        task_type="slice",
        status="运行中",
    )

    claims = claim_knowledge_tasks(
        isolated_postgres_url,
        "worker-recovery",
        lease_seconds=60,
    )

    assert [claim.task_id for claim in claims] == ["KT-LEGACY-RUNNING"]
