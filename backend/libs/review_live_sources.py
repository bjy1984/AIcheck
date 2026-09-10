"""Revalidate handoff dependencies from a consistent database read at workflow gates."""
from __future__ import annotations

from libs.db.review_handoff_loading import load_handoff_rows
from libs.integrations.errors import IntegrationServiceError
from libs.review_document_scope import ensure_document_sources


def ensure_live_document_sources(run, state, *, repository=None):
    ensure_document_sources(run, state)
    if "handoffInputsSnapshot" not in run:
        return
    if repository is None:
        from libs.db.repository import repo
        repository = repo
    connection = repository.sync_postgres
    if connection is None:
        return  # In-memory/SQLite mode retains its existing source contract.
    import os

    import psycopg

    # psycopg 的 connection.info.dsn **不含口令**（它按 libpq 的规矩把 password 剥掉），
    # 用它开新连接在需要口令认证的库上必然 fe_sendauth 失败，本检查就会一路 503——
    # 等于这道核验从未真正生效。所以用仓库自己保存的完整 DSN，解析顺序与
    # repository.configure_sync_postgres 保持一致。
    dsn = (getattr(repository, "postgres_dsn", None)
           or os.getenv("AICHECK_DATABASE_URL")
           or os.getenv("DATABASE_URL"))
    if not dsn:
        raise IntegrationServiceError("review", "validate_live_handoffs", status_code=503,
                                      reason="HANDOFF_SOURCE_CHECK_UNAVAILABLE")

    try:
        # A separate read transaction avoids committing caller writes, mutating shared
        # caches, or depending on an old worker connection's transaction snapshot.
        with psycopg.connect(dsn) as fresh:
            fresh.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            rows, _, _ = load_handoff_rows(fresh, run, run["tenantId"])
            current = {"review_runs": [run]}
            for collection, _, payload in rows:
                current.setdefault(collection, []).append(payload)
            ensure_document_sources(run, current)
    except psycopg.Error as exc:
        raise IntegrationServiceError("review", "validate_live_handoffs", status_code=503,
                                      reason="HANDOFF_SOURCE_CHECK_UNAVAILABLE") from exc
