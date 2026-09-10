"""Freeze sourced R11 approval records separately from parameter comparison inputs."""
from copy import deepcopy

from libs.review_orchestrator.deterministic_tools import validate_evidence_grounding
from libs.review_orchestrator.material_facts import build_material_judgment

TABLES = {"construction_approval_context": "approvalContexts", "construction_approval_signatures": "approvalSignatures",
          "construction_owner_approval": "ownerApprovals", "construction_plan_usage": "planUsages",
          "construction_plan_usage_inventory": "usageInventories"}


def approval_arguments(run, groups, issues):
    if len(groups["approvalContexts"]) != 1:
        return None
    context = groups["approvalContexts"][0]
    if context.get("planVersionId") not in run.get("inputDocumentVersionIds", []):
        return None
    def trusted(row):
        confidence = row.get("evidence", {}).get("confidence")
        if (type(confidence) not in (int, float) or not .75 <= confidence <= 1
                or type(row.get("conflicted", False)) is not bool):
            return False
        judgment = build_material_judgment([("approval", [row], ("signatureStatus", "decision", "projectId"))])["judgment"]
        return validate_evidence_grounding({**judgment, "facts": judgment["claimedFacts"], "minConfidence": .75})["result"] == "passed"

    if not trusted(context):
        return None
    groups = deepcopy(groups)
    issues = deepcopy(issues)
    for name in TABLES.values():
        for row in groups[name]:
            if not trusted(row):
                # Preserve identity/cardinality so an untrusted duplicate cannot
                # disappear and turn the remaining row into a unique match.
                row["evidenceRefs"] = []
                issues.append({"code": "r11_approval_record_source_untrusted", "recordGroup": name,
                               "documentVersionId": row.get("documentVersionId"),
                               "usageId": row.get("usageId"), "role": row.get("role")})
    grounded = [(name, [row for row in groups[name] if row.get("evidenceRefs")],
                 ("signatureStatus", "decision", "projectId")) for name in TABLES.values()]
    arguments = {"projectId": run["projectId"], "scope": deepcopy(context), "signatures": deepcopy(groups["approvalSignatures"]),
            "ownerApproval": deepcopy(groups["ownerApprovals"][0]) if len(groups["ownerApprovals"]) == 1 else None,
            "planUsage": deepcopy(groups["planUsages"][0]) if len(groups["planUsages"]) == 1 else None,
            "selectionIssues": deepcopy(issues),
            "sourceJudgment": build_material_judgment(grounded)["judgment"]}

    if groups["usageInventories"] or len(groups["planUsages"]) > 1:
        arguments["planUsages"] = deepcopy(groups["planUsages"])
        arguments["usageInventory"] = deepcopy(groups["usageInventories"][0]) if len(groups["usageInventories"]) == 1 else None
    return arguments
