"""Reconcile a sourced inventory of application events before first-use aggregation."""
from copy import deepcopy

from libs.review_orchestrator.deterministic_tools import result
from libs.review_tools.r39_tools import _refs, _text


def evaluate_application_inventory(arguments, fields, evaluate_one):
    inventory, applications = arguments.get("inventory"), arguments.get("applications")
    required, seen = set(), set()
    outputs, member_refs = [], []
    valid, invalid = False, False

    def finish(status, reason):
        output = result("evaluate_r39_first_use_validation", status,
            facts={"scope": "declared_complete_application_inventory", "reason": reason,
                   "applicationResults": outputs, "validationEffectiveness": "not_evaluated",
                   "wholeRuleAcceptance": "not_evaluated", "evidenceVerified": False,
                   "coverage": {"inventoryValidated": valid, "requiredCount": len(required) if valid else None,
                                "comparedCount": len(outputs), "complete": valid and not invalid and required == seen and all(
                                    row["result"] in {"passed", "failed", "not_applicable"} for row in outputs),
                                "missingApplications": [dict(zip(fields, key, strict=True)) for key in sorted(required - seen)] if valid else []}},
            checks=[], rule_version="r39-application-inventory-v1")
        output["evidenceRefs"] = deepcopy([*(_refs(inventory) if isinstance(inventory, dict) else []),
            *member_refs, *[ref for row in outputs for ref in row.get("evidenceRefs", [])]])
        return output

    if (not isinstance(inventory, dict) or inventory.get("projectId") != arguments.get("projectId")
            or inventory.get("complete") is not True or not _refs(inventory)):
        return finish("evidence_insufficient", "r39_complete_application_inventory_missing")
    members = inventory.get("members")
    if not isinstance(members, list) or not members or not isinstance(applications, list):
        return finish("evidence_insufficient", "r39_application_inventory_members_missing")
    for member in members:
        if (not isinstance(member, dict) or member.get("projectId") != arguments.get("projectId")
                or any(not _text(member.get(field)) for field in fields) or not _refs(member)):
            return finish("evidence_insufficient", "r39_application_inventory_member_invalid")
        key = tuple(member[field] for field in fields)
        if key in required:
            return finish("evidence_insufficient", "r39_application_inventory_member_duplicate")
        required.add(key)
        member_refs.extend(_refs(member))
    valid = True
    candidates = {}
    for application in applications:
        if not isinstance(application, dict) or {"inventory", "applications"} & application.keys():
            invalid = True
            continue
        scope = application.get("scope")
        if not isinstance(scope, dict) or any(not _text(scope.get(field)) for field in fields):
            invalid = True
            continue
        key = tuple(scope[field] for field in fields)
        if key not in required or application.get("projectId") != arguments.get("projectId"):
            invalid = True
            continue
        candidates.setdefault(key, []).append(application)
    for key, matches in sorted(candidates.items()):
        if len(matches) != 1:
            invalid = True
            continue
        seen.add(key)
        output = evaluate_one(matches[0])
        output["applicationScope"] = deepcopy(matches[0]["scope"])
        outputs.append(output)
    statuses = {row["result"] for row in outputs}
    if "failed" in statuses:
        return finish("failed", "r39_known_application_validation_failure")
    if invalid:
        return finish("evidence_insufficient", "r39_application_invalid_or_duplicate")
    if required != seen or "evidence_insufficient" in statuses:
        return finish("evidence_insufficient", "r39_application_inventory_incomplete")
    return finish("not_applicable" if statuses == {"not_applicable"} else "passed", "r39_application_inventory_compared")
