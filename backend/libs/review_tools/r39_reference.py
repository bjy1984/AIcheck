"""Compare a sourced instruction reference against a selected procedure revision."""
from __future__ import annotations

from copy import deepcopy

from libs.review_orchestrator.deterministic_tools import check, result
from libs.review_tools.r39_tools import _refs, _text

SCOPE_FIELDS = ("projectId", "organizationId", "instructionDocumentId", "instructionDocumentVersionId",
                "procedureDocumentId", "procedureDocumentVersionId", "method")


def evaluate_r39_procedure_reference(arguments):
    if "inventory" in arguments or "referencePairs" in arguments:
        from libs.review_tools.r39_reference_inventory import evaluate_reference_inventory
        return evaluate_reference_inventory(arguments, SCOPE_FIELDS, evaluate_r39_procedure_reference)
    rows = []

    def add(code, status, refs=()):
        rows.append({"code": code, "result": status, "evidenceRefs": deepcopy(list(refs))})

    def finish():
        statuses = {row["result"] for row in rows}
        status = ("failed" if "failed" in statuses else "evidence_insufficient" if "evidence_insufficient" in statuses
                  else "not_applicable" if statuses == {"not_applicable"} else "passed")
        output = result("evaluate_r39_procedure_reference", status,
                        facts={"referenceChecks": rows, "scope": "selected_instruction_procedure_reference_only",
                               "technicalCompliance": "not_evaluated", "wholeRuleAcceptance": "not_evaluated",
                               "evidenceVerified": False},
                        checks=[check(row["code"], row["result"] == "passed", row["result"], "passed") for row in rows],
                        rule_version="r39-procedure-reference-v1")
        output["evidenceRefs"] = [ref for row in rows for ref in row["evidenceRefs"]]
        return output

    scope = arguments.get("scope")
    if (not isinstance(scope, dict) or any(not _text(scope.get(key)) for key in SCOPE_FIELDS)
            or scope.get("projectId") != arguments.get("projectId")
            or scope["instructionDocumentId"] == scope["procedureDocumentId"]
            or scope["instructionDocumentVersionId"] == scope["procedureDocumentVersionId"]):
        add("r39_reference_scope_missing_or_conflicting", "evidence_insufficient")
        return finish()

    def matches(record):
        return isinstance(record, dict) and all(record.get(key) == scope[key] for key in SCOPE_FIELDS)

    basis = arguments.get("basis")
    if not matches(basis) or type(basis.get("applicable")) is not bool or not _refs(basis):
        add("r39_reference_applicability_missing", "evidence_insufficient")
        return finish()
    refs = _refs(basis)
    # Supplied conflicting identities cannot be hidden by a not-applicable claim.
    for name in ("instructionReference", "procedureIdentity"):
        if name in arguments and not matches(arguments[name]):
            add("r39_reference_supplied_scope_conflict", "evidence_insufficient", refs)
            return finish()
    if not basis["applicable"]:
        add("r39_reference_not_applicable", "not_applicable", refs)
        return finish()
    instruction = arguments.get("instructionReference")
    procedure = arguments.get("procedureIdentity")
    for record, version_key in ((instruction, "instructionDocumentVersionId"), (procedure, "procedureDocumentVersionId")):
        if not matches(record) or not _refs(record) or any(ref["documentVersionId"] != scope[version_key] for ref in _refs(record)):
            add("r39_reference_original_document_missing", "evidence_insufficient", refs)
            return finish()
        refs.extend(_refs(record))
    for instruction_key, procedure_key in (("referencedProcedureNumber", "procedureNumber"), ("referencedProcedureVersion", "procedureVersion")):
        actual, expected = instruction.get(instruction_key), procedure.get(procedure_key)
        if not _text(actual) or not _text(expected):
            add("r39_" + instruction_key + "_missing", "evidence_insufficient", refs)
        else:
            add("r39_" + instruction_key + "_consistency", "passed" if actual == expected else "failed", refs)
    return finish()
