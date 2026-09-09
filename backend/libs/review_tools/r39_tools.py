"""R39 first-use validation occurrence only, NB/T 47013.1-2015 4.3.2.3.

Does not establish instruction technical adequacy, approval or validation efficacy.
The caller must supply sourced facts; this tool does not certify their truth.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from libs.review_orchestrator.deterministic_tools import check, result

IDENTITY_FIELDS = ("projectId", "organizationId", "instructionId", "instructionVersion", "method", "objectId", "eventId")


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and value == value.strip()


def _refs(record: dict[str, Any]) -> list[dict[str, Any]]:
    refs = record.get("evidenceRefs")
    if not isinstance(refs, list) or not refs:
        return []
    for ref in refs:
        if (not isinstance(ref, dict) or not _text(ref.get("documentVersionId"))
                or type(ref.get("pageNo")) is not int or ref["pageNo"] < 1
                or not _text(ref.get("quotedText"))):
            return []
    return deepcopy(refs)


def evaluate_r39_first_use_validation(arguments: dict[str, Any]) -> dict[str, Any]:
    if "inventory" in arguments or "applications" in arguments:
        from libs.review_tools.r39_application_inventory import evaluate_application_inventory
        return evaluate_application_inventory(arguments, IDENTITY_FIELDS, evaluate_r39_first_use_validation)
    rows: list[dict[str, Any]] = []

    def add(code, status, refs=None):
        rows.append({"code": code, "result": status, "evidenceRefs": deepcopy(refs or [])})

    def finish():
        statuses = {row["result"] for row in rows}
        status = "failed" if "failed" in statuses else "evidence_insufficient" if "evidence_insufficient" in statuses else "not_applicable" if statuses == {"not_applicable"} else "passed"
        output = result("evaluate_r39_first_use_validation", status,
                        facts={"validationChecks": rows, "scope": "first_use_validation_occurrence_only",
                               "wholeRuleAcceptance": "not_evaluated", "evidenceVerified": False},
                        checks=[check(row["code"], row["result"] == "passed", row["result"], "passed") for row in rows],
                        rule_version="r39-first-use-validation-occurrence-v2")
        output["evidenceRefs"] = [ref for row in rows for ref in row["evidenceRefs"]]
        return output

    scope = arguments.get("scope")
    if (not isinstance(scope, dict) or any(not _text(scope.get(field)) for field in IDENTITY_FIELDS)
            or arguments.get("projectId") != scope["projectId"]):
        add("r39_application_identity_missing", "evidence_insufficient")
        return finish()

    def matching(record):
        return isinstance(record, dict) and all(record.get(field) == scope[field] for field in IDENTITY_FIELDS)

    basis = arguments.get("basis")
    if (not matching(basis) or basis.get("standard") != "NB/T 47013.1-2015"
            or basis.get("clause") != "4.3.2.3" or basis.get("applicable") is not True or not _refs(basis)):
        add("r39_applicable_basis_missing", "evidence_insufficient")
        return finish()
    application = arguments.get("application")
    if not matching(application) or type(application.get("firstUse")) is not bool or not _refs(application):
        add("r39_first_use_fact_missing_or_mismatched", "evidence_insufficient", _refs(basis))
        return finish()
    refs = [*_refs(basis), *_refs(application)]
    if "validation" in arguments and (not matching(arguments["validation"]) or not _refs(arguments["validation"])):
        add("r39_supplied_validation_scope_conflict", "evidence_insufficient", refs)
        return finish()
    if not application["firstUse"]:
        add("r39_current_event_not_first_use", "not_applicable", refs)
        return finish()
    if application.get("completed") is not True:
        add("r39_first_application_not_confirmed_complete", "evidence_insufficient", refs)
        return finish()
    validation = arguments.get("validation")
    if not matching(validation) or not _refs(validation):
        add("r39_validation_record_missing_or_mismatched", "evidence_insufficient", refs)
        return finish()
    refs.extend(_refs(validation))
    performed = validation.get("performed")
    if type(performed) is not bool:
        add("r39_validation_occurrence_unknown", "evidence_insufficient", refs)
    elif not performed:
        # A missing record alone cannot establish that validation never happened.
        add("r39_validation_not_performed", "failed", refs)
    else:
        at_first_use = validation.get("atFirstUse")
        add("r39_validation_at_first_use", "passed" if at_first_use is True else "failed" if at_first_use is False else "evidence_insufficient", refs)
    return finish()
