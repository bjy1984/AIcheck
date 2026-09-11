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
    candidates.sort(key=lambda item: _rule_preference(item, project_id), reverse=True)
    return deepcopy(candidates[0]) if candidates else None


def _rule_preference(rule: dict[str, Any], project_id: str | None) -> tuple[Any, ...]:
    """越大越优先：项目内规则 > 发布时间新 > 覆盖节点少 > 规则 id 大。

    第三项（覆盖节点少者优先）是 2026-09-11 加的。老种子 `RULE-WELDER-202606`
    （焊工资格核验）一条规则声明 nodeIds [24, 25, 27, 28]，与业务包里
    R25/R27 的 publishedAt 完全相同（06-26 09:12），并列时只靠入参顺序决胜——
    实测节点 25/27 侥幸取到了对的规则，但这不牢靠。声明「只管这一个节点」的规则
    比「一口气管四个」的更贴近该节点，先取窄的。第四项只为可复现，不含业务含义。
    """
    return (
        bool(project_id and rule_scope(rule)[0] == project_id),
        str(rule.get("publishedAt") or rule.get("updatedAt") or rule.get("importedAt") or ""),
        -len(review_rule_node_ids(rule)),
        str(rule.get("id") or ""),
    )
