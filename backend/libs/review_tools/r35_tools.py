"""R35 structured site quality-system checks; source verification is a separate gate."""
from __future__ import annotations

from typing import Any

from libs.review_orchestrator.deterministic_tools import check, parse_date, result


def evaluate_ndt_quality_system(arguments: dict[str, Any]) -> dict[str, Any]:
    name = "evaluate_ndt_quality_system"
    rows: list[dict[str, Any]] = []

    def add(code: str, status: str, evidence=None):
        rows.append({"code": code, "result": status, "evidenceRefs": evidence or []})

    def refs(record):
        values = record.get("evidenceRefs")
        return values if isinstance(values, list) and values and all(
            isinstance(ref, dict) and isinstance(ref.get("documentVersionId"), str) and ref["documentVersionId"]
            and type(ref.get("pageNo")) is int and ref["pageNo"] > 0 for ref in values) else []

    def finish():
        statuses = {row["result"] for row in rows}
        status = "failed" if "failed" in statuses else "evidence_insufficient" if "evidence_insufficient" in statuses else "not_applicable" if statuses == {"not_applicable"} else "passed"
        output = result(name, status, facts={"qualitySystemChecks": rows},
                        checks=[check(row["code"], row["result"] == "passed", row["result"], "passed") for row in rows],
                        rule_version="r35-site-quality-system-v1")
        output["evidenceRefs"] = [ref for row in rows for ref in row["evidenceRefs"]]
        return output

    applicability = arguments.get("applicability")
    if not isinstance(applicability, dict) or type(applicability.get("required")) is not bool or not refs(applicability):
        add("r35_applicability_evidence_missing", "evidence_insufficient")
        return finish()
    if applicability["required"] is False:
        add("r35_not_applicable", "not_applicable", refs(applicability))
        return finish()
    add("r35_applicable", "passed", refs(applicability))
    project, organization = arguments.get("projectId"), arguments.get("organizationId")
    activity_date = parse_date(arguments.get("activityDate"))
    if not isinstance(project, str) or not project.strip() or not isinstance(organization, str) or not organization.strip() or activity_date is None:
        add("r35_activity_identity_or_date_missing", "evidence_insufficient")
        return finish()

    def inspect(record, code, *, equipment_id=None):
        if not isinstance(record, dict) or not refs(record):
            add(code + "_evidence_missing", "evidence_insufficient")
            return
        evidence = refs(record)
        if not record.get("projectId") or not record.get("organizationId"):
            add(code + "_identity_missing", "evidence_insufficient", evidence)
        elif record["projectId"] != project or record["organizationId"] != organization:
            add(code + "_identity_mismatch", "evidence_insufficient", evidence)
        elif record.get("status") == "nonconforming":
            add(code + "_nonconforming", "failed", evidence)
        elif record.get("status") != "conforming":
            add(code + "_implementation_unconfirmed", "evidence_insufficient", evidence)
        elif equipment_id is not None:
            start, end = parse_date(record.get("validFrom")), parse_date(record.get("validUntil"))
            if start is None or end is None or start > end:
                add(code + "_validity_missing_or_invalid", "evidence_insufficient", evidence)
            else:
                add(code + "_validity", "passed" if start <= activity_date <= end else "failed", evidence)
        else:
            add(code, "passed", evidence)

    for key in ("manual", "controlledForms", "appointments", "implementationRecords"):
        records = arguments.get(key)
        if not isinstance(records, list) or not records:
            add("r35_" + key + "_missing", "evidence_insufficient")
        else:
            for index, record in enumerate(records):
                inspect(record, f"r35_{key}_{index + 1}")
    equipment = arguments.get("equipmentIds")
    if (not isinstance(equipment, list) or not equipment or any(not isinstance(item, str) or not item.strip() for item in equipment)
            or len(set(equipment)) != len(equipment) or not refs({"evidenceRefs": arguments.get("equipmentEvidenceRefs")})):
        add("r35_equipment_inventory_missing_or_ambiguous", "evidence_insufficient")
    else:
        add("r35_equipment_inventory", "passed", arguments["equipmentEvidenceRefs"])
        reports = arguments.get("calibrationReports")
        for index, equipment_id in enumerate(equipment):
            matches = [row for row in reports if isinstance(row, dict) and row.get("equipmentId") == equipment_id] if isinstance(reports, list) else []
            if len(matches) != 1:
                add(f"r35_equipment_{index + 1}_calibration_missing_or_ambiguous", "evidence_insufficient")
            else:
                inspect(matches[0], f"r35_equipment_{index + 1}", equipment_id=equipment_id)
    return finish()
