"""R37 sourced nonconformance witness chain; document presence alone cannot pass."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from libs.review_orchestrator.deterministic_tools import check, result


def evaluate_ndt_nonconformance(arguments: dict[str, Any]) -> dict[str, Any]:
    rows = []

    def refs(record):
        values = record.get("evidenceRefs") if isinstance(record, dict) else None
        return values if isinstance(values, list) and values and all(
            isinstance(ref, dict) and isinstance(ref.get("documentVersionId"), str) and ref["documentVersionId"].strip()
            and type(ref.get("pageNo")) is int and ref["pageNo"] > 0 for ref in values) else []

    def add(code, status, record=None):
        rows.append({"code": code, "result": status, "evidenceRefs": deepcopy(refs(record))})

    def finish():
        statuses = {row["result"] for row in rows}
        status = "failed" if "failed" in statuses else "evidence_insufficient" if "evidence_insufficient" in statuses else "not_applicable" if statuses == {"not_applicable"} else "passed"
        output = result("evaluate_ndt_nonconformance", status, facts={"nonconformanceChecks": rows},
                        checks=[check(row["code"], row["result"] == "passed", row["result"], "passed") for row in rows],
                        rule_version="r37-nonconformance-witness-chain-v2")
        output["evidenceRefs"] = [ref for row in rows for ref in row["evidenceRefs"]]
        return output

    applicability = arguments.get("applicability")
    if not isinstance(applicability, dict) or type(applicability.get("required")) is not bool or not refs(applicability):
        add("r37_applicability_missing", "evidence_insufficient")
        return finish()
    if not applicability["required"]:
        add("r37_not_applicable", "not_applicable", applicability)
        return finish()
    project, organization = arguments.get("projectId"), arguments.get("organizationId")
    if any(not isinstance(value, str) or not value.strip() for value in (project, organization)):
        add("r37_identity_missing", "evidence_insufficient")
        return finish()
    add("r37_applicable", "passed", applicability)

    def scoped(record):
        return isinstance(record, dict) and record.get("projectId") == project and record.get("organizationId") == organization and bool(refs(record))

    def inspect(record, code):
        if not scoped(record):
            add(code + "_identity_or_evidence_missing", "evidence_insufficient", record)
        else:
            value = record.get("status")
            status = "passed" if value == "conforming" else "failed" if value == "nonconforming" else "evidence_insufficient"
            add(code, status, record)

    inspect(arguments.get("procedure"), "r37_procedure")
    inventory = arguments.get("caseInventory")
    if not scoped(inventory) or inventory.get("complete") is not True or not isinstance(inventory.get("cases"), list) or not isinstance(inventory.get("inventoryId"), str) or not inventory["inventoryId"].strip():
        add("r37_case_inventory_incomplete", "evidence_insufficient", inventory)
        return finish()
    if type(inventory.get("caseCount")) is not int or inventory["caseCount"] != len(inventory["cases"]):
        add("r37_case_inventory_count_mismatch", "evidence_insufficient", inventory)
        return finish()
    add("r37_case_inventory", "passed", inventory)
    commissions = arguments.get("commissions")
    if not isinstance(commissions, list) or not commissions:
        add("r37_commissions_missing", "evidence_insufficient")
        return finish()
    commission_ids = [row.get("commissionId") if isinstance(row, dict) else None for row in commissions]
    if any(not isinstance(value, str) or not value.strip() for value in commission_ids) or len(set(commission_ids)) != len(commission_ids):
        add("r37_commissions_ambiguous", "evidence_insufficient")
        return finish()
    for index, commission in enumerate(commissions):
        inspect(commission, f"r37_commission_{index + 1}")
    seen = set()
    for index, case in enumerate(inventory["cases"]):
        code = f"r37_case_{index + 1}"
        if not scoped(case) or case.get("inventoryId") != inventory["inventoryId"] or any(not isinstance(case.get(key), str) or not case[key].strip() for key in ("caseId", "objectId", "commissionId")) or type(case.get("repairRound")) is not int or case["repairRound"] < 0:
            add(code + "_identity_missing", "evidence_insufficient", case)
            continue
        identity = tuple(case[key] for key in ("inventoryId", "caseId", "objectId", "commissionId", "repairRound"))
        if identity in seen:
            add(code + "_duplicate", "evidence_insufficient", case)
            continue
        seen.add(identity)
        commission = next((row for row in commissions if row["commissionId"] == case["commissionId"]), None)
        if not scoped(commission) or not isinstance(commission.get("objectIds"), list) or case["objectId"] not in commission["objectIds"]:
            add(code + "_commission_object_unmatched", "evidence_insufficient", case)
            continue
        add(code + "_identified", "passed", case)
        for key in ("notices", "feedback"):
            records = arguments.get(key)
            matches = [row for row in records if isinstance(row, dict) and all(row.get(field) == case[field] and type(row.get(field)) is type(case[field]) for field in ("inventoryId", "caseId", "objectId", "commissionId", "repairRound"))] if isinstance(records, list) else []
            if len(matches) != 1:
                add(code + "_" + key + "_missing_or_ambiguous", "evidence_insufficient", case)
            else:
                inspect(matches[0], code + "_" + key)
    for key in ("notices", "feedback"):
        records = arguments.get(key)
        if records is not None and not isinstance(records, list):
            add("r37_" + key + "_invalid", "evidence_insufficient")
        for record in records if isinstance(records, list) else []:
            if not scoped(record) or not any(all(record.get(field) == value and type(record.get(field)) is type(value) for field, value in zip(("inventoryId", "caseId", "objectId", "commissionId", "repairRound"), identity)) for identity in seen):
                add("r37_" + key + "_orphan_or_out_of_scope", "evidence_insufficient", record)
    return finish()
