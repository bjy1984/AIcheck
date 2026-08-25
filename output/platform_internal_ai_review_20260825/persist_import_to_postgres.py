from __future__ import annotations

import json
import os
import runpy
import sys
from copy import deepcopy
from datetime import datetime
from pathlib import Path

from dotenv import dotenv_values


MAIN_ROOT = Path("/Volumes/7up/github/knowledgetools")
WORKTREE = MAIN_ROOT / ".worktrees" / "qwen-auto-gold-classification"
BACKEND = WORKTREE / "backend"
OUTPUT = MAIN_ROOT / "output" / "platform_internal_ai_review_20260825"
BOOTSTRAP = OUTPUT / "serve_imported_test_projects.py"
ENV_FILE = MAIN_ROOT / "backend" / ".env"
PROJECT_IDS = ("P-TEST-OCR-001", "P-TEST-OCR-002")


def main() -> None:
    env = dotenv_values(ENV_FILE)
    dsn = str(env.get("AICHECK_DATABASE_URL") or env.get("DATABASE_URL") or "")
    if not dsn:
        raise RuntimeError("database_url_not_configured")
    sys.path.insert(0, str(BACKEND))
    imported = runpy.run_path(str(BOOTSTRAP), run_name="postgres_import")

    from libs.db.repository import STATE_COLLECTIONS, repo
    from libs.security.auth import DEFAULT_INITIAL_PASSWORD, USERS, hash_password

    inspection_user = deepcopy(USERS["inspection"])
    inspection_user.pop("password", None)
    inspection_user["passwordHash"] = hash_password(DEFAULT_INITIAL_PASSWORD)
    inspection_user["mustChangePassword"] = False
    inspection_user["status"] = "启用"
    inspection_user["updatedAt"] = "2026-08-25 12:00:00"
    repo.state["users"] = [
        item for item in repo.state.get("users", []) if item.get("username") != "inspection"
    ]
    repo.state["users"].append(inspection_user)

    os.environ["AICHECK_DATABASE_URL"] = dsn
    os.environ["AICHECK_SQLITE_DISABLE"] = "true"
    repo.configure_sync_postgres(dsn)
    connection = repo.sync_postgres
    if connection is None:
        raise RuntimeError("postgres_connection_not_available")
    rows = connection.execute(
        """
        SELECT object_id, payload->>'dataSource'
        FROM aicheck_state
        WHERE tenant_id = 'TENANT-DEFAULT'
          AND collection = 'projects'
          AND object_id = ANY(%s)
        """,
        (list(PROJECT_IDS),),
    ).fetchall()
    connection.rollback()
    unexpected = [row[0] for row in rows if str(row[1] or "") != "test_ocr_llm_frozen_import"]
    if unexpected:
        raise RuntimeError("refusing_to_overwrite_non_test_projects:" + ",".join(unexpected))
    already_imported = len({str(row[0]) for row in rows}) == len(PROJECT_IDS)
    if not already_imported:
        repo.flush_to_sync_postgres()

    counts = {}
    for collection in (
        "projects",
        "tree_nodes",
        "requirements",
        "documents",
        "versions",
        "bindings",
        "ocr_parse_results",
        "document_classification_runs",
        "material_targeting_runs",
        "submissions",
        "node_evidence_links",
        "ai_runs",
        "review_runs",
        "review_graph_nodes",
        "review_sessions",
        "review_messages",
        "review_session_events",
        "model_call_attempts",
        "audit_logs",
        "project_members",
    ):
        physical = STATE_COLLECTIONS[collection]
        if collection == "projects":
            count = connection.execute(
                """
                SELECT count(*) FROM aicheck_state
                WHERE tenant_id = 'TENANT-DEFAULT' AND collection = %s AND object_id = ANY(%s)
                """,
                (physical, list(PROJECT_IDS)),
            ).fetchone()[0]
        elif collection == "versions":
            count = connection.execute(
                """
                SELECT count(*) FROM aicheck_state versions
                WHERE versions.tenant_id = 'TENANT-DEFAULT'
                  AND versions.collection = %s
                  AND versions.payload->>'documentId' IN (
                    SELECT object_id FROM aicheck_state documents
                    WHERE documents.tenant_id = 'TENANT-DEFAULT'
                      AND documents.collection = 'documents'
                      AND documents.payload->>'projectId' = ANY(%s)
                  )
                """,
                (physical, list(PROJECT_IDS)),
            ).fetchone()[0]
        elif collection == "review_messages":
            count = connection.execute(
                """
                SELECT count(*) FROM aicheck_state messages
                WHERE messages.tenant_id = 'TENANT-DEFAULT'
                  AND messages.collection = %s
                  AND messages.payload->>'sessionId' IN (
                    SELECT object_id FROM aicheck_state sessions
                    WHERE sessions.tenant_id = 'TENANT-DEFAULT'
                      AND sessions.collection = 'review_sessions'
                      AND sessions.payload->>'projectId' = ANY(%s)
                  )
                """,
                (physical, list(PROJECT_IDS)),
            ).fetchone()[0]
        else:
            count = connection.execute(
                """
                SELECT count(*) FROM aicheck_state
                WHERE tenant_id = 'TENANT-DEFAULT'
                  AND collection = %s
                  AND payload->>'projectId' = ANY(%s)
                """,
                (physical, list(PROJECT_IDS)),
            ).fetchone()[0]
        counts[collection] = int(count)
    project_rows = [
        {"id": row[0], "name": row[1], "dataSource": row[2]}
        for row in connection.execute(
            """
            SELECT object_id, payload->>'name', payload->>'dataSource'
            FROM aicheck_state
            WHERE tenant_id = 'TENANT-DEFAULT'
              AND collection = 'projects'
              AND object_id = ANY(%s)
            ORDER BY object_id
            """,
            (list(PROJECT_IDS),),
        ).fetchall()
    ]
    inspection_members = int(
        connection.execute(
            """
            SELECT count(*)
            FROM aicheck_state
            WHERE tenant_id = 'TENANT-DEFAULT'
              AND collection = 'project_members'
              AND payload->>'projectId' = ANY(%s)
              AND payload->>'userId' = 'USER-INSPECTION-001'
            """,
            (list(PROJECT_IDS),),
        ).fetchone()[0]
    )
    inspection_users = int(
        connection.execute(
            """
            SELECT count(*)
            FROM aicheck_state
            WHERE tenant_id = 'TENANT-DEFAULT'
              AND collection = 'users'
              AND payload->>'username' = 'inspection'
              AND payload ? 'passwordHash'
            """
        ).fetchone()[0]
    )
    connection.rollback()

    manifest = imported["MANIFEST"]
    receipt = {
        "schemaVersion": "inspection-test-project-postgres-import@1",
        "importedAt": datetime.now().isoformat(),
        "database": "aicheck/public/TENANT-DEFAULT",
        "projectIds": list(PROJECT_IDS),
        "projects": project_rows,
        "inspectionMemberCount": inspection_members,
        "inspectionUserCount": inspection_users,
        "sourceBusinessDataImmutable": manifest["sourceBusinessDataImmutable"],
        "sourceHashesVerified": manifest["sourceHashesVerified"],
        "sourceHashCount": manifest["sourceHashCount"],
        "counts": counts,
        "backup": {
            "path": str(OUTPUT / "aicheck-before-test-import.dump"),
            "sha256": "72ba592298c4f2abc888b96258b79c67a6efa3773ea98755e2c0dd44859e08e9",
        },
    }
    (OUTPUT / "postgres_import_receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
