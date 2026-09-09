"""Scope identity shared by rule selection, replacement and rollback."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from libs.business_pack.loader import DEFAULT_BUSINESS_PACK_ID


def rule_scope(rule: dict[str, Any]) -> tuple[str, str]:
    return (
        str(rule.get("projectId") or ""),
        str(rule.get("businessPackId") or DEFAULT_BUSINESS_PACK_ID),
    )


def same_rule_scope(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return rule_scope(left) == rule_scope(right)


def review_rule_node_ids(rule: dict[str, Any]) -> set[int]:
    node_ids: set[int] = set()
    for raw in rule.get("nodeIds") or []:
        if str(raw).isdigit():
            node_ids.add(int(raw))
    return node_ids


def select_published_rule(rows: list[dict[str, Any]], node_id: int, *, business_pack_id: str | None = None, project_id: str | None = None) -> dict[str, Any] | None:
    candidates = []
    for rule in rows:
        if rule.get("status") != "已发布":
            continue
        if node_id not in review_rule_node_ids(rule):
            continue
        owner_project, owner_pack = rule_scope(rule)
        if owner_project and owner_project != project_id:
            continue
        if owner_pack != (business_pack_id or DEFAULT_BUSINESS_PACK_ID):
            continue
        candidates.append(rule)
    candidates.sort(
        key=lambda item: (
            bool(project_id and rule_scope(item)[0] == project_id),
            str(item.get("publishedAt") or item.get("updatedAt") or item.get("importedAt") or ""),
        ),
        reverse=True,
    )
    return deepcopy(candidates[0]) if candidates else None
