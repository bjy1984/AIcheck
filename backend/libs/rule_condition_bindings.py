"""Compile explicit condition-to-atomic-item replacements without dropping other checks."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from libs.review_rule_snapshot import _hash
from libs.rule_conditions import validate_conditions


def compile_condition_bindings(rule: dict[str, Any], pack: dict[str, Any]) -> dict[str, Any]:
    conditions = validate_conditions(rule.get("executionConditions"))
    nodes = rule.get("nodeIds") or []
    if len(nodes) != 1 or isinstance(nodes[0], bool) or not str(nodes[0]).isdigit():
        raise ValueError("condition_bindings_require_single_node")
    node_id = int(nodes[0])
    if rule.get("businessPackId") != pack.get("id"):
        raise ValueError("condition_binding_pack_mismatch")
    atomic_rows = [row for row in pack.get("atomicChecks") or [] if row.get("nodeId") == node_id]
    allowed = {row["id"] for row in atomic_rows}
    if not allowed or len(allowed) != len(atomic_rows):
        raise ValueError("condition_binding_atomic_catalog_invalid")
    bindings = [row for row in pack.get("atomicCheckToolBindings") or [] if row.get("atomicCheckId") in allowed]
    if {row["atomicCheckId"] for row in bindings} != allowed or len(bindings) != len(allowed):
        raise ValueError("condition_binding_base_plan_incomplete")
    grouped: dict[str, list[dict[str, Any]]] = {}
    for check in conditions["checks"]:
        target = check.get("atomicCheckId")
        if not isinstance(target, str) or target not in allowed:
            raise ValueError("condition_binding_target_missing_or_outside_node")
        grouped.setdefault(target, []).append(deepcopy(check))
    entries = [{"atomicCheckId": target, "mode": "replace", "conditions": {
        "schemaVersion": conditions["schemaVersion"], "checks": checks,
        **({"applicability": deepcopy(conditions["applicability"])} if "applicability" in conditions else {}),
    }} for target, checks in sorted(grouped.items())]
    plan = {"schemaVersion": "rule-condition-bindings-v1", "businessPackId": pack["id"], "nodeId": node_id,
            "ruleVersionId": rule.get("id"), "ruleRevision": rule.get("revision"),
            "conditionsHash": _hash(conditions), "baseBindingsHash": _hash({"bindings": bindings}),
            "replacements": entries, "retainedAtomicCheckIds": sorted(allowed - grouped.keys()),
            "formalExecutable": False}
    plan["planHash"] = _hash(plan)
    return plan
