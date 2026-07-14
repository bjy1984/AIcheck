from __future__ import annotations

import os

import pytest

from scripts import migrate_backend
from scripts.migrate_backend import apply_migrations


POSTGRES_URL = os.getenv("AICHECK_TEST_POSTGRES_URL")


def test_migration_manifest_freezes_every_sql_file() -> None:
    verified = migrate_backend.validate_migration_manifest()

    assert verified == {
        "0001_backend_audit_hardening": "dcec5ebd532a09c3d55e4ce3685530c7fb2446665836900dbdee9362b914fc23"
    }


def test_migration_manifest_rejects_modified_immutable_file(tmp_path, monkeypatch) -> None:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "0001_example.sql").write_text("SELECT 1;\n", encoding="utf-8")
    (migrations / "manifest.json").write_text(
        '{"migrations":[{"version":"0001_example","sha256":"' + ("0" * 64) + '","immutable":true}]}',
        encoding="utf-8",
    )
    monkeypatch.setattr(migrate_backend, "MIGRATIONS_ROOT", migrations)
    monkeypatch.setattr(migrate_backend, "MIGRATIONS_MANIFEST", migrations / "manifest.json")

    with pytest.raises(RuntimeError, match="Immutable migration checksum mismatch"):
        migrate_backend.validate_migration_manifest()


@pytest.mark.skipif(not POSTGRES_URL, reason="AICHECK_TEST_POSTGRES_URL is required for migration integration tests")
def test_backend_migration_enforces_tenant_keys_and_append_only_audit(isolated_postgres_url: str) -> None:
    import psycopg

    pending = migrate_backend.migration_status(isolated_postgres_url)
    assert pending["compatible"] is True
    assert pending["current"] is False
    assert pending["summary"] == {
        "applied": 0,
        "pending": 1,
        "checksum_mismatch": 0,
        "database_only": 0,
    }
    assert apply_migrations(isolated_postgres_url) == ["0001_backend_audit_hardening"]
    assert apply_migrations(isolated_postgres_url) == []
    current = migrate_backend.migration_status(isolated_postgres_url)
    assert current["compatible"] is True
    assert current["current"] is True
    assert current["summary"]["applied"] == 1
    with psycopg.connect(isolated_postgres_url, autocommit=False) as connection:
        primary_key_columns = [
            str(name)
            for (name,) in connection.execute(
                """
                SELECT att.attname
                FROM pg_constraint con
                JOIN unnest(con.conkey) WITH ORDINALITY AS key(attnum, ordinality) ON TRUE
                JOIN pg_attribute att ON att.attrelid = con.conrelid AND att.attnum = key.attnum
                WHERE con.conrelid = 'aicheck_state'::regclass AND con.contype = 'p'
                ORDER BY key.ordinality
                """
            ).fetchall()
        ]
        assert primary_key_columns == ["tenant_id", "collection", "object_id"]

        connection.execute(
            """
            INSERT INTO aicheck_state (tenant_id, collection, object_id, payload)
            VALUES
                ('TENANT-MIGRATION-A', 'review_runs', 'RRUN-SAME', '{"tenantId":"TENANT-MIGRATION-A"}'::jsonb),
                ('TENANT-MIGRATION-B', 'review_runs', 'RRUN-SAME', '{"tenantId":"TENANT-MIGRATION-B"}'::jsonb)
            """
        )
        count = connection.execute(
            "SELECT count(*) FROM aicheck_state WHERE collection = 'review_runs' AND object_id = 'RRUN-SAME'"
        ).fetchone()[0]
        assert count >= 2

        connection.execute(
            """
            INSERT INTO aicheck_state (tenant_id, collection, object_id, payload)
            VALUES (
                'TENANT-MIGRATION-A',
                'audit_logs',
                'AUD-MIGRATION-1',
                '{"id":"AUD-MIGRATION-1","tenantId":"TENANT-MIGRATION-A","sequence":1,"previousHash":"GENESIS","eventHash":"sha256:test"}'::jsonb
            )
            """
        )
        with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
            connection.execute(
                """
                UPDATE aicheck_state
                SET payload = payload || '{"action":"tampered"}'::jsonb
                WHERE tenant_id = 'TENANT-MIGRATION-A'
                  AND collection = 'audit_logs'
                  AND object_id = 'AUD-MIGRATION-1'
                """
            )
        connection.rollback()


