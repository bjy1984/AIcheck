from __future__ import annotations

import os
from typing import Any

from libs.integrations.storage import object_storage

from .repository import flush_state, repo
from .seed import ensure_test_project_members


def postgres_dsn() -> str | None:
    return os.getenv("AICHECK_DATABASE_URL") or os.getenv("DATABASE_URL")


def postgres_enabled() -> bool:
    return bool(postgres_dsn())


async def init_postgres_if_configured(app: Any) -> None:
    dsn = postgres_dsn()
    if not dsn:
        repo.configure_sqlite()
        repo.load_from_sqlite()
        bootstrap_local_roles_if_configured()
        app.state.postgres = None
        app.state.postgres_error = None
        app.state.sqlite = repo.sqlite_path
        return
    try:
        repo.configure_sync_postgres(dsn)
        repo.ensure_postgres_schema()
        repo.load_from_sync_postgres()
        object_storage.ensure_buckets()
        app.state.postgres = dsn
        app.state.postgres_error = None
        app.state.sqlite = None
    except Exception as exc:
        if os.getenv("AICHECK_SQLITE_FALLBACK", "true").lower() == "false":
            raise
        repo.close_sync_postgres()
        repo.postgres_dsn = None
        repo.postgres_enabled = False
        repo.configure_sqlite()
        repo.load_from_sqlite()
        bootstrap_local_roles_if_configured()
        app.state.postgres = None
        app.state.postgres_error = str(exc)
        app.state.sqlite = repo.sqlite_path


def bootstrap_local_roles_if_configured() -> None:
    if os.getenv("AICHECK_BOOTSTRAP_LOCAL_ROLES", "false").lower() != "true":
        return
    from scripts.create_roles import (
        apply_role_bootstrap_to_state,
        resolve_role_passwords,
        selected_roles,
    )

    roles = selected_roles(os.getenv("AICHECK_BOOTSTRAP_LOCAL_ROLE_LIST", "admin,inspection,contractor,ndt,owner,fde"))
    project_id = os.getenv("AICHECK_DEFAULT_PROJECT_ID", "P-2026-HDCP-001")
    passwords = resolve_role_passwords(roles)
    apply_role_bootstrap_to_state(roles, project_id, passwords=passwords, rotate_passwords=False)
    ensure_test_project_members(
        repo.state.get("projects", []),
        repo.state.setdefault("project_members", []),
        repo.state.get("tree_nodes", []),
    )
    flush_state()


async def close_postgres(app: Any) -> None:
    repo.close_sync_postgres()
    app.state.postgres = None
    app.state.sqlite = None


async def run_transaction_probe(dsn: str | None = None) -> dict[str, Any]:
    configured_dsn = dsn or postgres_dsn()
    payload: dict[str, Any] = {
        "postgresEnabled": bool(configured_dsn),
        "transactionsConfigured": bool(configured_dsn),
        "transactionProbe": "skipped",
    }
    if not configured_dsn:
        payload["reason"] = "postgres_not_configured"
        return payload

    try:
        with repo.postgres_connection(configured_dsn) as connection:
            with connection.transaction():
                probe = connection.execute(
                    "SELECT current_database(), pg_is_in_recovery(), txid_current()"
                ).fetchone()
                if not probe or not probe[0]:
                    raise RuntimeError("PostgreSQL transaction probe returned no database identity")
    except Exception as exc:
        payload.update(
            {
                "transactionProbe": "failed",
                "reason": "transaction_probe_failed",
                "errorType": type(exc).__name__,
            }
        )
        return payload

    payload["transactionProbe"] = "pass"
    return payload
