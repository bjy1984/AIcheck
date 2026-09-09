"""Progressive inspection coverage under GB/T 20801.1-2025 8.1.4.

Coverage completion is not acceptance of defective objects; repair closure is separate.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any

from libs.review_orchestrator.deterministic_tools import result


def evaluate_r37_progressive_inspection(arguments: dict[str, Any]) -> dict[str, Any]:
    project, organization = arguments.get("projectId"), arguments.get("organizationId")
    event, batch = arguments.get("event"), arguments.get("batch")
    evidence, repair = [], set()

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

    def refs(record):
        values = record.get("evidenceRefs") if isinstance(record, dict) else None
        return values if isinstance(values, list) and values and all(isinstance(ref, dict)
            and text(ref.get("documentVersionId")) and type(ref.get("pageNo")) is int and ref["pageNo"] > 0 for ref in values) else []

    def scoped(record):
        return isinstance(record, dict) and record.get("projectId") == project and record.get("organizationId") == organization and bool(refs(record))

    def finish(status, stage, reason, **details):
        output = result("evaluate_r37_progressive_inspection", status,
            facts={"stage": stage, "reason": reason, "repairRequiredObjectIds": sorted(repair), "batchAcceptance": "not_evaluated", **details},
            checks=[], rule_version="r37-progressive-coverage-v1")
        output["evidenceRefs"] = deepcopy(evidence)
        output["standardBasis"] = {"standard": "GB/T 20801.1-2025", "clause": "8.1.4", "pdfPage": 118}
        return output

    def unknown(reason, stage="unresolved", **details):
        return finish("evidence_insufficient", stage, reason, **details)

    if not all(text(value) for value in (project, organization)) or not scoped(event):
        return unknown("event_identity_or_evidence_missing")
    evidence.extend(refs(event))
    if any(not text(event.get(key)) for key in ("eventId", "batchId", "objectId", "method", "scope", "acceptanceCriteriaId")) or type(event.get("isWeld")) is not bool:
        return unknown("event_fields_missing")
    if event.get("status") not in ("qualified", "unqualified") or event.get("phase") not in ("initial", "repair_reinspection") or event.get("inspectionMode") not in ("full", "sampling", "local"):
        return unknown("event_status_or_applicability_unknown")
    if event["status"] == "qualified":
        return finish("not_applicable", "not_required", "no_exceeding_defect")
    repair.add(event["objectId"])
    if event["phase"] == "repair_reinspection":
        return finish("not_applicable", "repair_only", "repair_reinspection_does_not_restart_progression")
    if event["inspectionMode"] == "full":
        return finish("not_applicable", "not_required", "initial_inspection_was_full")
    if not scoped(batch) or batch.get("batchId") != event["batchId"] or batch.get("complete") is not True:
        return unknown("batch_inventory_unconfirmed")
    members = batch.get("members")
    if not isinstance(members, list) or not members or type(batch.get("memberCount")) is not int or batch["memberCount"] != len(members):
        return unknown("batch_inventory_count_invalid")
    registry = {}
    for member in members:
        if not scoped(member) or member.get("batchId") != event["batchId"] or not text(member.get("objectId")) or member["objectId"] in registry or not text(member.get("similarityGroupId")):
            return unknown("batch_member_identity_invalid")
        registry[member["objectId"]] = member
        evidence.extend(refs(member))
    evidence.extend(refs(batch))
    original = registry.get(event["objectId"])
    if original is None or event["isWeld"] and not text(original.get("welderId")):
        return unknown("trigger_object_or_welder_unidentified")
    initial_time = instant(event.get("inspectedAt"))
    if initial_time is None:
        return unknown("trigger_inspection_time_unknown")
    first, second, full = (arguments.get(key, []) for key in ("firstReports", "secondReports", "fullReports"))
    if any(not isinstance(records, list) for records in (first, second, full)):
        return unknown("report_collections_invalid")
    seen = {event["objectId"]}

    def inspect(report, *, additional, not_before):
        if not scoped(report) or not text(report.get("objectId")) or report["objectId"] not in registry:
            return "report_identity_or_evidence_missing"
        inspected = instant(report.get("inspectedAt"))
        if inspected is None or inspected < not_before:
            return "inspection_time_missing_or_before_trigger"
        if report.get("phase") != "initial":
            return "repair_reinspection_cannot_trigger_new_progression"
        if any(report.get(key) != event[key] for key in ("eventId", "batchId", "method", "scope", "acceptanceCriteriaId")):
            return "report_does_not_match_original_inspection"
        member = registry[report["objectId"]]
        if additional and (member["similarityGroupId"] != original["similarityGroupId"] or event["isWeld"] and member.get("welderId") != original["welderId"]):
            return "additional_piece_not_same_kind_or_welder"
        if additional and report["objectId"] in seen:
            return "additional_piece_reused"
        status, defects = report.get("status"), report.get("defectIds")
        if status not in ("qualified", "unqualified") or not isinstance(defects, list) or not all(text(value) for value in defects) or len(set(defects)) != len(defects) or (status == "qualified") != (not defects):
            return "report_status_or_defect_inventory_unknown"
        seen.add(report["objectId"])
        evidence.extend(refs(report))
        if defects:
            repair.add(report["objectId"])
        return None

    for report in first:
        error = inspect(report, additional=True, not_before=initial_time)
        if error:
            return unknown(error, "first")
    if len(first) < 2:
        return unknown("two_additional_pieces_required", "first", additionalCountRequired=2 - len(first))
    failures = {(row["objectId"], defect) for row in first for defect in row["defectIds"]}
    if not failures:
        if second or full:
            return unknown("unexpected_later_stage_records", "first")
        return finish("passed", "first_complete", "additional_pieces_qualified_repair_closure_still_required")
    groups = {key: [] for key in failures}
    for report in second:
        if not isinstance(report, dict) or not text(report.get("parentObjectId")) or not text(report.get("parentDefectId")):
            return unknown("second_stage_parent_missing", "second")
        parent = report["parentObjectId"], report["parentDefectId"]
        if parent not in groups:
            return unknown("second_stage_parent_unknown", "second")
        parent_report = next(row for row in first if row["objectId"] == parent[0])
        error = inspect(report, additional=True, not_before=instant(parent_report["inspectedAt"]))
        if error:
            return unknown(error, "second")
        groups[parent].append(report)
    missing = [{"parentObjectId": obj, "parentDefectId": defect, "additionalCountRequired": 2 - len(records)}
               for (obj, defect), records in sorted(groups.items()) if len(records) < 2]
    escalated = any(row["defectIds"] for row in second)
    if missing and not escalated:
        return unknown("two_additional_pieces_per_defect_required", "second", missingGroups=missing)
    if not escalated:
        if full:
            return unknown("unexpected_full_stage_records", "second")
        return finish("passed", "second_complete", "second_stage_qualified_repair_closure_still_required")
    escalation_time = min(instant(row["inspectedAt"]) for row in second if row["defectIds"])
    full_seen = set()
    for report in full:
        error = inspect(report, additional=False, not_before=escalation_time)
        if error:
            return unknown(error, "full")
        if report["objectId"] in full_seen:
            return unknown("full_stage_duplicate_report", "full")
        full_seen.add(report["objectId"])
    missing_objects = sorted(set(registry) - seen)
    if missing_objects:
        return unknown("full_batch_inspection_required", "full", missingObjectIds=missing_objects)
    return finish("passed", "full_complete", "full_coverage_repair_closure_still_required")
