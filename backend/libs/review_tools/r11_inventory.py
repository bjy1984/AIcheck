"""Reconcile every declared comparison object before aggregating R11 parameters."""
from libs.review_orchestrator.deterministic_tools import result
from libs.review_tools.r39_tools import _refs, _text


def evaluate_inventory(arguments, evaluate_one):
    inventory = arguments.get("inventory")
    comparisons = arguments.get("objectComparisons")
    outputs = []

    def finish(status, reason):
        value = result("evaluate_r11_project_parameters", status,
                       facts={"scope": "declared_complete_object_inventory", "reason": reason,
                              "objectResults": outputs, "wholeRuleAcceptance": "not_evaluated"},
                       checks=[], rule_version="r11-project-parameter-inventory-v1")
        value["evidenceRefs"] = [*_refs(inventory or {}), *[ref for item in outputs for ref in item.get("evidenceRefs", [])]]
        return value

    if (not isinstance(inventory, dict) or inventory.get("projectId") != arguments.get("projectId")
            or inventory.get("complete") is not True or not _refs(inventory)):
        return finish("evidence_insufficient", "r11_complete_object_inventory_missing")
    members = inventory.get("members")
    if not isinstance(members, list) or not members or not isinstance(comparisons, list):
        return finish("evidence_insufficient", "r11_inventory_members_missing")
    required = set()
    for member in members:
        if (not isinstance(member, dict) or member.get("projectId") != arguments.get("projectId")
                or not _refs(member) or any(not _text(member.get(key)) for key in ("objectType", "objectId", "planVersionId", "designVersionId"))):
            return finish("evidence_insufficient", "r11_inventory_member_invalid")
        key = tuple(member[field] for field in ("objectType", "objectId", "planVersionId", "designVersionId"))
        if key in required:
            return finish("evidence_insufficient", "r11_inventory_member_duplicate")
        required.add(key)
    seen = set()
    for comparison in comparisons:
        if not isinstance(comparison, dict) or {"inventory", "objectComparisons"} & comparison.keys():
            return finish("evidence_insufficient", "r11_nested_inventory_invalid")
        scope = comparison.get("scope", {}) if isinstance(comparison, dict) else {}
        key = tuple(scope.get(field) for field in ("objectType", "objectId", "planVersionId", "designVersionId"))
        if any(not _text(value) for value in key) or key in seen or key not in required or comparison.get("projectId") != arguments.get("projectId"):
            return finish("evidence_insufficient", "r11_comparison_object_unexpected_or_duplicate")
        seen.add(key)
        output = evaluate_one(comparison)
        output["objectScope"] = scope.copy()
        outputs.append(output)
    statuses = {item["result"] for item in outputs}
    if "failed" in statuses:
        return finish("failed", "r11_known_parameter_difference")
    if seen != required or "evidence_insufficient" in statuses:
        return finish("evidence_insufficient", "r11_inventory_comparison_incomplete")
    return finish("not_applicable" if statuses == {"not_applicable"} else "passed", "r11_all_inventory_objects_compared")
