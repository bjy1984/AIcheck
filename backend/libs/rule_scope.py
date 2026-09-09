"""Scope identity shared by rule selection, replacement and rollback."""
from __future__ import annotations

from typing import Any

from libs.business_pack.loader import DEFAULT_BUSINESS_PACK_ID


def rule_scope(rule: dict[str, Any]) -> tuple[str, str]:
    return (
        str(rule.get("projectId") or ""),
        str(rule.get("businessPackId") or DEFAULT_BUSINESS_PACK_ID),
    )


def same_rule_scope(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return rule_scope(left) == rule_scope(right)
