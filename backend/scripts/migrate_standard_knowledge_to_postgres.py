from __future__ import annotations

import argparse
import json
import os
import sqlite3
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import Any

STANDARD_SOURCE_ID = "KS-STANDARD-RULES"


def load_sqlite_rows(path: Path) -> dict[str, list[tuple[str, dict[str, Any]]]]:
    grouped: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    with sqlite3.connect(path) as connection:
        rows = connection.execute(
            "SELECT collection, object_id, payload FROM aicheck_state ORDER BY collection, object_id"
        ).fetchall()
    for collection, object_id, raw_payload in rows:
        payload = json.loads(raw_payload)
        if isinstance(payload, dict):
            grouped[str(collection)].append((str(object_id), payload))
    return grouped


def select_standard_rows(
    grouped: dict[str, list[tuple[str, dict[str, Any]]]],
) -> dict[str, list[tuple[str, dict[str, Any]]]]:
    files = [
        row
        for row in grouped.get("knowledge_files", [])
        if row[1].get("sourceId") == STANDARD_SOURCE_ID
    ]
    file_ids = {row[0] for row in files}
    document_ids = {str(row[1].get("documentId")) for row in files if row[1].get("documentId")}
    version_ids = {
        str(row[1].get("documentVersionId")) for row in files if row[1].get("documentVersionId")
    }
    chunks = [
        row
        for row in grouped.get("knowledge_chunks", [])
        if row[1].get("sourceId") == STANDARD_SOURCE_ID or row[1].get("fileId") in file_ids
    ]
    chunk_ids = {row[0] for row in chunks}

    predicates: dict[str, Callable[[dict[str, Any]], bool]] = {
        "knowledge_sources": lambda item: item.get("id") == STANDARD_SOURCE_ID,
        "knowledge_files": lambda item: item.get("sourceId") == STANDARD_SOURCE_ID,
        "knowledge_tasks": lambda item: item.get("targetId") in file_ids
        or item.get("documentId") in document_ids
        or item.get("documentVersionId") in version_ids,
        "knowledge_chunks": lambda item: item.get("sourceId") == STANDARD_SOURCE_ID
        or item.get("fileId") in file_ids,
        "knowledge_vectors": lambda item: item.get("sourceId") == STANDARD_SOURCE_ID
        or item.get("fileId") in file_ids
        or item.get("chunkId") in chunk_ids,
        "knowledge_clauses": lambda item: item.get("fileId") in file_ids
        or item.get("clauseId") in chunk_ids
        or (item.get("scope") or {}).get("sourceId") == STANDARD_SOURCE_ID,
        "knowledge_page_index_nodes": lambda item: item.get("kbDocId") == STANDARD_SOURCE_ID
        or item.get("fileId") in file_ids
        or item.get("nodeId") in file_ids,
        "knowledge_chunk_quarantines": lambda item: item.get("sourceId") == STANDARD_SOURCE_ID
        or item.get("fileId") in file_ids
        or item.get("chunkId") in chunk_ids,
        "knowledge_vector_corrections": lambda item: item.get("fileId") in file_ids
        or item.get("chunkId") in chunk_ids,
        "documents": lambda item: item.get("id") in document_ids,
        "document_versions": lambda item: item.get("id") in version_ids
        or item.get("documentId") in document_ids,
        "ocr_jobs": lambda item: item.get("documentId") in document_ids
        or item.get("documentVersionId") in version_ids,
        "ocr_parse_results": lambda item: item.get("documentId") in document_ids
        or item.get("documentVersionId") in version_ids,
        "extracted_fields": lambda item: item.get("documentVersionId") in version_ids,
    }
    selected: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for collection, predicate in predicates.items():
        matching = [row for row in grouped.get(collection, []) if predicate(row[1])]
        if matching:
            selected[collection] = matching
    return selected


