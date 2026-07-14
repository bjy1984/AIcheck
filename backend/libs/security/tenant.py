from __future__ import annotations

import os
from contextvars import ContextVar, Token
from typing import Any


DEFAULT_TENANT_ID = "TENANT-DEFAULT"
_request_tenant_id: ContextVar[str | None] = ContextVar("aicheck_request_tenant_id", default=None)


def configured_tenant_id() -> str:
    return str(os.getenv("AICHECK_TENANT_ID") or DEFAULT_TENANT_ID).strip() or DEFAULT_TENANT_ID


def tenant_mode() -> str:
    return str(os.getenv("AICHECK_TENANT_MODE") or "shared").strip().lower() or "shared"


def tenant_is_allowed(tenant_id: str) -> bool:
    """Enforce the deployment boundary for single-tenant/isolated processes."""

    canonical = str(tenant_id or "").strip()
    if not canonical:
        return False
    return tenant_mode() != "isolated" or canonical == configured_tenant_id()


def current_tenant_id() -> str:
    """Return the authenticated request/worker tenant, falling back to deployment default."""

    return _request_tenant_id.get() or configured_tenant_id()


def set_request_tenant_id(tenant_id: str) -> Token[str | None]:
    canonical = str(tenant_id or "").strip()
    if not canonical:
        raise ValueError("tenant_id must be non-empty")
    return _request_tenant_id.set(canonical)


def reset_request_tenant_id(token: Token[str | None]) -> None:
    _request_tenant_id.reset(token)


def tenant_id_for_record(record: dict[str, Any] | None) -> str:
    if not isinstance(record, dict):
        return current_tenant_id()
    return str(record.get("tenantId") or record.get("tenant_id") or current_tenant_id())


def apply_default_tenant(value: Any, *, tenant_id: str | None = None) -> Any:
    """Backfill legacy in-memory records with the canonical tenant boundary.

    PostgreSQL migrations persist the field.  This helper keeps SQLite/demo/test
    records on the same authorization path and deliberately never trusts a
    request-provided tenant value.
    """

    canonical = str(tenant_id or current_tenant_id())
    if isinstance(value, dict):
        value.setdefault("tenantId", canonical)
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                item.setdefault("tenantId", canonical)
    return value
