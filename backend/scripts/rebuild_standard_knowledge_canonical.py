#!/usr/bin/env python3
"""Safely rebuild derived canonical records for the standard knowledge library."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import psycopg
from psycopg.types.json import Jsonb


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from libs.security.tenant import configured_tenant_id  # noqa: E402
from libs.standard_knowledge_canonical import (  # noqa: E402
    build_standard_knowledge_record,
)


STANDARD_SOURCE_ID = "KS-STANDARD-RULES"
CANONICAL_COLLECTION = "standard_knowledge_records"
SOURCE_COLLECTIONS = (
    "knowledge_sources",
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
    "business_packs",
)
_BUILDER_COLLECTIONS = {
    "knowledge_sources": "knowledge_sources",
    "knowledge_files": "knowledge_files",
    "documents": "documents",
    "versions": "document_versions",
    "ocr_parse_results": "ocr_parse_results",
    "extracted_fields": "extracted_fields",
    "evidence_links": "evidence_links",
    "knowledge_chunks": "knowledge_chunks",
    "knowledge_clauses": "knowledge_clauses",
    "knowledge_page_index_nodes": "knowledge_page_index_nodes",
    "standard_document_versions": "standard_document_versions",
    "standard_clause_references": "standard_clause_references",
    "standard_clause_locators": "standard_clause_locators",
    "rule_versions": "rule_versions",
    "business_packs": "business_packs",
}


def persist_canonical_record(
    connection: psycopg.Connection[Any],
    tenant_id: str,
    record: dict[str, Any],
) -> Literal["inserted", "updated", "unchanged"]:
    """Lock and upsert only the derived record owned by ``tenant_id``."""
    lock_scope = json.dumps(
        [tenant_id, str(record["knowledgeFileId"])],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    connection.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
        (lock_scope,),
    )
    row = connection.execute(
        """
        SELECT payload FROM aicheck_state
        WHERE tenant_id=%s
          AND collection='standard_knowledge_records'
          AND object_id=%s
        FOR UPDATE
        """,
        (tenant_id, record["knowledgeFileId"]),
    ).fetchone()
    previous = dict(row[0]) if row else None
    if previous and previous.get("sourceFingerprint") == record["sourceFingerprint"]:
        return "unchanged"
    connection.execute(
        """
        INSERT INTO aicheck_state
            (tenant_id, collection, object_id, payload, updated_at)
        VALUES (%s, 'standard_knowledge_records', %s, %s, now())
        ON CONFLICT (tenant_id, collection, object_id)
        DO UPDATE SET payload=EXCLUDED.payload, updated_at=now()
        """,
        (tenant_id, record["knowledgeFileId"], Jsonb(record)),
    )
    return "updated" if previous else "inserted"


def source_collection_digests(
    connection: psycopg.Connection[Any], tenant_id: str
) -> dict[str, str]:
    """Hash every immutable source collection in deterministic object-ID order."""
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
                (tenant_id, collection),
            ).fetchone()[0]
        )
        for collection in SOURCE_COLLECTIONS
    }


def _standard_file_ids(connection: psycopg.Connection[Any], tenant_id: str) -> list[str]:
    return [
        str(object_id)
        for (object_id,) in connection.execute(
            """
            SELECT object_id FROM aicheck_state
            WHERE tenant_id=%s
              AND collection='knowledge_files'
              AND payload ->> 'sourceId'=%s
            ORDER BY object_id
            """,
            (tenant_id, STANDARD_SOURCE_ID),
        ).fetchall()
    ]


def _locked_standard_links(
    connection: psycopg.Connection[Any], tenant_id: str, file_id: str
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    file_row = connection.execute(
        """
        SELECT payload FROM aicheck_state
        WHERE tenant_id=%s AND collection='knowledge_files' AND object_id=%s
        FOR SHARE
        """,
        (tenant_id, file_id),
    ).fetchone()
    file = dict(file_row[0]) if file_row else {}
    if not file or file.get("sourceId") != STANDARD_SOURCE_ID:
        raise ValueError(f"not a standard knowledge file: {file_id}")

    document_id = str(file.get("documentId") or "")
    document_row = connection.execute(
        """
        SELECT payload FROM aicheck_state
        WHERE tenant_id=%s AND collection='documents' AND object_id=%s
        FOR SHARE
        """,
        (tenant_id, document_id),
    ).fetchone()
    document = dict(document_row[0]) if document_row else {}
    version_id = str(document.get("currentVersionId") or "")
    version_row = connection.execute(
        """
        SELECT payload FROM aicheck_state
        WHERE tenant_id=%s AND collection='document_versions' AND object_id=%s
        FOR SHARE
        """,
        (tenant_id, version_id),
    ).fetchone()
    version = dict(version_row[0]) if version_row else {}
    if (
        not document
        or not version
        or document.get("id") != document_id
        or version.get("id") != version_id
        or version.get("documentId") != document_id
        or file.get("documentVersionId") != version_id
    ):
        raise ValueError(f"standard document/version relationship invalid: {file_id}")
    return file, document, version


def _load_builder_state(
    connection: psycopg.Connection[Any], tenant_id: str
) -> dict[str, list[dict[str, Any]]]:
    collection_names = sorted(set(_BUILDER_COLLECTIONS.values()))
    rows = connection.execute(
        """
        SELECT collection, payload FROM aicheck_state
        WHERE tenant_id=%s AND collection=ANY(%s)
        ORDER BY collection, object_id
        """,
        (tenant_id, collection_names),
    ).fetchall()
    state = {key: [] for key in _BUILDER_COLLECTIONS}
    state_key_by_collection = {
        collection: state_key for state_key, collection in _BUILDER_COLLECTIONS.items()
    }
    for collection, payload in rows:
        state[state_key_by_collection[str(collection)]].append(dict(payload))
    return state


def rebuild(
    database_url: str,
    *,
    apply: bool,
    file_id: str | None = None,
) -> dict[str, Any]:
    tenant_id = configured_tenant_id()
    with psycopg.connect(database_url, autocommit=True) as connection:
        before_digests = source_collection_digests(connection, tenant_id)
        file_ids = [file_id] if file_id else _standard_file_ids(connection, tenant_id)
        counts = {"inserted": 0, "updated": 0, "unchanged": 0, "failed": 0}
        records: list[dict[str, Any]] = []
        context_only = 0
        planned = 0

        for current_file_id in file_ids:
            try:
                with connection.transaction():
                    _locked_standard_links(connection, tenant_id, current_file_id)
                    state = _load_builder_state(connection, tenant_id)
                    record = build_standard_knowledge_record(
                        state,
                        current_file_id,
                        REPO_ROOT,
                    )
                    context_only += int(record.get("contextType") == "context_only")
                    planned += 1
                    action = (
                        persist_canonical_record(connection, tenant_id, record)
                        if apply
                        else "planned"
                    )
                    if action in counts:
                        counts[action] += 1
                    records.append(
                        {
                            "knowledgeFileId": current_file_id,
                            "action": action,
                            "contextType": record.get("contextType"),
                            "sourceFingerprint": record.get("sourceFingerprint"),
                            "missingCategories": list(
                                (record.get("completeness") or {}).get("missingCategories") or []
                            ),
                        }
                    )
            except Exception as exc:  # noqa: BLE001 - one bad standard must not abort siblings
                counts["failed"] += 1
                records.append(
                    {
                        "knowledgeFileId": current_file_id,
                        "action": "failed",
                        "errorType": type(exc).__name__,
                        "error": str(exc),
                    }
                )

        after_digests = source_collection_digests(connection, tenant_id)

    written = counts["inserted"] + counts["updated"]
    return {
        "schemaVersion": "standard-knowledge-canonical-migration-report@1",
        "generatedAt": datetime.now(UTC).isoformat(),
        "mode": "apply" if apply else "dry-run",
        "tenantId": tenant_id,
        "processed": len(file_ids),
        "planned": planned,
        "written": written,
        **counts,
        "contextOnly": context_only,
        "sourceDigestsBefore": before_digests,
        "sourceDigestsAfter": after_digests,
        "sourceDigestUnchanged": before_digests == after_digests,
        "records": records,
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default=os.getenv("AICHECK_DATABASE_URL") or os.getenv("DATABASE_URL") or "",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--file-id")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def _render_report(report: dict[str, Any], *, pretty: bool) -> str:
    return json.dumps(
        report,
        ensure_ascii=False,
        indent=2 if pretty else None,
        sort_keys=True,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.database_url:
        raise SystemExit("AICHECK_DATABASE_URL or --database-url is required")
    report = rebuild(
        args.database_url,
        apply=bool(args.apply),
        file_id=args.file_id,
    )
    rendered = _render_report(report, pretty=bool(args.json or args.output))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return (
        1
        if int(report.get("failed") or 0) > 0 or report.get("sourceDigestUnchanged") is not True
        else 0
    )


if __name__ == "__main__":
    raise SystemExit(main())