def migrate(
    selected: dict[str, list[tuple[str, dict[str, Any]]]],
    database_url: str,
) -> dict[str, Any]:
    try:
        import psycopg
    except Exception as exc:  # pragma: no cover - deployment dependency
        raise RuntimeError(f"psycopg is required: {exc}") from exc

    inserted_or_updated: dict[str, int] = {}
    with psycopg.connect(database_url, autocommit=False) as connection:
        with connection.transaction():
            connection.execute("SELECT pg_advisory_xact_lock(hashtext('aicheck_standard_knowledge_migration'))")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS aicheck_state (
                    tenant_id text NOT NULL DEFAULT 'TENANT-DEFAULT',
                    collection text NOT NULL,
                    object_id text NOT NULL,
                    payload jsonb NOT NULL,
                    updated_at timestamptz NOT NULL DEFAULT now(),
                    PRIMARY KEY (tenant_id, collection, object_id)
                )
                """
            )
            for collection, rows in selected.items():
                for object_id, payload in rows:
                    tenant_id = str(payload.get("tenantId") or os.getenv("AICHECK_TENANT_ID") or "TENANT-DEFAULT")
                    connection.execute(
                        """
                        INSERT INTO aicheck_state (tenant_id, collection, object_id, payload, updated_at)
                        VALUES (%s, %s, %s, %s::jsonb, now())
                        ON CONFLICT (tenant_id, collection, object_id)
                        DO UPDATE SET payload = EXCLUDED.payload, updated_at = now()
                        """,
                        (tenant_id, collection, object_id, json.dumps(payload, ensure_ascii=False)),
                    )
                inserted_or_updated[collection] = len(rows)
        connection.commit()
    return {"collections": inserted_or_updated, "rowCount": sum(inserted_or_updated.values())}


def target_counts(selected: dict[str, list[tuple[str, dict[str, Any]]]], database_url: str) -> dict[str, int]:
    try:
        import psycopg
    except Exception:
        return {}
    collections = list(selected)
    if not collections:
        return {}
    with psycopg.connect(database_url, autocommit=True) as connection:
        rows = connection.execute(
            "SELECT collection, count(*) FROM aicheck_state WHERE collection = ANY(%s) GROUP BY collection",
            (collections,),
        ).fetchall()
    return {str(collection): int(count) for collection, count in rows}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Safely upsert only KS-STANDARD-RULES data from SQLite into PostgreSQL."
    )
    parser.add_argument("--sqlite", type=Path, default=Path("data/aicheck.sqlite3"))
    parser.add_argument(
        "--database-url",
        default=os.getenv("AICHECK_DATABASE_URL") or os.getenv("DATABASE_URL") or "",
    )
    parser.add_argument("--apply", action="store_true", help="Apply the transaction. Default is dry-run.")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.sqlite.is_file():
        raise SystemExit(f"SQLite source does not exist: {args.sqlite}")
    if not args.database_url:
        raise SystemExit("AICHECK_DATABASE_URL or --database-url is required")
    selected = select_standard_rows(load_sqlite_rows(args.sqlite))
    file_count = len(selected.get("knowledge_files", []))
    chunk_count = len(selected.get("knowledge_chunks", []))
    vector_count = len(selected.get("knowledge_vectors", []))
    if file_count == 0 or chunk_count == 0 or vector_count != chunk_count:
        raise SystemExit(
            f"Source knowledge gate failed: files={file_count}, chunks={chunk_count}, vectors={vector_count}"
        )
    before = target_counts(selected, args.database_url)
    applied = migrate(selected, args.database_url) if args.apply else None
    after = target_counts(selected, args.database_url) if args.apply else before
    report = {
        "schemaVersion": "aicheck-standard-knowledge-postgres-migration@1",
        "mode": "apply" if args.apply else "dry-run",
        "sourceId": STANDARD_SOURCE_ID,
        "sourceSqlite": str(args.sqlite),
        "sourceCounts": {name: len(rows) for name, rows in selected.items()},
        "targetCountsBefore": before,
        "targetCountsAfter": after,
        "applied": applied,
        "preservesNonKnowledgeCollections": True,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2 if args.json else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
