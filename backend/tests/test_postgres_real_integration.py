from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from apps.api.main import acquire_idempotency_lock, app, release_idempotency_lock
from libs.db.repository import InMemoryRepository, repo
from libs.security.auth import decode_token, hash_password
from libs.security.tenant import reset_request_tenant_id, set_request_tenant_id
from scripts.migrate_backend import apply_migrations

pytestmark = pytest.mark.skipif(
    not os.getenv("AICHECK_TEST_POSTGRES_URL"),
    reason="AICHECK_TEST_POSTGRES_URL is required for PostgreSQL integration tests",
)
client = TestClient(app)


def close_repository(repository: InMemoryRepository) -> None:
    repository.close_sync_postgres()


def test_real_postgres_isolates_same_aggregate_id_between_tenants(isolated_postgres_url: str) -> None:
    import psycopg

    apply_migrations(isolated_postgres_url)
    repository = InMemoryRepository()
    repository.configure_sync_postgres(isolated_postgres_url)
    try:
        for tenant_id, status in (("TENANT-A", "queued"), ("TENANT-B", "running")):
            token = set_request_tenant_id(tenant_id)
            try:
                repository.upsert_state_records_to_sync_postgres(
                    {
                        "review_runs": [
                            {
                                "id": "RRUN-SAME",
                                "reviewRunId": "RRUN-SAME",
                                "tenantId": tenant_id,
                                "status": status,
                            }
                        ]
                    }
                )
            finally:
                reset_request_tenant_id(token)
    finally:
        close_repository(repository)

    with psycopg.connect(isolated_postgres_url, autocommit=False) as connection:
        rows = connection.execute(
            """
            SELECT tenant_id, payload ->> 'status'
            FROM aicheck_state
            WHERE collection = 'review_runs' AND object_id = 'RRUN-SAME'
            ORDER BY tenant_id
            """
        ).fetchall()
        assert rows == [("TENANT-A", "queued"), ("TENANT-B", "running")]
        connection.rollback()


def test_real_postgres_rejects_stale_cross_process_update(isolated_postgres_url: str) -> None:
    import psycopg

    apply_migrations(isolated_postgres_url)
    seed = InMemoryRepository()
    seed.configure_sync_postgres(isolated_postgres_url)
    token = set_request_tenant_id("TENANT-CONCURRENT")
    try:
        seed.upsert_state_records_to_sync_postgres(
            {
                "review_runs": [
                    {
                        "id": "RRUN-CAS",
                        "reviewRunId": "RRUN-CAS",
                        "tenantId": "TENANT-CONCURRENT",
                        "status": "queued",
                    }
                ]
            }
        )
    finally:
        reset_request_tenant_id(token)
        close_repository(seed)

    first = InMemoryRepository()
    second = InMemoryRepository()
    first.configure_sync_postgres(isolated_postgres_url)
    second.configure_sync_postgres(isolated_postgres_url)
    token = set_request_tenant_id("TENANT-CONCURRENT")
    try:
        first.load_from_sync_postgres({"review_runs"})
        second.load_from_sync_postgres({"review_runs"})
        first_run = first.find_one("review_runs", "RRUN-CAS", id_field="reviewRunId")
        second_run = second.find_one("review_runs", "RRUN-CAS", id_field="reviewRunId")
        assert first_run and second_run
        first_run["status"] = "waiting_human_review"
        second_run["status"] = "cancelled"
        first.upsert_state_records_to_sync_postgres({"review_runs": [first_run]})
        with pytest.raises(RuntimeError, match="Concurrent persistence update detected"):
            second.upsert_state_records_to_sync_postgres({"review_runs": [second_run]})
    finally:
        reset_request_tenant_id(token)
        close_repository(first)
        close_repository(second)

    with psycopg.connect(isolated_postgres_url, autocommit=False) as connection:
        status = connection.execute(
            """
            SELECT payload ->> 'status'
            FROM aicheck_state
            WHERE tenant_id = 'TENANT-CONCURRENT'
              AND collection = 'review_runs'
              AND object_id = 'RRUN-CAS'
            """
        ).fetchone()[0]
        assert status == "waiting_human_review"
        connection.rollback()


def test_real_postgres_idempotency_lock_is_bounded_and_recovers(
    isolated_postgres_url: str,
    monkeypatch,
) -> None:
    apply_migrations(isolated_postgres_url)
    scope = "TENANT-LOCK:USER-1:inspection:POST:/resource:key"
    tenant_id = "TENANT-LOCK"
    monkeypatch.setenv("AICHECK_IDEMPOTENCY_LOCK_TIMEOUT_MS", "150")
    holder, persisted = acquire_idempotency_lock(scope, tenant_id, isolated_postgres_url)
    assert persisted is None
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            blocked = executor.submit(acquire_idempotency_lock, scope, tenant_id, isolated_postgres_url)
            with pytest.raises(Exception) as error:
                blocked.result(timeout=3)
            assert type(error.value).__name__ in {"LockNotAvailable", "QueryCanceled"}
    finally:
        release_idempotency_lock(holder, SimpleNamespace(state=SimpleNamespace(idempotency_scope=scope)))

    connection, persisted = acquire_idempotency_lock(scope, tenant_id, isolated_postgres_url)
    try:
        assert persisted is None
    finally:
        release_idempotency_lock(connection, SimpleNamespace(state=SimpleNamespace(idempotency_scope=scope)))


def test_real_postgres_cold_tenant_login_loads_user_and_persists_audit(isolated_postgres_url: str) -> None:
    import psycopg

    apply_migrations(isolated_postgres_url)
    tenant_id = "TENANT-COLD-POSTGRES"
    token = set_request_tenant_id(tenant_id)
    try:
        repo.reset()
        repo.configure_sync_postgres(isolated_postgres_url)
        user = {
            "id": "USER-COLD-POSTGRES",
            "username": "cold-postgres",
            "passwordHash": hash_password("ColdPostgres!2026"),
            "role": "inspection",
            "status": "启用",
            "authVersion": 0,
            "mustChangePassword": False,
            "displayName": "冷租户 PostgreSQL 用户",
            "tenantId": tenant_id,
        }
        repo.upsert_state_records_to_sync_postgres({"users": [user]})
        repo.reset()
    finally:
        reset_request_tenant_id(token)

    try:
        response = client.post(
            "/api/auth/login",
            json={
                "tenantId": tenant_id,
                "username": "cold-postgres",
                "password": "ColdPostgres!2026",
            },
        )
        assert response.status_code == 200
        claims = decode_token(response.json()["data"]["token"])
        assert claims and claims["tid"] == tenant_id

        with psycopg.connect(isolated_postgres_url, autocommit=False) as connection:
            audit = connection.execute(
                """
                SELECT tenant_id, payload ->> 'actorId', payload ->> 'action'
                FROM aicheck_state
                WHERE tenant_id = %s AND collection = 'audit_logs'
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (tenant_id,),
            ).fetchone()
            assert audit == (tenant_id, "USER-COLD-POSTGRES", "登录成功")
            connection.rollback()
    finally:
        token = set_request_tenant_id(tenant_id)
        try:
            repo.close_sync_postgres()
            repo.postgres_dsn = None
            repo.postgres_enabled = False
            repo.reset()
        finally:
            reset_request_tenant_id(token)
