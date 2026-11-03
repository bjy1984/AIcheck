from __future__ import annotations

import os
import re
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


TENANT_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")


def valid_tenant_id(value: Any) -> str | None:
    """形如 TENANT-xxx 的院 id 原样返回，其余返回 None（任务消息头、登录体都是外来值）。"""
    text = str(value or "").strip()
    return text if TENANT_ID_RE.fullmatch(text) else None


def tenant_scoped_name(name: str, tenant_id: str | None = None) -> str:
    """部署默认院以外的院，存储路径、锁键前面加 tenants/<院>/。

    2026-11-02 多特检院：两个院的项目号、文档版本号可能相同，对象存储路径
    documents/{project}/{version} 和任务锁会互相覆盖、互相挡住。默认院不加前缀，
    已有的文件和锁不用迁移；已经带了本院前缀的不再重复加。
    """
    tenant = str(tenant_id or current_tenant_id())
    normalized = str(name or "").lstrip("/")
    if tenant == configured_tenant_id():
        return normalized
    prefix = f"tenants/{tenant}/"
    return normalized if normalized.startswith(prefix) else f"{prefix}{normalized}"


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
