from __future__ import annotations

import json
import os
from datetime import UTC
from pathlib import Path

import pytest

from scripts.legacy_audit_manifest import (
    build_manifest,
    canonical_bytes,
    verify_locked_reference,
    verify_manifest,
)
from scripts.migrate_backend import apply_migrations
from scripts.prepare_legacy_production import apply_preparation, legacy_report
from scripts.production_audit_ops import canonical_event_hash
from scripts.reconcile_review_runs import load_plan, mark_failed_to_start

POSTGRES_URL = os.getenv("AICHECK_TEST_POSTGRES_URL")


def test_production_compose_is_explicit_and_fail_closed() -> None:
    import yaml

    root = Path(__file__).resolve().parents[1]
    deploy = yaml.safe_load((root / "docker-compose.deploy.yml").read_text(encoding="utf-8"))["services"]
    base = yaml.safe_load((root / "docker-compose.yml").read_text(encoding="utf-8"))["services"]

    for service in (
        "api-service",
        "worker-service",
        "review-worker-service",
        "ocr-service",
        "redis",
        "minio",
        "postgres",
        "temporal-service",
        "temporal-ui",
        "embedding-service",
        "litellm-service",
    ):
        assert deploy[service]["restart"] == "unless-stopped"
    assert deploy["minio"]["ports"][0].startswith("127.0.0.1:")
    assert "@sha256:" in deploy["litellm-service"]["image"]
    assert deploy["api-service"]["environment"]["AICHECK_TENANT_MODE"].endswith(":-isolated}")
    assert deploy["api-service"]["environment"]["AICHECK_AUDIT_ANCHOR_RETENTION_DAYS"].endswith(":-3650}")
    assert base["workflow-migrate"]["profiles"] == ["migration"]
    assert "workflow-migrate" not in base["api-service"]["depends_on"]
    assert "workflow-migrate" not in base["review-worker-service"]["depends_on"]


def test_legacy_audit_manifest_hash_detects_tampering() -> None:
    manifest = build_manifest(
        {
            "tenantId": "TENANT-DEFAULT",
            "database": "aicheck",
            "legacyAuditRows": 56,
            "legacyAuditDigest": "sha256:legacy",
            "legacyAuditWindow": {},
            "stateRows": 11590,
            "stateDigestWithoutTenant": "sha256:state",
        },
        incident_id="INC-2026-001",
        backup_reference="backup://snapshot-001",
    )

    assert verify_manifest(manifest) == manifest["manifestHash"]
    manifest["legacyAuditRows"] = 55
    with pytest.raises(RuntimeError, match="hash mismatch"):
        verify_manifest(manifest)


def test_operational_audit_hash_ignores_only_integrity_fields() -> None:
    event = {"id": "AUD-1", "sequence": 1, "previousHash": "GENESIS", "action": "seal"}
    digest = canonical_event_hash("GENESIS", event)
    event["eventHash"] = "tampered-output-field"
    event["integrityStatus"] = "verified"

    assert canonical_event_hash("GENESIS", event) == digest
    event["action"] = "changed"
    assert canonical_event_hash("GENESIS", event) != digest


