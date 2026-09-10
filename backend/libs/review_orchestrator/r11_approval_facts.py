"""Freeze sourced R11 approval records separately from parameter comparison inputs."""
from copy import deepcopy

from libs.review_orchestrator.deterministic_tools import validate_evidence_grounding
from libs.review_orchestrator.material_facts import build_material_judgment

TABLES = {"construction_approval_context": "approvalContexts", "construction_approval_signatures": "approvalSignatures",
          "construction_owner_approval": "ownerApprovals"}


def approval_arguments(run, groups, issues):
    if len(groups["approvalContexts"]) != 1:
        return None
    context = groups["approvalContexts"][0]
    if context.get("planVersionId") not in run.get("inputDocumentVersionIds", []):
        return None
    records = [(name, groups[name], ("signatureStatus", "decision", "projectId")) for name in TABLES.values()]
    rows = [row for _, items, _ in records for row in items]
    if any(type(row["evidence"].get("confidence")) not in (int, float) or not .75 <= row["evidence"]["confidence"] <= 1 for row in rows):
        return None
    judgment = build_material_judgment(records)["judgment"]
    if validate_evidence_grounding({**judgment, "facts": judgment["claimedFacts"], "minConfidence": .75})["result"] != "passed":
        return None
    return {"projectId": run["projectId"], "scope": deepcopy(context), "signatures": deepcopy(groups["approvalSignatures"]),
            "ownerApproval": deepcopy(groups["ownerApprovals"][0]) if len(groups["ownerApprovals"]) == 1 else None,
            "selectionIssues": deepcopy(issues)}
