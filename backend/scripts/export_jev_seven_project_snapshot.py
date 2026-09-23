"""Export only the approved seven-project OCR corpus from a read-only snapshot.

The private 0600 zlib file is an evaluation input, never a repository artifact.
No repository loader, seeding, reconciliation, or database write is invoked.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import zlib
from pathlib import Path
from typing import Any

from libs.security.tenant import current_tenant_id
from scripts.preflight_jev_document_routing import preflight_project_corpus

PROJECT_IDS = (
    "P-2026-6B15AE", "P-2026-7F7270", "P-2026-ECD202", "P-2026-GDLNG-002",
    "P-2026-HDCP-001", "P-TEST-OCR-001", "P-TEST-OCR-002",
)


def build_snapshot(state: dict[str, Any], project_ids: tuple[str, ...] = PROJECT_IDS) -> dict[str, Any]:
    if len(set(project_ids)) != 7:
        raise ValueError("exactly_seven_distinct_projects_required")
    projects = [row for row in state.get("projects") or [] if row.get("id") in project_ids]
    if {row.get("id") for row in projects} != set(project_ids) or len(projects) != 7:
        raise ValueError("approved_projects_missing_or_duplicated")
    documents = [row for row in state.get("documents") or [] if row.get("projectId") in project_ids]
    document_ids = {str(row.get("id") or "") for row in documents}
    current_ids = {str(row.get("currentVersionId") or "") for row in documents}
    if not documents or "" in document_ids | current_ids or len(document_ids) != len(documents):
        raise ValueError("project_documents_invalid")
    versions = [row for row in state.get("versions") or []
                if str(row.get("id") or row.get("documentVersionId") or "") in current_ids]
    if len(versions) != len(current_ids):
        raise ValueError("current_versions_missing_or_duplicated")
    parses = [row for row in state.get("ocr_parse_results") or []
              if str(row.get("documentVersionId") or "") in current_ids]
    links = [row for row in state.get("node_evidence_links") or []
             if row.get("projectId") in project_ids
             and str(row.get("documentVersionId") or "") in current_ids]
    runs = [row for row in state.get("review_runs") or []
            if row.get("projectId") in project_ids
            and set(map(str, row.get("inputDocumentVersionIds") or [])) <= current_ids]
    run_ids = {str(row.get("reviewRunId") or row.get("id") or "") for row in runs}
    configured = (state.get("admin_config") or {}).get("materialReviewPoints") or []
    routing = {
        str(project["id"]): [point for point in configured
                             if point.get("enabled", True)
                             and str(point.get("businessPackId") or project.get("businessPackId")
                                     or "engineering_inspection_v1")
                             == str(project.get("businessPackId") or "engineering_inspection_v1")]
        for project in projects
    }
    snapshot = {"source": "read_only_seven_project_ocr_snapshot",
                "projects": projects, "documents": documents, "versions": versions,
                "ocr_parse_results": parses, "node_evidence_links": links,
                "routingPointsByProject": routing,
                "review_runs": runs,
                "rule_check_results": [row for row in state.get("rule_check_results") or []
                                       if str(row.get("reviewRunId") or "") in run_ids],
                "fact_corrections": [row for row in state.get("fact_corrections") or []
                                     if row.get("projectId") in project_ids],
                "requirements": [row for row in state.get("requirements") or []
                                 if row.get("projectId") in project_ids],
                "tree_nodes": [row for row in state.get("tree_nodes") or []
                               if row.get("projectId") in project_ids],
                "configuredPoints": configured}
    report = preflight_project_corpus(snapshot, expected_project_count=7)
    if report["invalidEvidenceLinks"]:
        raise ValueError("invalid_project_evidence_links")
    return snapshot


def _database_state(database_url: str) -> dict[str, Any]:
    import psycopg

    tenant_id = current_tenant_id()
    try:
        with psycopg.connect(database_url) as connection:
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            row = connection.execute(
                "SELECT payload FROM aicheck_singletons WHERE tenant_id = %s AND name = 'admin_config'",
                (tenant_id,),
            ).fetchone()
            if row is None:
                raise ValueError("persisted_admin_config_missing")

            def rows(collection: str, predicate: str, ids: list[str]) -> list[dict[str, Any]]:
                # All predicates are fixed literals below, never CLI input.
                return [item[0] for item in connection.execute(
                    "SELECT payload FROM aicheck_state WHERE tenant_id = %s AND collection = %s "
                    + predicate, (tenant_id, collection, ids),
                ).fetchall()]

            project_ids = list(PROJECT_IDS)
            projects = rows("projects", "AND object_id = ANY(%s)", project_ids)
            documents = rows("documents", "AND payload->>'projectId' = ANY(%s)", project_ids)
            current_ids = [str(item.get("currentVersionId") or "") for item in documents]
            review_runs = rows("review_runs", "AND payload->>'projectId' = ANY(%s)", project_ids)
            run_ids = [str(item.get("reviewRunId") or item.get("id") or "") for item in review_runs]
            return {"admin_config": row[0], "projects": projects, "documents": documents,
                    "versions": rows("versions", "AND object_id = ANY(%s)", current_ids),
                    "ocr_parse_results": rows("ocr_parse_results",
                                              "AND payload->>'documentVersionId' = ANY(%s)", current_ids),
                    "node_evidence_links": rows("node_evidence_links",
                                                "AND payload->>'documentVersionId' = ANY(%s)", current_ids),
                    "requirements": rows("requirements", "AND payload->>'projectId' = ANY(%s)", project_ids),
                    "tree_nodes": rows("tree_nodes", "AND payload->>'projectId' = ANY(%s)", project_ids),
                    "review_runs": review_runs,
                    "rule_check_results": rows("rule_check_results",
                                               "AND payload->>'reviewRunId' = ANY(%s)", run_ids),
                    "fact_corrections": rows("fact_corrections",
                                             "AND payload->>'projectId' = ANY(%s)", project_ids)}
    except psycopg.Error as exc:
        raise ValueError("database_read_failed") from exc


def _private_write(path: Path, data: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(data)
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.getenv("AICHECK_DATABASE_URL") or os.getenv("DATABASE_URL"))
    parser.add_argument("--state", type=Path, help="Existing private JSON state for offline replay")
    parser.add_argument("--output", required=True, type=Path, help="New private .json.zlib path")
    args = parser.parse_args()
    if bool(args.database_url) == bool(args.state):
        parser.error("provide exactly one of --state or a database URL")
    try:
        if args.state:
            if stat.S_IMODE(args.state.stat().st_mode) & 0o077:
                raise ValueError("private_source_permissions_required")
            state = json.loads(args.state.read_text(encoding="utf-8"))
        else:
            state = _database_state(args.database_url)
        snapshot = build_snapshot(state)
        payload = zlib.compress(json.dumps(snapshot, ensure_ascii=False, sort_keys=True).encode(), level=9)
        _private_write(args.output, payload)
        preflight = preflight_project_corpus(snapshot, expected_project_count=7)
    except (OSError, TypeError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps({"snapshotSha256": hashlib.sha256(payload).hexdigest(),
                      "projectCount": preflight["projectCount"],
                      "documentCount": preflight["documentCount"],
                      "readyCount": preflight["readyCount"],
                      "plannedRequestCount": preflight["requestCount"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
