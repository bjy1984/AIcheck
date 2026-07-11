from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Any


_request_audit_context: ContextVar[dict[str, Any] | None] = ContextVar(
    "aicheck_request_audit_context",
    default=None,
)


def set_request_audit_context(value: dict[str, Any]) -> Token:
    return _request_audit_context.set(value)


def reset_request_audit_context(token: Token) -> None:
    _request_audit_context.reset(token)


def current_request_audit_context() -> dict[str, Any]:
    return dict(_request_audit_context.get() or {})
