"""Documented plan signatures, owner reply and use order; not signature authentication."""
from copy import deepcopy

from libs.review_orchestrator.deterministic_tools import check, result
from libs.review_tools.r11_approval_timing import approval_timing
from libs.review_tools.r39_tools import _refs, _text

SCOPE_FIELDS = ("projectId", "planVersionId", "ownerOrganizationId", "approvalCycleId")
ROLES = ("编制", "审核", "审批")


def evaluate_r11_approval(arguments):
    rows = []

    def add(code, status, refs=()):
        rows.append({"code": code, "result": status, "evidenceRefs": deepcopy(list(refs))})

    def finish():
        statuses = {row["result"] for row in rows}
        status = "failed" if "failed" in statuses else "evidence_insufficient" if "evidence_insufficient" in statuses else "passed"
        if arguments.get("selectionIssues") and status == "passed":
            status = "evidence_insufficient"
        output = result("evaluate_construction_plan", status,
            facts={"scope": "documented_plan_signatures_owner_reply_and_use_order_only", "wholeRuleAcceptance": "not_evaluated",
                   "evidenceVerified": False, "approvalChecks": rows, "selectionIssues": deepcopy(arguments.get("selectionIssues") or [])},
            checks=[check(row["code"], row["result"] == "passed", row["result"], "passed") for row in rows],
            rule_version="r11-documented-plan-approval-v2")
        output["evidenceRefs"] = [ref for row in rows for ref in row["evidenceRefs"]]
        return output

    scope = arguments.get("scope")
    if (not isinstance(scope, dict) or any(not _text(scope.get(key)) for key in SCOPE_FIELDS)
            or scope["projectId"] != arguments.get("projectId") or not _refs(scope)
            or scope.get("completePlanSet") is not True or scope.get("planVersionIds") != [scope["planVersionId"]]):
        add("r11_approval_scope_incomplete", "evidence_insufficient")
        return finish()

    def matches(row):
        return isinstance(row, dict) and all(row.get(key) == scope[key] for key in SCOPE_FIELDS) and bool(_refs(row))

    signatures = arguments.get("signatures")
    if not isinstance(signatures, list) or any(not matches(row) or row.get("role") not in ROLES for row in signatures):
        add("r11_signature_source_or_role_ambiguous", "evidence_insufficient")
    else:
        for role in ROLES:
            matches_role = [row for row in signatures if row["role"] == role]
            if len(matches_role) != 1:
                add(f"r11_signature_{role}_unresolved", "evidence_insufficient")
                continue
            row = matches_role[0]
            status = row.get("signatureStatus")
            if any(ref["documentVersionId"] != scope["planVersionId"] for ref in _refs(row)):
                status = "unknown"
            outcome = "passed" if status == "present" and _text(row.get("signerName")) else "failed" if status == "absent" else "evidence_insufficient"
            add(f"r11_signature_{role}", outcome, _refs(row))
    approval = arguments.get("ownerApproval")
    if not matches(approval):
        add("r11_owner_reply_scope_unresolved", "evidence_insufficient")
    else:
        status = approval.get("decision")
        outcome = "passed" if status == "approved" else "failed" if status == "rejected" else "evidence_insufficient"
        add("r11_owner_reply", outcome, _refs(approval))
    rows.append(approval_timing(scope, approval, arguments.get("planUsage")))
    return finish()