@pytest.mark.skipif(not POSTGRES_URL, reason="AICHECK_TEST_POSTGRES_URL is required for migration integration tests")
def test_backend_migration_upgrades_legacy_single_tenant_tables(isolated_postgres_url: str) -> None:
    import psycopg

    with psycopg.connect(isolated_postgres_url, autocommit=False) as connection:
        connection.execute(
            """
            CREATE TABLE aicheck_state (
                collection text NOT NULL,
                object_id text NOT NULL,
                payload jsonb NOT NULL,
                updated_at timestamptz NOT NULL DEFAULT now(),
                PRIMARY KEY (collection, object_id)
            );
            CREATE TABLE aicheck_singletons (
                name text PRIMARY KEY,
                payload jsonb NOT NULL,
                updated_at timestamptz NOT NULL DEFAULT now()
            );
            CREATE TABLE idempotency_records (
                scope text PRIMARY KEY,
                payload jsonb NOT NULL,
                updated_at timestamptz NOT NULL DEFAULT now()
            );
            """
        )
        connection.execute(
            """
            INSERT INTO aicheck_state (collection, object_id, payload) VALUES
                ('review_runs', 'RRUN-LEGACY', '{"id":"RRUN-LEGACY","tenantId":"TENANT-LEGACY"}'::jsonb),
                ('projects', 'P-DEFAULT', '{"id":"P-DEFAULT"}'::jsonb),
                ('audit_logs', 'AUD-LEGACY', '{"id":"AUD-LEGACY","tenantId":"TENANT-LEGACY","sequence":1,"previousHash":"GENESIS","eventHash":"sha256:legacy"}'::jsonb);
            INSERT INTO aicheck_singletons (name, payload)
            VALUES ('admin_config', '{"tenantId":"TENANT-LEGACY","revision":1}'::jsonb);
            INSERT INTO idempotency_records (scope, payload)
            VALUES ('TENANT-LEGACY:user:role:POST:/resource:key', '{"tenantId":"TENANT-LEGACY"}'::jsonb);
            """
        )
        connection.commit()

    assert apply_migrations(isolated_postgres_url) == ["0001_backend_audit_hardening"]

    with psycopg.connect(isolated_postgres_url, autocommit=False) as connection:
        rows = connection.execute(
            "SELECT tenant_id, collection, object_id, payload ->> 'tenantId' FROM aicheck_state ORDER BY collection"
        ).fetchall()
        assert ("TENANT-LEGACY", "review_runs", "RRUN-LEGACY", "TENANT-LEGACY") in rows
        assert ("TENANT-DEFAULT", "projects", "P-DEFAULT", "TENANT-DEFAULT") in rows
        assert connection.execute(
            "SELECT tenant_id FROM aicheck_singletons WHERE name = 'admin_config'"
        ).fetchone()[0] == "TENANT-LEGACY"
        assert connection.execute(
            "SELECT tenant_id FROM idempotency_records"
        ).fetchone()[0] == "TENANT-LEGACY"
        mirrored = connection.execute(
            "SELECT tenant_id, id, event_hash FROM audit_events WHERE id = 'AUD-LEGACY'"
        ).fetchone()
        assert mirrored == ("TENANT-LEGACY", "AUD-LEGACY", "sha256:legacy")
        connection.rollback()


@pytest.mark.skipif(not POSTGRES_URL, reason="AICHECK_TEST_POSTGRES_URL is required for migration integration tests")
def test_backend_migration_rejects_changed_applied_checksum(isolated_postgres_url: str) -> None:
    import psycopg

    apply_migrations(isolated_postgres_url)
    with psycopg.connect(isolated_postgres_url, autocommit=False) as connection:
        connection.execute(
            "UPDATE schema_migrations SET checksum = %s WHERE version = %s",
            ("0" * 64, "0001_backend_audit_hardening"),
        )
        connection.commit()

    with pytest.raises(RuntimeError, match="Applied migration checksum changed"):
        apply_migrations(isolated_postgres_url)
    status = migrate_backend.migration_status(isolated_postgres_url)
    assert status["compatible"] is False
    assert status["current"] is False
    assert status["summary"]["checksum_mismatch"] == 1


@pytest.mark.skipif(not POSTGRES_URL, reason="AICHECK_TEST_POSTGRES_URL is required for migration integration tests")
def test_backend_migration_rejects_database_only_future_version(isolated_postgres_url: str) -> None:
    import psycopg

    apply_migrations(isolated_postgres_url)
    with psycopg.connect(isolated_postgres_url, autocommit=False) as connection:
        connection.execute(
            "INSERT INTO schema_migrations (version, checksum) VALUES (%s, %s)",
            ("9999_future_version", "f" * 64),
        )
        connection.commit()

    status = migrate_backend.migration_status(isolated_postgres_url)
    assert status["compatible"] is False
    assert status["current"] is False
    assert status["summary"]["database_only"] == 1
    with pytest.raises(RuntimeError, match="unknown to this build: 9999_future_version"):
        apply_migrations(isolated_postgres_url)
