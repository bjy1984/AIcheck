from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

TENANT_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
INDEX_COMPATIBILITY_MARKERS = {
    "idx_aicheck_state_collection": "(tenant_id, collection)",
    "idx_aicheck_state_payload_gin": "USING gin (payload)",
    "idx_idempotency_updated_at": "(tenant_id, updated_at DESC)",
}
CORE_TABLES = ("aicheck_state", "aicheck_singletons", "idempotency_records")


def sha256_rows(connection: Any, query: str) -> tuple[int, str]:
    digest = hashlib.sha256()
    count = 0
    with connection.cursor() as cursor:
        cursor.execute(query)
        for row in cursor:
            encoded = "\0".join("" if value is None else str(value) for value in row).encode()
            digest.update(encoded)
            digest.update(b"\n")
            count += 1
    return count, digest.hexdigest()


def state_digest(connection: Any) -> tuple[int, str]:
    return sha256_rows(
        connection,
        """
        SELECT collection, object_id, (payload - 'tenantId')::text
        FROM aicheck_state
        ORDER BY collection, object_id
        """,
    )


def audit_digest(connection: Any) -> tuple[int, str]:
    return sha256_rows(
        connection,
        """
        SELECT object_id, payload::text
        FROM aicheck_state
        WHERE collection = 'audit_logs'
        ORDER BY object_id
        """,
    )


def relation_exists(connection: Any, relation: str) -> bool:
    return bool(connection.execute("SELECT to_regclass(%s) IS NOT NULL", (relation,)).fetchone()[0])


