"""One R37 defect's reinspection, based on GB/T 20801.1-2025 8.1.3/8.3.3.4.

This does not decide progressive inspection of the represented batch.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any

from libs.review_orchestrator.deterministic_tools import check, result
from libs.review_tools.r37_reinspection_set import evaluate_reinspection_set


def evaluate_r37_reinspection(arguments: dict[str, Any]) -> dict[str, Any]:
    if "caseInventory" in arguments:
        return evaluate_reinspection_set(arguments, evaluate_r37_reinspection)
    rows = []
    project, organization = arguments.get("projectId"), arguments.get("organizationId")

    def refs(record):
        values = record.get("evidenceRefs") if isinstance(record, dict) else None
        return values if isinstance(values, list) and values and all(isinstance(ref, dict)
            and isinstance(ref.get("documentVersionId"), str) and ref["documentVersionId"].strip()
            and type(ref.get("pageNo")) is int and ref["pageNo"] > 0 for ref in values) else []

    def scoped(record):
        return isinstance(record, dict) and record.get("projectId") == project and record.get("organizationId") == organization and refs(record)

    def add(code, status, *records):
        rows.append({"code": code, "result": status, "evidenceRefs": deepcopy([ref for record in records for ref in refs(record)])})

    def finish():
        statuses = {row["result"] for row in rows}
        status = "failed" if "failed" in statuses else "evidence_insufficient" if "evidence_insufficient" in statuses else "not_applicable" if statuses == {"not_applicable"} else "passed"
        output = result("evaluate_r37_reinspection", status, facts={"reinspectionChecks": rows},
                        checks=[check(row["code"], row["result"] == "passed", row["result"], "passed") for row in rows],
                        rule_version="r37-original-reinspection-v1")
        output["evidenceRefs"] = [ref for row in rows for ref in row["evidenceRefs"]]
        output["standardBasis"] = {"standard": "GB/T 20801.1-2025", "clauses": ["8.1.3", "8.3.3.4"], "pdfPages": [118, 124]}
        return output

    def text(value):
        return isinstance(value, str) and bool(value.strip())

    def instant(value):
        if not isinstance(value, str):
            return None
        try:
            parsed = datetime.fromisoformat(value)
            return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None
        except ValueError:
            return None

    case = arguments.get("case")
    identity_fields = ("inventoryId", "caseId", "objectId", "repairRound")
    if not all(text(value) for value in (project, organization)) or not scoped(case) or any(not text(case.get(key)) for key in identity_fields[:-1]) or type(case.get("repairRound")) is not int or case["repairRound"] < 0:
        add("r37_reinspection_identity_missing", "evidence_insufficient")
        return finish()
    if type(case.get("exceedsAcceptance")) is not bool:
        add("r37_defect_applicability_missing", "evidence_insufficient", case)
        return finish()
    if not case["exceedsAcceptance"]:
        add("r37_no_exceeding_defect", "not_applicable", case)
        return finish()
    original, disposition = arguments.get("originalInspection"), arguments.get("disposition")
    if not scoped(original) or not text(case.get("originalInspectionId")) or original.get("inspectionId") != case["originalInspectionId"] or original.get("objectId") != case["objectId"]:
        add("r37_original_inspection_unmatched", "evidence_insufficient", case, original)
        return finish()
    if not scoped(disposition) or any(disposition.get(key) != case[key] or type(disposition.get(key)) is not type(case[key]) for key in identity_fields):
        add("r37_disposition_unmatched", "evidence_insufficient", case, disposition)
        return finish()
    action = disposition.get("action")
    target = case["objectId"] if action == "repair" else disposition.get("replacementObjectId") if action == "replace" else None
    completed = instant(disposition.get("completedAt"))
    if not text(target) or completed is None or (action == "replace" and target == case["objectId"]):
        add("r37_disposition_target_or_completion_missing", "evidence_insufficient", disposition)
        return finish()
    requirements, reports = original.get("requirements"), arguments.get("reinspections")
    if not isinstance(requirements, list) or not requirements or not isinstance(reports, list):
        add("r37_original_requirements_or_reports_missing", "evidence_insufficient", original)
        return finish()
    methods = [row.get("method") if isinstance(row, dict) else None for row in requirements]
    if not all(text(method) for method in methods) or len(set(methods)) != len(methods):
        add("r37_original_methods_ambiguous", "evidence_insufficient", original)
        return finish()
    for index, requirement in enumerate(requirements):
        code = f"r37_reinspection_{index + 1}"
        matches = [row for row in reports if isinstance(row, dict) and row.get("method") == requirement["method"]]
        if len(matches) != 1:
            add(code + "_report_missing_or_ambiguous", "evidence_insufficient", original)
            continue
        report = matches[0]
        if not scoped(report) or report.get("objectId") != target or any(report.get(key) != case[key] or type(report.get(key)) is not type(case[key]) for key in ("inventoryId", "caseId", "repairRound")):
            add(code + "_report_identity_mismatch", "evidence_insufficient", disposition, report)
            continue
        inspected = instant(report.get("inspectedAt"))
        if inspected is None:
            add(code + "_inspection_time_missing", "evidence_insufficient", report)
            continue
        elif inspected < completed:
            add(code + "_inspection_before_completion", "failed", disposition, report)
        comparable = True
        for field in ("scope", "acceptanceCriteriaId"):
            same = text(requirement.get(field)) and report.get(field) == requirement[field]
            comparable = comparable and same
            add(code + "_" + field, "passed" if same else "evidence_insufficient", original, report)
        if not comparable:
            continue
        status = report.get("status")
        add(code + "_result", "passed" if status == "qualified" else "failed" if status == "unqualified" else "evidence_insufficient", report)
    return finish()
