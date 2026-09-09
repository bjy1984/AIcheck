"""Resolve explicit material requirements without inferring them from file order."""
from __future__ import annotations

from typing import Any


def resolve_binding_requirement(
    state: dict[str, Any], project_id: str, node_id: int, requirement_id: Any,
) -> dict[str, Any] | None:
    if requirement_id is None or requirement_id == "":
        return None  # Supplemental evidence does not satisfy a named requirement by default.
    if not isinstance(requirement_id, str):
        raise TypeError("requirementId 必须是字符串")
    matches = [
        row for row in state.get("requirements", [])
        if row.get("id") == requirement_id and row.get("projectId") == project_id
        and str(row.get("nodeId")) == str(node_id)
    ]
    if len(matches) != 1:
        raise ValueError("资料要求不存在、不属于当前工程节点或存在重复记录")
    return matches[0]
