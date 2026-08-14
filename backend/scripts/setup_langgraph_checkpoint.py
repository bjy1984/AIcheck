from __future__ import annotations

import os

REQUIRED_TABLES = {
    "checkpoints",
    "checkpoint_blobs",
    "checkpoint_writes",
    "checkpoint_migrations",
}


def setup_checkpoint_schema(dsn: str) -> None:
    from langgraph.checkpoint.postgres import PostgresSaver

    context = PostgresSaver.from_conn_string(dsn)
    if hasattr(context, "__enter__"):
        with context as saver:
            saver.setup()
        return
    context.setup()


def verify_checkpoint_schema(dsn: str) -> set[str]:
    import psycopg

    with psycopg.connect(dsn) as connection:
        rows = connection.execute(
            "SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname = 'public'"
        ).fetchall()
    return {str(row[0]) for row in rows} & REQUIRED_TABLES


def main() -> int:
    dsn = os.getenv("LANGGRAPH_CHECKPOINT_DSN", "").strip()
    if not dsn:
        raise RuntimeError("LANGGRAPH_CHECKPOINT_DSN is required")
    setup_checkpoint_schema(dsn)
    found = verify_checkpoint_schema(dsn)
    missing = sorted(REQUIRED_TABLES - found)
    if missing:
        raise RuntimeError(f"LangGraph checkpoint schema is incomplete: {', '.join(missing)}")
    print(f"LangGraph checkpoint schema ready: {', '.join(sorted(found))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
