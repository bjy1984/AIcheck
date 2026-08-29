from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

BACKEND_ROOT = Path(__file__).resolve().parents[1]
SOURCE_COLLECTIONS = (
    "knowledge_files",
    "documents",
    "document_versions",
    "ocr_parse_results",
    "extracted_fields",
    "evidence_links",
    "knowledge_chunks",
    "knowledge_clauses",
    "knowledge_page_index_nodes",
    "standard_document_versions",
    "standard_clause_references",
    "standard_clause_locators",
    "rule_versions",
)


def run_rebuild(database_url: str, *args: str) -> dict[str, Any]:
    command = [
        sys.executable,
        str(BACKEND_ROOT / "scripts/rebuild_standard_knowledge_canonical.py"),
        "--database-url",
        database_url,
        "--json",
        *args,
    ]
    completed = subprocess.run(
        command,
        cwd=BACKEND_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def run_verify(database_url: str, *, require_count: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(BACKEND_ROOT / "scripts/verify_standard_knowledge_canonical.py"),
            "--database-url",
            database_url,
            "--require-count",
            str(require_count),
            "--json",
        ],
        cwd=BACKEND_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def count_collection(database_url: str, collection: str) -> int:
    with psycopg.connect(database_url) as connection:
        return int(
            connection.execute(
                "SELECT count(*) FROM aicheck_state WHERE tenant_id=%s AND collection=%s",
                ("TENANT-DEFAULT", collection),
            ).fetchone()[0]
        )


def seed_standard_fixture(database_url: str, *, count: int) -> None:
    records = canonical_postgres_fixture_records(count=count)
    with psycopg.connect(database_url, autocommit=False) as connection:
        connection.execute(
            """
            CREATE TABLE aicheck_state (
                tenant_id text NOT NULL,
                collection text NOT NULL,
                object_id text NOT NULL,
                payload jsonb NOT NULL,
                updated_at timestamptz NOT NULL DEFAULT now(),
                PRIMARY KEY (tenant_id, collection, object_id)
            )
            """
        )
        for collection, object_id, payload in records:
            connection.execute(
                """
                INSERT INTO aicheck_state
                    (tenant_id, collection, object_id, payload, updated_at)
                VALUES (%s, %s, %s, %s, now())
                """,
                ("TENANT-DEFAULT", collection, object_id, Jsonb(payload)),
            )
        connection.commit()


def canonical_postgres_fixture_records(*, count: int) -> list[tuple[str, str, dict[str, Any]]]:
    records = []
    for index in range(1, count + 1):
        suffix = f"{index:03d}"
        file_id = f"KF-KB-{suffix}"
        document_id = f"KDOC-{suffix}"
        version_id = f"KDV-{suffix}-V1"
        records.extend(
            [
                (
                    "knowledge_files",
                    file_id,
                    {
                        "id": file_id,
                        "sourceId": "KS-STANDARD-RULES",
                        "sourceType": "standard",
                        "documentId": document_id,
                        "documentVersionId": version_id,
                        "fileName": f"STD-{suffix}.pdf",
                        "sourceRelativePath": f"rules/standards/STD-{suffix}.pdf",
                        "tenantId": "TENANT-DEFAULT",
                    },
                ),
                (
                    "documents",
                    document_id,
                    {
                        "id": document_id,
                        "currentVersionId": version_id,
                        "tenantId": "TENANT-DEFAULT",
                    },
                ),
                (
                    "document_versions",
                    version_id,
                    {
                        "id": version_id,
                        "documentId": document_id,
                        "isCurrent": True,
                        "tenantId": "TENANT-DEFAULT",
                    },
                ),
                (
                    "ocr_parse_results",
                    f"PARSE-{suffix}",
                    {
                        "id": f"PARSE-{suffix}",
                        "parseResultId": f"PARSE-{suffix}",
                        "documentId": document_id,
                        "documentVersionId": version_id,
                        "metadata": {"sidecarImported": True},
                        "fields": [{"fieldName": "标准编号", "fieldValue": f"STD-{suffix}"}],
                        "layoutBlocks": [
                            {
                                "blockId": f"B-{suffix}",
                                "blockType": "text",
                                "text": "1 范围",
                                "pageNo": 1,
                            }
                        ],
                        "tables": [],
                        "seals": [],
                        "pages": [{"pageNo": 1}],
                        "tenantId": "TENANT-DEFAULT",
                    },
                ),
            ]
        )
    return records


def source_collection_digests(database_url: str) -> dict[str, str]:
    with psycopg.connect(database_url) as connection:
        return {
            collection: str(
                connection.execute(
                    """
                    SELECT md5(coalesce(
                        string_agg(object_id || payload::text, '' ORDER BY object_id),
                        ''
                    ))
                    FROM aicheck_state
                    WHERE tenant_id=%s AND collection=%s
                    """,
                    ("TENANT-DEFAULT", collection),
                ).fetchone()[0]
            )
            for collection in SOURCE_COLLECTIONS
        }


def seed_valid_canonical(database_url: str, *, file_id: str, fingerprint: str) -> None:
    with psycopg.connect(database_url, autocommit=False) as connection:
        connection.execute(
            """
            INSERT INTO aicheck_state
                (tenant_id, collection, object_id, payload, updated_at)
            VALUES (%s, 'standard_knowledge_records', %s, %s, now())
            """,
            (
                "TENANT-DEFAULT",
                file_id,
                Jsonb(
                    {
                        "id": f"SKR-{file_id}",
                        "knowledgeFileId": file_id,
                        "canonicalVersion": "standard-knowledge-canonical@1",
                        "sourceFingerprint": fingerprint,
                    }
                ),
            ),
        )
        connection.commit()


def seed_broken_standard_source(database_url: str, *, file_id: str) -> None:
    with psycopg.connect(database_url, autocommit=False) as connection:
        file_payload = connection.execute(
            """
            SELECT payload FROM aicheck_state
            WHERE tenant_id=%s AND collection='knowledge_files' AND object_id=%s
            FOR UPDATE
            """,
            ("TENANT-DEFAULT", file_id),
        ).fetchone()[0]
        document_id = file_payload["documentId"]
        document_payload = connection.execute(
            """
            SELECT payload FROM aicheck_state
            WHERE tenant_id=%s AND collection='documents' AND object_id=%s
            FOR UPDATE
            """,
            ("TENANT-DEFAULT", document_id),
        ).fetchone()[0]
        document_payload["currentVersionId"] = "KDV-MISSING"
        connection.execute(
            """
            UPDATE aicheck_state SET payload=%s, updated_at=now()
            WHERE tenant_id=%s AND collection='documents' AND object_id=%s
            """,
            (Jsonb(document_payload), "TENANT-DEFAULT", document_id),
        )
        connection.commit()


def canonical_record(database_url: str, file_id: str) -> dict[str, Any]:
    with psycopg.connect(database_url) as connection:
        return dict(
            connection.execute(
                """
                SELECT payload FROM aicheck_state
                WHERE tenant_id=%s
                  AND collection='standard_knowledge_records'
                  AND object_id=%s
                """,
                ("TENANT-DEFAULT", file_id),
            ).fetchone()[0]
        )


def mark_context_only(database_url: str, *, file_id: str) -> None:
    with psycopg.connect(database_url, autocommit=False) as connection:
        payload = connection.execute(
            """
            SELECT payload FROM aicheck_state
            WHERE tenant_id=%s AND collection='knowledge_files' AND object_id=%s
            FOR UPDATE
            """,
            ("TENANT-DEFAULT", file_id),
        ).fetchone()[0]
        payload["contextType"] = "business_rule_context"
        connection.execute(
            """
            UPDATE aicheck_state SET payload=%s, updated_at=now()
            WHERE tenant_id=%s AND collection='knowledge_files' AND object_id=%s
            """,
            (Jsonb(payload), "TENANT-DEFAULT", file_id),
        )
        connection.commit()


def test_dry_run_writes_nothing_and_reports_all_records(isolated_postgres_url, tmp_path):
    seed_standard_fixture(isolated_postgres_url, count=2)
    output = tmp_path / "report.json"

    report = run_rebuild(
        isolated_postgres_url,
        "--dry-run",
        "--output",
        str(output),
    )

    assert report["processed"] == 2
    assert report["planned"] == 2
    assert report["written"] == 0
    assert report["failed"] == 0
    assert json.loads(output.read_text(encoding="utf-8")) == report
    assert count_collection(isolated_postgres_url, "standard_knowledge_records") == 0


def test_apply_is_idempotent_and_preserves_source_digests(isolated_postgres_url):
    seed_standard_fixture(isolated_postgres_url, count=2)
    before = source_collection_digests(isolated_postgres_url)

    first = run_rebuild(isolated_postgres_url, "--apply")
    second = run_rebuild(isolated_postgres_url, "--apply")

    assert first["inserted"] == 2
    assert first["written"] == 2
    assert second["unchanged"] == 2
    assert second["written"] == 0
    assert count_collection(isolated_postgres_url, "standard_knowledge_records") == 2
    assert source_collection_digests(isolated_postgres_url) == before
    assert first["sourceDigestUnchanged"] is True
    assert second["sourceDigestUnchanged"] is True


def test_failed_record_does_not_replace_previous_valid_record(isolated_postgres_url):
    seed_standard_fixture(isolated_postgres_url, count=1)
    seed_valid_canonical(
        isolated_postgres_url,
        file_id="KF-KB-001",
        fingerprint="sha256:good",
    )
    seed_broken_standard_source(isolated_postgres_url, file_id="KF-KB-001")

    report = run_rebuild(
        isolated_postgres_url,
        "--apply",
        "--file-id",
        "KF-KB-001",
    )

    assert report["failed"] == 1
    assert report["written"] == 0
    assert canonical_record(isolated_postgres_url, "KF-KB-001")["sourceFingerprint"] == (
        "sha256:good"
    )


def test_one_failed_record_does_not_roll_back_successful_siblings(isolated_postgres_url):
    seed_standard_fixture(isolated_postgres_url, count=2)
    seed_broken_standard_source(isolated_postgres_url, file_id="KF-KB-002")

    report = run_rebuild(isolated_postgres_url, "--apply")

    assert report["processed"] == 2
    assert report["inserted"] == 1
    assert report["failed"] == 1
    assert count_collection(isolated_postgres_url, "standard_knowledge_records") == 1
    assert canonical_record(isolated_postgres_url, "KF-KB-001")["knowledgeFileId"] == ("KF-KB-001")


def test_verifier_reports_coverage_matrix_and_all_fixture_gates(isolated_postgres_url):
    seed_standard_fixture(isolated_postgres_url, count=2)
    run_rebuild(isolated_postgres_url, "--apply")

    completed = run_verify(isolated_postgres_url, require_count=2)
    report = json.loads(completed.stdout)

    assert completed.returncode == 0, completed.stderr
    assert report["actualCount"] == 2
    assert report["mineruCovered"] == 2
    assert report["contextOnlyCount"] == 0
    assert all(report["assertions"].values())
    assert len(report["standards"]) == 2
    assert all("missingCategories" in item for item in report["standards"])
    assert report["coverageMatrix"]["identity"]["complete"] == 2
    assert report["sourceDigestsBefore"] == report["sourceDigestsAfter"]


def test_verifier_exits_nonzero_when_required_count_is_not_met(isolated_postgres_url):
    seed_standard_fixture(isolated_postgres_url, count=1)
    run_rebuild(isolated_postgres_url, "--apply")

    completed = run_verify(isolated_postgres_url, require_count=2)
    report = json.loads(completed.stdout)

    assert completed.returncode == 1
    assert report["assertions"]["canonical_count"] is False


def test_verifier_rejects_a_provenance_entry_without_source_identity(isolated_postgres_url):
    seed_standard_fixture(isolated_postgres_url, count=1)
    run_rebuild(isolated_postgres_url, "--apply")
    record = canonical_record(isolated_postgres_url, "KF-KB-001")
    record["provenance"][0]["sourceId"] = ""
    with psycopg.connect(isolated_postgres_url, autocommit=False) as connection:
        connection.execute(
            """
            UPDATE aicheck_state SET payload=%s, updated_at=now()
            WHERE tenant_id=%s
              AND collection='standard_knowledge_records'
              AND object_id=%s
            """,
            (Jsonb(record), "TENANT-DEFAULT", "KF-KB-001"),
        )
        connection.commit()

    completed = run_verify(isolated_postgres_url, require_count=1)
    report = json.loads(completed.stdout)

    assert completed.returncode == 1
    assert report["assertions"]["missing_provenance"] is False
    assert report["missingProvenanceDetails"] == [
        {"knowledgeFileId": "KF-KB-001", "paths": ["provenance[0]"]}
    ]


def test_verifier_rejects_a_field_source_without_source_identity(isolated_postgres_url):
    seed_standard_fixture(isolated_postgres_url, count=1)
    run_rebuild(isolated_postgres_url, "--apply")
    record = canonical_record(isolated_postgres_url, "KF-KB-001")
    record["identity"]["standardCode"]["sources"][0]["sourceId"] = ""
    with psycopg.connect(isolated_postgres_url, autocommit=False) as connection:
        connection.execute(
            """
            UPDATE aicheck_state SET payload=%s, updated_at=now()
            WHERE tenant_id=%s
              AND collection='standard_knowledge_records'
              AND object_id=%s
            """,
            (Jsonb(record), "TENANT-DEFAULT", "KF-KB-001"),
        )
        connection.commit()

    completed = run_verify(isolated_postgres_url, require_count=1)
    report = json.loads(completed.stdout)

    assert completed.returncode == 1
    assert report["assertions"]["missing_provenance"] is False
    assert report["missingProvenanceDetails"] == [
        {
            "knowledgeFileId": "KF-KB-001",
            "paths": ["identity.standardCode.sources[0]"],
        }
    ]


def test_verifier_enforces_the_59_record_production_baseline(isolated_postgres_url):
    seed_standard_fixture(isolated_postgres_url, count=59)
    mark_context_only(isolated_postgres_url, file_id="KF-KB-059")
    migration = run_rebuild(isolated_postgres_url, "--apply")

    completed = run_verify(isolated_postgres_url, require_count=59)
    report = json.loads(completed.stdout)

    assert migration["inserted"] == 59
    assert migration["contextOnly"] == 1
    assert completed.returncode == 0, completed.stderr
    assert report["expectedMineruCoverage"] == 58
    assert report["mineruCovered"] == 58
    assert report["expectedContextOnlyCount"] == 1
    assert report["contextOnlyCount"] == 1
    assert all(report["assertions"].values())


def test_configured_tenant_is_the_authoritative_write_boundary(
    isolated_postgres_url,
    monkeypatch,
):
    seed_standard_fixture(isolated_postgres_url, count=1)
    authoritative_tenant = "TENANT-CANONICAL-MIGRATION-TEST"
    with psycopg.connect(isolated_postgres_url, autocommit=False) as connection:
        connection.execute(
            "UPDATE aicheck_state SET tenant_id=%s",
            (authoritative_tenant,),
        )
        connection.commit()
    monkeypatch.setenv("AICHECK_TENANT_ID", authoritative_tenant)

    report = run_rebuild(isolated_postgres_url, "--apply")

    assert report["tenantId"] == authoritative_tenant
    with psycopg.connect(isolated_postgres_url) as connection:
        tenants = connection.execute(
            """
            SELECT tenant_id FROM aicheck_state
            WHERE collection='standard_knowledge_records'
            """
        ).fetchall()
    assert tenants == [(authoritative_tenant,)]