def test_reconciliation_plan_rejects_duplicate_review_runs(tmp_path) -> None:
    path = tmp_path / "plan.json"
    path.write_text(
        json.dumps(
            {
                "schemaVersion": "aicheck-review-reconciliation-v1",
                "incidentId": "INC-1",
                "tenantId": "TENANT-DEFAULT",
                "temporal": [
                    {
                        "reviewRunId": "RRUN-1",
                        "workflowId": "review-run-RRUN-1",
                        "runId": "RUN-1",
                        "action": "preserve_waiting",
                        "expectedDbStatus": "waiting_human_review",
                    }
                ],
                "databaseOnly": [
                    {
                        "reviewRunId": "RRUN-1",
                        "workflowId": "review-run-RRUN-1",
                        "action": "mark_failed_to_start",
                        "expectedDbStatus": "queued",
                        "reasonCode": "RECOVERY_ORPHAN_DB_ONLY",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="Duplicate ReviewRun"):
        load_plan(str(path))


def test_reconciliation_plan_rejects_path_traversal_identifier(tmp_path) -> None:
    path = tmp_path / "plan.json"
    path.write_text(
        json.dumps(
            {
                "schemaVersion": "aicheck-review-reconciliation-v1",
                "incidentId": "../escape",
                "tenantId": "TENANT-DEFAULT",
                "temporal": [],
                "databaseOnly": [],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="safe identifier"):
        load_plan(str(path))


def test_locked_manifest_verification_reads_exact_versioned_content() -> None:
    from datetime import datetime, timedelta

    retention_started_at = datetime.now(UTC) - timedelta(days=2)

    class Response:
        def __init__(self, body: bytes) -> None:
            self.body = body

        def read(self) -> bytes:
            return self.body

        def close(self) -> None:
            return None

        def release_conn(self) -> None:
            return None

    class Retention:
        mode = "COMPLIANCE"

        def __init__(self) -> None:
            self.retain_until_date = retention_started_at + timedelta(days=3650)

    class Stat:
        last_modified = retention_started_at

    class Client:
        def __init__(self, body: bytes) -> None:
            self.body = body

        def get_object(self, bucket, object_name, *, version_id):
            assert (bucket, object_name, version_id) == ("audit-anchors-v2", "legacy/manifest.json", "V1")
            return Response(self.body)

        def get_object_retention(self, bucket, object_name, *, version_id):
            return Retention()

        def stat_object(self, bucket, object_name, *, version_id):
            assert (bucket, object_name, version_id) == ("audit-anchors-v2", "legacy/manifest.json", "V1")
            return Stat()

    class Storage:
        def __init__(self, body: bytes) -> None:
            self._client = Client(body)

        def client(self):
            return self._client

    manifest = {"manifestHash": "sha256:test", "tenantId": "TENANT-DEFAULT"}
    body = canonical_bytes(manifest)
    result = verify_locked_reference(
        Storage(body),
        "minio://audit-anchors-v2/legacy/manifest.json?versionId=V1",
        3650,
        verify_delete_denied=False,
        expected_body=body,
        expected_bucket="audit-anchors-v2",
    )

    assert result["objectSha256"].startswith("sha256:")
    assert result["retentionStartedAt"] == retention_started_at.isoformat()
    assert result["retentionDurationSeconds"] == 3650 * 24 * 60 * 60
    with pytest.raises(RuntimeError, match="content mismatch"):
        verify_locked_reference(
            Storage(b"tampered"),
            "minio://audit-anchors-v2/legacy/manifest.json?versionId=V1",
            3650,
            verify_delete_denied=False,
            expected_body=body,
            expected_bucket="audit-anchors-v2",
        )


@pytest.mark.skipif(not POSTGRES_URL, reason="AICHECK_TEST_POSTGRES_URL is required")
def test_legacy_production_preparation_upgrades_realistic_old_schema(isolated_postgres_url: str) -> None:
    import psycopg

    with psycopg.connect(isolated_postgres_url, autocommit=True) as connection:
        connection.execute("CREATE EXTENSION IF NOT EXISTS vector")
        connection.execute(
            """
            CREATE TABLE aicheck_state (
                collection text NOT NULL,
                object_id text NOT NULL,
                payload jsonb NOT NULL,
                updated_at timestamptz NOT NULL DEFAULT now(),
                PRIMARY KEY (collection, object_id)
            );
            CREATE INDEX idx_aicheck_state_collection ON aicheck_state (collection);
            CREATE INDEX idx_aicheck_state_payload_gin ON aicheck_state USING gin (payload);
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
            CREATE INDEX idx_idempotency_updated_at ON idempotency_records (updated_at DESC);
            CREATE TABLE knowledge_vector_index (
                id text PRIMARY KEY,
                file_id text,
                chunk_id text,
                document_id text,
                document_version_id text,
                source_id text,
                embedding vector(3) NOT NULL,
                dimensions integer NOT NULL,
                embedding_model text NOT NULL,
                index_version text NOT NULL,
                metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
                updated_at timestamptz NOT NULL DEFAULT now()
            );
            CREATE INDEX idx_kvi_embedding_cosine
                ON knowledge_vector_index USING hnsw (embedding vector_cosine_ops)
                WITH (m = 16, ef_construction = 64);
            INSERT INTO aicheck_state (collection, object_id, payload) VALUES
                ('projects','P-1','{"id":"P-1"}'),
                ('audit_logs','AUD-LEGACY','{"id":"AUD-LEGACY","action":"legacy"}');
            INSERT INTO aicheck_singletons (name,payload) VALUES ('settings','{"revision":1}');
            INSERT INTO idempotency_records (scope,payload) VALUES ('POST:/resource:key','{}');
            INSERT INTO knowledge_vector_index (
                id, embedding, dimensions, embedding_model, index_version
            ) VALUES ('KVI-1','[0.1,0.2,0.3]',3,'test','v1');
            """
        )
        before = legacy_report(connection, "TENANT-DEFAULT")
        changes = apply_preparation(connection, "TENANT-DEFAULT", batch_size=1)
        after = legacy_report(connection, "TENANT-DEFAULT")

        assert changes["stateRowsUpdated"] == 2
        assert changes["knowledgeVectorRowsUpdated"] == 1
        assert changes["droppedIndexes"] == [
            "idx_aicheck_state_collection",
            "idx_idempotency_updated_at",
        ]
        assert after["stateDigestWithoutTenant"] == before["stateDigestWithoutTenant"]
        assert connection.execute(
            "SELECT tenant_id, payload->>'tenantId' FROM idempotency_records"
        ).fetchone() == ("TENANT-DEFAULT", "TENANT-DEFAULT")
        assert connection.execute(
            "SELECT tenant_id FROM knowledge_vector_index"
        ).fetchone()[0] == "TENANT-DEFAULT"
        old_indexes = {
            row[0]
            for row in connection.execute(
                "SELECT indexname FROM pg_indexes WHERE schemaname=current_schema()"
            ).fetchall()
        }
        assert "idx_aicheck_state_collection" not in old_indexes
        assert "idx_idempotency_updated_at" not in old_indexes
        assert "idx_aicheck_state_payload_gin" in old_indexes

    assert apply_migrations(isolated_postgres_url) == ["0001_backend_audit_hardening"]
    with psycopg.connect(isolated_postgres_url, autocommit=True) as connection:
        assert connection.execute(
            "SELECT count(*) FROM aicheck_state WHERE tenant_id='TENANT-DEFAULT'"
        ).fetchone()[0] == 2
        kvi_pk = connection.execute(
            """
            SELECT array_agg(att.attname ORDER BY key.ordinality)
            FROM pg_constraint con
            JOIN unnest(con.conkey) WITH ORDINALITY key(attnum, ordinality) ON TRUE
            JOIN pg_attribute att ON att.attrelid=con.conrelid AND att.attnum=key.attnum
            WHERE con.conrelid='knowledge_vector_index'::regclass AND con.contype='p'
            """
        ).fetchone()[0]
        assert kvi_pk == ["tenant_id", "id"]
        index_defs = {
            name: definition
            for name, definition in connection.execute(
                "SELECT indexname,indexdef FROM pg_indexes WHERE schemaname=current_schema()"
            ).fetchall()
        }
        assert "(tenant_id, collection)" in index_defs["idx_aicheck_state_collection"]
        assert "(tenant_id, updated_at DESC)" in index_defs["idx_idempotency_updated_at"]


@pytest.mark.skipif(not POSTGRES_URL, reason="AICHECK_TEST_POSTGRES_URL is required")
def test_database_only_reconciliation_is_cas_and_audited(isolated_postgres_url: str) -> None:
    import psycopg
    from psycopg.types.json import Jsonb

    apply_migrations(isolated_postgres_url)
    with psycopg.connect(isolated_postgres_url, autocommit=False) as connection:
        connection.execute(
            """
            INSERT INTO aicheck_state (tenant_id,collection,object_id,payload,revision)
            VALUES (%s,'review_runs','RRUN-ORPHAN',%s,1)
            """,
            (
                "TENANT-DEFAULT",
                Jsonb({"id": "RRUN-ORPHAN", "tenantId": "TENANT-DEFAULT", "status": "queued"}),
            ),
        )
        connection.commit()
        with connection.transaction():
            applied = mark_failed_to_start(
                connection,
                tenant_id="TENANT-DEFAULT",
                incident_id="INC-RECONCILE-1",
                entry={
                    "reviewRunId": "RRUN-ORPHAN",
                    "expectedDbStatus": "queued",
                    "reasonCode": "RECOVERY_ORPHAN_DB_ONLY",
                },
            )

        assert applied["revision"] == 2
        status = connection.execute(
            "SELECT payload->>'status' FROM aicheck_state WHERE tenant_id=%s AND collection='review_runs' AND object_id='RRUN-ORPHAN'",
            ("TENANT-DEFAULT",),
        ).fetchone()[0]
        audit = connection.execute(
            "SELECT payload->>'reasonCode', sequence, event_hash FROM audit_events WHERE tenant_id=%s",
            ("TENANT-DEFAULT",),
        ).fetchone()
        assert status == "failed_to_start"
        assert audit[0] == "RECOVERY_ORPHAN_DB_ONLY"
        assert audit[1] == 1
        assert str(audit[2]).startswith("sha256:")
