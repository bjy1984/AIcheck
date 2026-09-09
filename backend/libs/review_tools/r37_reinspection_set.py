"""Match every defect in an explicit complete inventory to independent reinspection records."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from libs.review_orchestrator.deterministic_tools import result


def evaluate_reinspection_set(arguments: dict[str, Any], evaluate_one) -> dict[str, Any]:
    project, organization = arguments.get("projectId"), arguments.get("organizationId")
    outcomes = []

    def refs(record):
        values = record.get("evidenceRefs") if isinstance(record, dict) else None
        return values if isinstance(values, list) and values and all(isinstance(ref, dict)
            and isinstance(ref.get("documentVersionId"), str) and ref["documentVersionId"].strip()
            and type(ref.get("pageNo")) is int and ref["pageNo"] > 0 for ref in values) else []

    def finish(status=None):
        statuses = {row["result"] for row in outcomes}
        status = status or ("failed" if "failed" in statuses else "evidence_insufficient" if "evidence_insufficient" in statuses else "not_applicable" if statuses == {"not_applicable"} else "passed")
        output = result("evaluate_r37_reinspection", status, facts={"caseResults": deepcopy(outcomes)}, checks=[], rule_version="r37-reinspection-inventory-v1")
        output["evidenceRefs"] = deepcopy([*refs(arguments.get("caseInventory")), *(ref for row in outcomes for ref in row.get("evidenceRefs", []))])
        return output

    def reject(code):
        outcomes.append({"result": "evidence_insufficient", "reason": code})
        return finish()

    def scoped(record):
        return isinstance(record, dict) and record.get("projectId") == project and record.get("organizationId") == organization and refs(record)

    if "case" in arguments:
        return reject("r37_reinspection_input_mode_ambiguous")
    if any(not isinstance(value, str) or not value.strip() for value in (project, organization)):
        return reject("r37_reinspection_scope_missing")
    applicability = arguments.get("applicability")
    if isinstance(applicability, dict) and applicability.get("required") is False and refs(applicability):
        outcomes.append({"result": "not_applicable", "evidenceRefs": refs(applicability)})
        return finish()
    inventory = arguments.get("caseInventory")
    if not scoped(inventory) or inventory.get("complete") is not True or not isinstance(inventory.get("inventoryId"), str) or not inventory["inventoryId"].strip():
        return reject("r37_reinspection_inventory_unconfirmed")
    cases = inventory.get("cases")
    if not isinstance(cases, list) or type(inventory.get("caseCount")) is not int or inventory["caseCount"] != len(cases):
        return reject("r37_reinspection_inventory_count_mismatch")
    keys = []
    for case in cases:
        if not scoped(case) or case.get("inventoryId") != inventory["inventoryId"] or any(not isinstance(case.get(key), str) or not case[key].strip() for key in ("caseId", "objectId")) or type(case.get("repairRound")) is not int or case["repairRound"] < 0:
            return reject("r37_reinspection_case_identity_invalid")
        keys.append((case["caseId"], case["objectId"], case["repairRound"]))
    if len(set(keys)) != len(keys):
        return reject("r37_reinspection_duplicate_case")
    originals, dispositions, reports = (arguments.get(key) for key in ("originalInspections", "dispositions", "reinspections"))
    if any(not isinstance(records, list) for records in (originals, dispositions, reports)):
        return reject("r37_reinspection_record_collections_missing")

    def matches_case(record, case):
        return isinstance(record, dict) and all(record.get(key) == case[key] and type(record.get(key)) is type(case[key]) for key in ("inventoryId", "caseId", "repairRound"))

    for record in [*dispositions, *reports]:
        if not scoped(record) or not any(matches_case(record, case) for case in cases):
            return reject("r37_reinspection_orphan_or_out_of_scope_record")
    if not cases:
        return finish("not_applicable")
    for case in cases:
        original_matches = [row for row in originals if isinstance(row, dict) and row.get("inspectionId") == case.get("originalInspectionId")]
        disposition_matches = [row for row in dispositions if matches_case(row, case)]
        params = {"projectId": project, "organizationId": organization, "case": deepcopy(case),
                  "originalInspection": deepcopy(original_matches[0]) if len(original_matches) == 1 else None,
                  "disposition": deepcopy(disposition_matches[0]) if len(disposition_matches) == 1 else None,
                  "reinspections": deepcopy([row for row in reports if matches_case(row, case)])}
        outcomes.append({**evaluate_one(params), "caseId": case["caseId"], "objectId": case["objectId"], "repairRound": case["repairRound"]})
    return finish()
