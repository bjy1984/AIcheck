"""Expose recorded approval checks, without rewriting findings or persisted runs."""
from copy import deepcopy


def recorded_approval_checks(atomic):
    if atomic.get("atomicCheckId") != "AC-R11-01":
        return []
    rows = []
    for tool in atomic.get("toolResults") or []:
        if not isinstance(tool, dict) or tool.get("toolName") != "evaluate_construction_plan":
            continue
        facts = tool.get("facts")
        if not isinstance(facts, dict):
            continue
        for check in facts.get("approvalChecks") or []:
            if not isinstance(check, dict) or not isinstance(check.get("code"), str):
                continue
            rows.append({key: deepcopy(check[key]) for key in
                         ("code", "result", "usageId", "approvedAt", "startedAt", "evidenceRefs") if key in check})
    return rows
