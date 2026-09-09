from __future__ import annotations

from typing import Any

from libs.rule_scope import same_rule_scope


def rule_version_sort_key(item: dict[str, Any]) -> tuple[int, int, str, str]:
    sequence = item.get("sourceSequence")
    if sequence is None:
        node_ids = item.get("nodeIds") or []
        sequence = min((int(node_id) for node_id in node_ids if str(node_id).isdigit()), default=9999)
    try:
        sequence_value = int(sequence)
    except (TypeError, ValueError):
        sequence_value = 9999
    status_rank = {"草稿": 0, "待发布": 1, "已发布": 2, "已回滚": 3}.get(str(item.get("status") or ""), 9)
    return (sequence_value, status_rank, str(item.get("updatedAt") or ""), str(item.get("id") or ""))


def rule_version_changes(base: dict[str, Any], target: dict[str, Any] | None) -> list[dict[str, Any]]:
    compared_fields = [
        ("inspectionCategory", "监检项目（大类）"),
        ("inspectionItem", "监检项目（内容）"),
        ("inspectionClass", "类别"),
        ("standardText", "判断准则 / 标准规范"),
        ("witnessText", "方法及内容 / 工作见证"),
        ("nodeIds", "适用节点"),
        ("status", "状态"),
        ("executionConditions", "可执行条件"),
    ]
    changes = []
    for field, label in compared_fields:
        before = (target or {}).get(field)
        after = base.get(field)
        if before != after:
            changes.append(
                {
                    "field": field,
                    "label": label,
                    "before": before,
                    "after": after,
                    "severity": "warning" if field in {"nodeIds", "standardText", "witnessText"} else "info",
                    "changeType": "added" if not before and after else "removed" if before and not after else "changed",
                }
            )
    return changes


def matching_rule_target(
    rows: list[dict[str, Any]],
    base: dict[str, Any],
    *,
    target_version_id: str | None = None,
    target_version: str | None = None,
) -> dict[str, Any] | None:
    target = next((row for row in rows if row.get("id") == target_version_id), None) if target_version_id else None
    if target is None and target_version:
        target = next(
            (
                item
                for item in rows
                if item.get("version") == target_version
                and same_rule_scope(base, item)
                and (not base.get("ruleKey") or item.get("ruleKey") == base.get("ruleKey"))
            ),
            None,
        )
    if target and not same_rule_scope(base, target):
        return None
    if target and base.get("ruleKey") and target.get("ruleKey") != base.get("ruleKey"):
        return None
    return target


def rule_operation_fingerprint_payload(rows, base, target, *, normalize_rule_status, parse_rule_node_ids):
    affected = [
        item
        for item in rows
        if item.get("id") in {base.get("id"), (target or {}).get("id")}
        or (
            same_rule_scope(base, item)
            and normalize_rule_status(item.get("status")) == "已发布"
            and (
                bool(base.get("ruleKey") and item.get("ruleKey") == base.get("ruleKey"))
                or bool(set(parse_rule_node_ids(base.get("nodeIds"))) & set(parse_rule_node_ids(item.get("nodeIds"))))
            )
        )
    ]
    return [
            {
                "id": item.get("id"),
                "revision": item.get("revision"),
                "updatedAt": item.get("updatedAt"),
                "status": item.get("status"),
                "nodeIds": item.get("nodeIds"),
            }
            for item in sorted(affected, key=lambda row: str(row.get("id") or ""))
    ]


def rule_diff_payload(base: dict[str, Any], target: dict[str, Any] | None, *, versioned_record, compared_at: str) -> dict[str, Any]:
    changes = rule_version_changes(base, target)
    return {
        "base": versioned_record("rule-version", base),
        "target": versioned_record("rule-version", target) if target else None,
        "comparedAt": compared_at,
        "summary": {
            "added": len([item for item in changes if item["changeType"] == "added"]),
            "changed": len([item for item in changes if item["changeType"] == "changed"]),
            "removed": len([item for item in changes if item["changeType"] == "removed"]),
            "warning": len([item for item in changes if item["severity"] == "warning"]),
        },
        "changes": changes,
    }


def rule_operation_diff(rows, base, target, action, *, versioned_record, compared_at):
    if action == "rollback":
        return rule_diff_payload({**target, "status": "已发布"}, base, versioned_record=versioned_record, compared_at=compared_at)
    base = {**base, "status": "已发布"}
    affected = [row for row in rows if row.get("id") != base.get("id") and row.get("status") == "已发布"
                and same_rule_scope(base, row) and (
                    (base.get("ruleKey") and base.get("ruleKey") == row.get("ruleKey"))
                    or bool(set(base.get("nodeIds") or []) & set(row.get("nodeIds") or [])))]
    result = rule_diff_payload(base, affected[0] if len(affected) == 1 else None,
                              versioned_record=versioned_record, compared_at=compared_at)
    if affected:
        result["changes"] = [{**change, "fromRuleVersionId": row["id"]}
                             for row in sorted(affected, key=lambda row: row["id"])
                             for change in rule_version_changes(base, row)]
        result["summary"] = {kind: sum(change["changeType"] == kind for change in result["changes"])
                             for kind in ("added", "changed", "removed")}
        result["summary"]["warning"] = sum(change["severity"] == "warning" for change in result["changes"])
    result["affectedRuleVersionIds"] = [row["id"] for row in affected]
    return result
