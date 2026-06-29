from __future__ import annotations

import os
from typing import Any
from uuid import uuid4

from libs.integrations.storage import object_storage

from .repository import repo


def postgres_dsn() -> str | None:
    return os.getenv("AICHECK_DATABASE_URL") or os.getenv("DATABASE_URL")


def postgres_enabled() -> bool:
    return bool(postgres_dsn())


async def init_postgres_if_configured(app: Any) -> None:
    dsn = postgres_dsn()
    if not dsn:
        bootstrap_local_roles_if_configured()
        app.state.postgres = None
        return
    repo.configure_sync_postgres(dsn)
    repo.ensure_postgres_schema()
    repo.load_from_sync_postgres()
    object_storage.ensure_buckets()
    app.state.postgres = dsn


def bootstrap_local_roles_if_configured() -> None:
    if os.getenv("AICHECK_BOOTSTRAP_LOCAL_ROLES", "false").lower() != "true":
        return
    from scripts.create_roles import build_plan, resolve_role_passwords, selected_roles

    roles = selected_roles(os.getenv("AICHECK_BOOTSTRAP_LOCAL_ROLE_LIST", "admin,inspection,contractor,ndt,owner,fde"))
    project_id = os.getenv("AICHECK_DEFAULT_PROJECT_ID", "P-2026-HDCP-001")
    passwords = resolve_role_passwords(roles)
    plan = build_plan(roles, project_id, passwords=passwords, show_passwords=False)
    repo.state["users"] = plan["authUsers"]
    repo.state["roles"] = plan["authRoles"]
    repo.state["project_members"] = plan["projectMembers"]
    repo.state["admin_config"] = plan["adminConfigPayload"]


async def close_postgres(app: Any) -> None:
    repo.close_sync_postgres()
    app.state.postgres = None


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

    probe_id = f"postgres-transaction-probe-{uuid4().hex}"
    try:
        with repo.postgres_connection(configured_dsn) as connection:
            with connection.transaction():
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS _deployment_probes (
                        id text PRIMARY KEY,
                        purpose text NOT NULL,
                        created_at timestamptz NOT NULL DEFAULT now()
                    )
                    """
                )
                connection.execute(
                    "INSERT INTO _deployment_probes (id, purpose) VALUES (%s, %s)",
                    (probe_id, "deployment-transaction-probe"),
                )
                connection.execute("DELETE FROM _deployment_probes WHERE id = %s", (probe_id,))
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