def column_names(connection: Any, table: str) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = current_schema() AND table_name = %s
            """,
            (table,),
        ).fetchall()
    }


def legacy_report(connection: Any, tenant_id: str) -> dict[str, Any]:
    state_rows, state_hash = state_digest(connection)
    audit_rows, audit_hash = audit_digest(connection)
    tables: dict[str, Any] = {}
    for table in CORE_TABLES:
        tables[table] = {
            "exists": relation_exists(connection, table),
            "columns": sorted(column_names(connection, table)) if relation_exists(connection, table) else [],
        }
    kvi_exists = relation_exists(connection, "knowledge_vector_index")
    kvi_rows = (
        int(connection.execute("SELECT count(*) FROM knowledge_vector_index").fetchone()[0])
        if kvi_exists
        else 0
    )
    indexes = {
        str(name): str(definition)
        for name, definition in connection.execute(
            """
            SELECT indexname, indexdef
            FROM pg_indexes
            WHERE schemaname = current_schema()
              AND tablename IN ('aicheck_state','aicheck_singletons','idempotency_records','knowledge_vector_index')
            ORDER BY indexname
            """
        ).fetchall()
    }
    foreign_keys = [
        {"table": str(table), "name": str(name), "definition": str(definition)}
        for table, name, definition in connection.execute(
            """
            SELECT conrelid::regclass::text, conname, pg_get_constraintdef(oid)
            FROM pg_constraint
            WHERE contype = 'f'
              AND confrelid IN (
                'aicheck_state'::regclass,
                'aicheck_singletons'::regclass,
                'idempotency_records'::regclass,
                COALESCE(to_regclass('knowledge_vector_index'), 'aicheck_state'::regclass)
              )
            ORDER BY 1,2
            """
        ).fetchall()
    ]
    audit_window = connection.execute(
        """
        SELECT min(payload ->> 'createdAt'), max(payload ->> 'createdAt'), min(updated_at), max(updated_at)
        FROM aicheck_state WHERE collection = 'audit_logs'
        """
    ).fetchone()
    migration_versions = (
        [
            {"version": str(version), "checksum": str(checksum)}
            for version, checksum in connection.execute(
                "SELECT version, checksum FROM schema_migrations ORDER BY version"
            ).fetchall()
        ]
        if relation_exists(connection, "schema_migrations")
        else []
    )
    active_transactions = int(
        connection.execute(
            """
            SELECT count(*) FROM pg_stat_activity
            WHERE datname=current_database() AND pid<>pg_backend_pid()
              AND xact_start IS NOT NULL AND state<>'idle'
            """
        ).fetchone()[0]
    )
    return {
        "schemaVersion": "aicheck-legacy-production-preflight-v1",
        "generatedAt": datetime.now(UTC).isoformat(),
        "database": str(connection.info.dbname),
        "tenantId": tenant_id,
        "stateRows": state_rows,
        "stateDigestWithoutTenant": f"sha256:{state_hash}",
        "legacyAuditRows": audit_rows,
        "legacyAuditDigest": f"sha256:{audit_hash}",
        "legacyAuditWindow": {
            "payloadCreatedAtMin": audit_window[0],
            "payloadCreatedAtMax": audit_window[1],
            "rowUpdatedAtMin": audit_window[2].isoformat() if audit_window[2] else None,
            "rowUpdatedAtMax": audit_window[3].isoformat() if audit_window[3] else None,
        },
        "tables": tables,
        "knowledgeVectorIndex": {
            "exists": kvi_exists,
            "rows": kvi_rows,
            "columns": sorted(column_names(connection, "knowledge_vector_index")) if kvi_exists else [],
        },
        "indexes": indexes,
        "referencingForeignKeys": foreign_keys,
        "migrationVersions": migration_versions,
        "activeTransactions": active_transactions,
    }


def validate_apply_guard(
    report: dict[str, Any],
    *,
    expected_state_rows: int,
    expected_state_digest: str,
    incident_id: str,
) -> None:
    if not incident_id.strip():
        raise RuntimeError("--incident-id is required with --apply")
    if report["stateRows"] != expected_state_rows:
        raise RuntimeError(
            f"State row guard failed: expected={expected_state_rows}, actual={report['stateRows']}"
        )
    normalized = expected_state_digest.removeprefix("sha256:")
    actual = str(report["stateDigestWithoutTenant"]).removeprefix("sha256:")
    if normalized != actual:
        raise RuntimeError(f"State digest guard failed: expected={normalized}, actual={actual}")
    if report["referencingForeignKeys"]:
        raise RuntimeError("Referenced legacy primary keys require a reviewed migration: " + json.dumps(report["referencingForeignKeys"]))
    if report["migrationVersions"]:
        raise RuntimeError("Legacy preparation is forbidden after versioned migrations have been applied")
    if report["activeTransactions"]:
        raise RuntimeError(f"Maintenance guard failed: {report['activeTransactions']} other active transactions")
    cosine = str(report["indexes"].get("idx_kvi_embedding_cosine") or "")
    if cosine and " USING hnsw " not in cosine:
        raise RuntimeError("Existing KVI cosine index is not HNSW; migration requires an explicit reviewed decision")


def ensure_tenant_column(connection: Any, table: str) -> None:
    connection.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS tenant_id text")


def update_state_batches(connection: Any, tenant_id: str, batch_size: int) -> int:
    total = 0
    from psycopg.types.json import Jsonb

    while True:
        with connection.transaction():
            rows = connection.execute(
                """
                WITH batch AS (
                    SELECT ctid
                    FROM aicheck_state
                    WHERE tenant_id IS DISTINCT FROM %s
                       OR payload ->> 'tenantId' IS DISTINCT FROM %s
                    ORDER BY collection, object_id
                    LIMIT %s
                    FOR UPDATE SKIP LOCKED
                )
                UPDATE aicheck_state AS state
                SET tenant_id = %s,
                    payload = jsonb_set(state.payload, '{tenantId}', %s, true),
                    updated_at = state.updated_at
                FROM batch
                WHERE state.ctid = batch.ctid
                RETURNING state.object_id
                """,
                (tenant_id, tenant_id, batch_size, tenant_id, Jsonb(tenant_id)),
            ).fetchall()
        total += len(rows)
        if len(rows) < batch_size:
            return total


def update_simple_tenant_table(connection: Any, table: str, tenant_id: str) -> int:
    from psycopg.types.json import Jsonb

    with connection.transaction():
        rows = connection.execute(
            f"""
            UPDATE {table}
            SET tenant_id = %s,
                payload = jsonb_set(payload, '{{tenantId}}', %s, true),
                updated_at = updated_at
            WHERE tenant_id IS DISTINCT FROM %s
               OR payload ->> 'tenantId' IS DISTINCT FROM %s
            RETURNING 1
            """,
            (tenant_id, Jsonb(tenant_id), tenant_id, tenant_id),
        ).fetchall()
    return len(rows)


def prepare_kvi(connection: Any, tenant_id: str, batch_size: int) -> int:
    if not relation_exists(connection, "knowledge_vector_index"):
        return 0
    if connection.execute(
        "SELECT EXISTS (SELECT 1 FROM pg_constraint WHERE contype='f' AND confrelid='knowledge_vector_index'::regclass)"
    ).fetchone()[0]:
        raise RuntimeError("knowledge_vector_index is referenced by a foreign key")
    with connection.transaction():
        connection.execute("ALTER TABLE knowledge_vector_index ADD COLUMN IF NOT EXISTS tenant_id text")
    total = 0
    while True:
        with connection.transaction():
            rows = connection.execute(
                """
                WITH batch AS (
                    SELECT ctid FROM knowledge_vector_index
                    WHERE tenant_id IS DISTINCT FROM %s
                    ORDER BY id LIMIT %s FOR UPDATE SKIP LOCKED
                )
                UPDATE knowledge_vector_index AS kvi
                SET tenant_id = %s, updated_at = kvi.updated_at
                FROM batch WHERE kvi.ctid = batch.ctid
                RETURNING kvi.id
                """,
                (tenant_id, batch_size, tenant_id),
            ).fetchall()
        total += len(rows)
        if len(rows) < batch_size:
            break
    with connection.transaction():
        constraint = connection.execute(
            "SELECT conname FROM pg_constraint WHERE conrelid='knowledge_vector_index'::regclass AND contype='p'"
        ).fetchone()
        if constraint:
            columns = [
                row[0]
                for row in connection.execute(
                    """
                    SELECT att.attname
                    FROM pg_constraint con
                    JOIN unnest(con.conkey) WITH ORDINALITY key(attnum, ordinality) ON TRUE
                    JOIN pg_attribute att ON att.attrelid=con.conrelid AND att.attnum=key.attnum
                    WHERE con.conrelid='knowledge_vector_index'::regclass AND con.contype='p'
                    ORDER BY key.ordinality
                    """
                ).fetchall()
            ]
            if columns != ["tenant_id", "id"]:
                safe_name = str(constraint[0]).replace('"', '""')
                connection.execute(f'ALTER TABLE knowledge_vector_index DROP CONSTRAINT "{safe_name}"')
                connection.execute("ALTER TABLE knowledge_vector_index ADD PRIMARY KEY (tenant_id, id)")
        else:
            connection.execute("ALTER TABLE knowledge_vector_index ADD PRIMARY KEY (tenant_id, id)")
        connection.execute("ALTER TABLE knowledge_vector_index ALTER COLUMN tenant_id SET NOT NULL")
        from psycopg import sql

        connection.execute(
            sql.SQL("ALTER TABLE knowledge_vector_index ALTER COLUMN tenant_id SET DEFAULT {}")
            .format(sql.Literal(tenant_id))
        )
    return total


def apply_preparation(connection: Any, tenant_id: str, batch_size: int) -> dict[str, Any]:
    connection.execute("SET lock_timeout = '5s'")
    dropped_indexes: list[str] = []
    with connection.transaction():
        for table in CORE_TABLES:
            ensure_tenant_column(connection, table)
        existing_indexes = {
            str(name): str(definition)
            for name, definition in connection.execute(
                "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname=current_schema()"
            ).fetchall()
        }
        for index, compatibility_marker in INDEX_COMPATIBILITY_MARKERS.items():
            definition = existing_indexes.get(index)
            if definition and compatibility_marker not in definition:
                safe_name = index.replace('"', '""')
                connection.execute(f'DROP INDEX "{safe_name}"')
                dropped_indexes.append(index)
    state_updates = update_state_batches(connection, tenant_id, batch_size)
    singleton_updates = update_simple_tenant_table(connection, "aicheck_singletons", tenant_id)
    idempotency_updates = update_simple_tenant_table(connection, "idempotency_records", tenant_id)
    kvi_updates = prepare_kvi(connection, tenant_id, batch_size)
    return {
        "stateRowsUpdated": state_updates,
        "singletonRowsUpdated": singleton_updates,
        "idempotencyRowsUpdated": idempotency_updates,
        "knowledgeVectorRowsUpdated": kvi_updates,
        "droppedIndexes": dropped_indexes,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare a legacy AIcheck production database for migration 0001.")
    parser.add_argument("--database-url", default=os.getenv("AICHECK_DATABASE_URL") or os.getenv("DATABASE_URL"))
    parser.add_argument("--tenant-id", default=os.getenv("AICHECK_TENANT_ID") or "TENANT-DEFAULT")
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--incident-id", default="")
    parser.add_argument("--confirmation", default="")
    parser.add_argument("--expected-state-rows", type=int)
    parser.add_argument("--expected-state-digest")
    parser.add_argument("--manifest-output")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not args.database_url:
        parser.error("--database-url or AICHECK_DATABASE_URL is required")
    if not TENANT_PATTERN.fullmatch(args.tenant_id):
        parser.error("--tenant-id is invalid")
    if args.batch_size < 1 or args.batch_size > 10_000:
        parser.error("--batch-size must be between 1 and 10000")

    import psycopg

    with psycopg.connect(args.database_url, autocommit=True) as connection:
        report = legacy_report(connection, args.tenant_id)
        result: dict[str, Any] = {"mode": "plan", "preflight": report}
        if args.apply:
            if args.expected_state_rows is None or not args.expected_state_digest:
                parser.error("--apply requires --expected-state-rows and --expected-state-digest")
            if args.confirmation != args.incident_id:
                parser.error("--apply requires --confirmation to exactly equal --incident-id")
            validate_apply_guard(
                report,
                expected_state_rows=args.expected_state_rows,
                expected_state_digest=args.expected_state_digest,
                incident_id=args.incident_id,
            )
            result["mode"] = "apply"
            result["incidentId"] = args.incident_id
            result["changes"] = apply_preparation(connection, args.tenant_id, args.batch_size)
            after = legacy_report(connection, args.tenant_id)
            if after["stateRows"] != report["stateRows"]:
                raise RuntimeError("State row count changed during legacy preparation")
            if after["stateDigestWithoutTenant"] != report["stateDigestWithoutTenant"]:
                raise RuntimeError("Business payload digest changed during legacy preparation")
            result["after"] = after
        if args.manifest_output:
            target = Path(args.manifest_output)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
            result["manifestOutput"] = str(target)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
