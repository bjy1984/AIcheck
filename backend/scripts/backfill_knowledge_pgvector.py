from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from typing import Any


DEFAULT_SOURCE_ID = "KS-STANDARD-RULES"
DEFAULT_DIMENSIONS = 1024
DEFAULT_EXPECTED_COUNT = 2134
DEFAULT_MODEL = "Qwen/Qwen3-Embedding-0.6B"
DEFAULT_INDEX_VERSION = "knowledge-index-qwen3-0.6b@1024"


def canonical_digest(rows: list[tuple[str, dict[str, Any]]]) -> str:
    digest = hashlib.sha256()
    for object_id, payload in sorted(rows, key=lambda item: item[0]):
        digest.update(object_id.encode("utf-8"))
        digest.update(b"\0")
        digest.update(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        digest.update(b"\n")
    return digest.hexdigest()


def vector_literal(values: Any, *, dimensions: int = DEFAULT_DIMENSIONS) -> tuple[str, float]:
    if not isinstance(values, list) or len(values) != dimensions:
        raise ValueError(f"embedding must contain exactly {dimensions} values")
    normalized: list[float] = []
    norm_squared = 0.0
    for value in values:
        try:
            parsed = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("embedding contains a non-numeric value") from exc
        if not math.isfinite(parsed):
            raise ValueError("embedding contains a non-finite value")
        normalized.append(parsed)
        norm_squared += parsed * parsed
    norm = math.sqrt(norm_squared)
    if norm <= 0:
        raise ValueError("embedding must not be a zero vector")
    return "[" + ",".join(format(value, ".17g") for value in normalized) + "]", norm


def prepare_row(
    object_id: str,
    payload: dict[str, Any],
    *,
    dimensions: int = DEFAULT_DIMENSIONS,
) -> dict[str, Any]:
    if int(payload.get("dimensions") or 0) != dimensions:
        raise ValueError(f"{object_id}: dimensions do not match {dimensions}")
    literal, norm = vector_literal(payload.get("embedding"), dimensions=dimensions)
    required = {
        "fileId": payload.get("fileId"),
        "chunkId": payload.get("chunkId"),
        "sourceId": payload.get("sourceId"),
        "embeddingModel": payload.get("embeddingModel"),
        "indexVersion": payload.get("indexVersion"),
    }
    missing = [key for key, value in required.items() if not value]
    if missing:
        raise ValueError(f"{object_id}: missing required fields {','.join(missing)}")
    metadata = {key: value for key, value in payload.items() if key != "embedding"}
    return {
        "id": object_id,
        "file_id": payload.get("fileId"),
        "chunk_id": payload.get("chunkId"),
        "document_id": payload.get("documentId"),
        "document_version_id": payload.get("documentVersionId"),
        "source_id": payload.get("sourceId"),
        "embedding_literal": literal,
        "norm": norm,
        "dimensions": dimensions,
        "embedding_model": payload.get("embeddingModel"),
        "index_version": payload.get("indexVersion"),
        "metadata": json.dumps(metadata, ensure_ascii=False, sort_keys=True),
    }


def load_source_rows(connection: Any, source_id: str) -> list[tuple[str, dict[str, Any]]]:
    rows = connection.execute(
        """
        SELECT object_id, payload
        FROM aicheck_state
        WHERE collection = 'knowledge_vectors'
          AND payload->>'sourceId' = %s
        ORDER BY object_id
        """,
        (source_id,),
    ).fetchall()
    normalized: list[tuple[str, dict[str, Any]]] = []
    for object_id, payload in rows:
        if isinstance(payload, str):
            payload = json.loads(payload)
        if isinstance(payload, dict):
            normalized.append((str(object_id), payload))
    return normalized


def schema_status(connection: Any) -> dict[str, Any]:
    available = bool(
        connection.execute(
            "SELECT EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'vector')"
        ).fetchone()[0]
    )
    installed = bool(
        connection.execute(
            "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')"
        ).fetchone()[0]
    )
    table_ready = connection.execute(
        "SELECT to_regclass('public.knowledge_vector_index')"
    ).fetchone()[0] is not None
    index_definition = None
    if table_ready:
        row = connection.execute(
            "SELECT indexdef FROM pg_indexes WHERE schemaname='public' AND indexname='idx_kvi_embedding_cosine'"
        ).fetchone()
        index_definition = str(row[0]) if row else None
    return {
        "extensionAvailable": available,
        "extensionInstalled": installed,
        "tableReady": table_ready,
        "cosineIndex": index_definition,
        "hnswReady": bool(index_definition and "USING hnsw" in index_definition),
    }


def ensure_schema(connection: Any) -> None:
    connection.execute("CREATE EXTENSION IF NOT EXISTS vector")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_vector_index (
            id text PRIMARY KEY,
            file_id text,
            chunk_id text,
            document_id text,
            document_version_id text,
            source_id text,
            embedding vector(1024) NOT NULL,
            dimensions integer NOT NULL CHECK (dimensions = 1024),
            embedding_model text NOT NULL,
            index_version text NOT NULL,
            metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
            updated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_kvi_source ON knowledge_vector_index (source_id)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_kvi_index_version ON knowledge_vector_index (index_version)"
    )
    current = connection.execute(
        "SELECT indexdef FROM pg_indexes WHERE schemaname='public' AND indexname='idx_kvi_embedding_cosine'"
    ).fetchone()
    if current and "USING hnsw" not in str(current[0]):
        connection.execute("DROP INDEX idx_kvi_embedding_cosine")
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_kvi_embedding_cosine
        ON knowledge_vector_index
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
        """
    )


def target_summary(connection: Any, source_id: str) -> dict[str, Any]:
    if connection.execute(
        "SELECT to_regclass('public.knowledge_vector_index')"
    ).fetchone()[0] is None:
        return {
            "count": 0,
            "dimensionMismatchCount": 0,
            "zeroVectorCount": 0,
            "duplicateChunkCount": 0,
        }
    count, dimension_mismatch, zero_vectors = connection.execute(
        """
        SELECT
            count(*),
            count(*) FILTER (WHERE dimensions <> 1024),
            count(*) FILTER (WHERE vector_norm(embedding) IS NULL OR vector_norm(embedding) <= 0)
        FROM knowledge_vector_index
        WHERE source_id = %s
        """,
        (source_id,),
    ).fetchone()
    duplicate_chunks = connection.execute(
        """
        SELECT count(*)
        FROM (
            SELECT chunk_id
            FROM knowledge_vector_index
            WHERE source_id = %s
            GROUP BY chunk_id
            HAVING count(*) > 1
        ) duplicates
        """,
        (source_id,),
    ).fetchone()[0]
    return {
        "count": int(count),
        "dimensionMismatchCount": int(dimension_mismatch),
        "zeroVectorCount": int(zero_vectors),
        "duplicateChunkCount": int(duplicate_chunks),
    }


def apply_backfill(
    connection: Any,
    prepared: list[dict[str, Any]],
    *,
    source_id: str,
    prune_stale: bool,
) -> dict[str, int]:
    stale_removed = 0
    with connection.transaction():
        connection.execute(
            "SELECT pg_advisory_xact_lock(hashtext('aicheck_knowledge_pgvector_backfill'))"
        )
        ensure_schema(connection)
        for row in prepared:
            connection.execute(
                """
                INSERT INTO knowledge_vector_index (
                    id, file_id, chunk_id, document_id, document_version_id, source_id,
                    embedding, dimensions, embedding_model, index_version, metadata, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s::vector, %s, %s, %s, %s::jsonb, now())
                ON CONFLICT (id) DO UPDATE SET
                    file_id = EXCLUDED.file_id,
                    chunk_id = EXCLUDED.chunk_id,
                    document_id = EXCLUDED.document_id,
                    document_version_id = EXCLUDED.document_version_id,
                    source_id = EXCLUDED.source_id,
                    embedding = EXCLUDED.embedding,
                    dimensions = EXCLUDED.dimensions,
                    embedding_model = EXCLUDED.embedding_model,
                    index_version = EXCLUDED.index_version,
                    metadata = EXCLUDED.metadata,
                    updated_at = now()
                """,
                (
                    row["id"],
                    row["file_id"],
                    row["chunk_id"],
                    row["document_id"],
                    row["document_version_id"],
                    row["source_id"],
                    row["embedding_literal"],
                    row["dimensions"],
                    row["embedding_model"],
                    row["index_version"],
                    row["metadata"],
                ),
            )
        if prune_stale:
            selected_ids = [row["id"] for row in prepared]
            result = connection.execute(
                """
                DELETE FROM knowledge_vector_index
                WHERE source_id = %s
                  AND NOT (id = ANY(%s))
                """,
                (source_id, selected_ids),
            )
            stale_removed = int(result.rowcount or 0)
    connection.execute("ANALYZE knowledge_vector_index")
    connection.commit()
    return {"upserted": len(prepared), "staleRemoved": stale_removed}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate and backfill one knowledge source from JSONB into pgvector."
    )
    parser.add_argument(
        "--database-url",
        default=os.getenv("AICHECK_DATABASE_URL") or os.getenv("DATABASE_URL") or "",
    )
    parser.add_argument("--source-id", default=DEFAULT_SOURCE_ID)
    parser.add_argument("--dimensions", type=int, default=DEFAULT_DIMENSIONS)
    parser.add_argument("--expected-count", type=int, default=DEFAULT_EXPECTED_COUNT)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--prune-stale", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.database_url:
        raise SystemExit("AICHECK_DATABASE_URL or --database-url is required")
    try:
        import psycopg
    except Exception as exc:
        raise SystemExit(f"psycopg is required: {exc}") from exc

    with psycopg.connect(args.database_url, autocommit=False) as connection:
        source_rows = load_source_rows(connection, args.source_id)
        if len(source_rows) != args.expected_count:
            raise SystemExit(
                f"Source vector gate failed: expected={args.expected_count}, actual={len(source_rows)}"
            )
        prepared = [
            prepare_row(object_id, payload, dimensions=args.dimensions)
            for object_id, payload in source_rows
        ]
        models = sorted({row["embedding_model"] for row in prepared})
        versions = sorted({row["index_version"] for row in prepared})
        if models != [DEFAULT_MODEL] or versions != [DEFAULT_INDEX_VERSION]:
            raise SystemExit(
                f"Source index gate failed: models={models}, indexVersions={versions}"
            )
        before_schema = schema_status(connection)
        before = target_summary(connection, args.source_id)
        applied = None
        if args.apply:
            if not before_schema["extensionAvailable"]:
                raise SystemExit("PostgreSQL server does not provide the vector extension")
            applied = apply_backfill(
                connection,
                prepared,
                source_id=args.source_id,
                prune_stale=args.prune_stale,
            )
        after_schema = schema_status(connection)
        after = target_summary(connection, args.source_id)
        ok = (
            after["count"] == args.expected_count
            and after["dimensionMismatchCount"] == 0
            and after["zeroVectorCount"] == 0
            and after["duplicateChunkCount"] == 0
            and after_schema["hnswReady"]
        ) if args.apply else len(prepared) == args.expected_count
        report = {
            "schemaVersion": "aicheck-knowledge-pgvector-backfill@1",
            "mode": "apply" if args.apply else "dry-run",
            "sourceId": args.source_id,
            "sourceCount": len(source_rows),
            "sourceDigest": canonical_digest(source_rows),
            "dimensions": args.dimensions,
            "embeddingModels": models,
            "indexVersions": versions,
            "schemaBefore": before_schema,
            "schemaAfter": after_schema,
            "targetBefore": before,
            "targetAfter": after,
            "applied": applied,
            "ok": ok,
        }
        print(json.dumps(report, ensure_ascii=False, indent=2 if args.json else None))
        return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
