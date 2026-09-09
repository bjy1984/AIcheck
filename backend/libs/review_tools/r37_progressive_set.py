"""Evaluate every declared progressive-inspection event using separately sourced batch rows."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from libs.review_orchestrator.deterministic_tools import result


def evaluate_progressive_set(arguments: dict[str, Any], evaluate_one) -> dict[str, Any]:
    project, organization = arguments.get("projectId"), arguments.get("organizationId")
    inventory = arguments.get("progressiveInventory")
    outcomes = []

    def text(value):
        return isinstance(value, str) and bool(value.strip())

    def refs(record):
        values = record.get("evidenceRefs") if isinstance(record, dict) else None
        return values if isinstance(values, list) and values and all(isinstance(ref, dict) and text(ref.get("documentVersionId"))
            and type(ref.get("pageNo")) is int and ref["pageNo"] > 0 for ref in values) else []

    def scoped(record):
        return isinstance(record, dict) and record.get("projectId") == project and record.get("organizationId") == organization and bool(refs(record))

    def finish(reason=None):
        statuses = {row["result"] for row in outcomes}
        status = "evidence_insufficient" if reason or "evidence_insufficient" in statuses else "failed" if "failed" in statuses else "not_applicable" if not outcomes or statuses == {"not_applicable"} else "passed"
        repairs = sorted({obj for row in outcomes for obj in row.get("facts", {}).get("repairRequiredObjectIds", [])})
        output = result("evaluate_r37_progressive_inspection", status,
            facts={"eventResults": deepcopy(outcomes), "reason": reason, "repairRequiredObjectIds": repairs, "batchAcceptance": "not_evaluated"},
            checks=[], rule_version="r37-progressive-inventory-v1")
        output["evidenceRefs"] = deepcopy([*refs(inventory), *(ref for row in outcomes for ref in row.get("evidenceRefs", []))])
        return output

    if "event" in arguments:
        return finish("progressive_input_mode_ambiguous")
    if not all(text(value) for value in (project, organization)) or not scoped(inventory) or inventory.get("complete") is not True or not text(inventory.get("inventoryId")):
        return finish("progressive_inventory_unconfirmed")
    events, batches, members, reports = (arguments.get(key) for key in ("progressiveEvents", "inspectionBatches", "inspectionBatchMembers", "progressiveReports"))
    if any(not isinstance(rows, list) for rows in (events, batches, members, reports)):
        return finish("progressive_source_collections_missing")
    if type(inventory.get("eventCount")) is not int or inventory["eventCount"] != len(events):
        return finish("progressive_event_count_mismatch")
    event_ids = []
    for event in events:
        if not scoped(event) or event.get("inventoryId") != inventory["inventoryId"] or not text(event.get("eventId")):
            return finish("progressive_event_identity_invalid")
        event_ids.append(event["eventId"])
    if len(set(event_ids)) != len(event_ids):
        return finish("progressive_duplicate_event")
    batch_ids = []
    for batch in batches:
        if not scoped(batch) or not text(batch.get("batchId")):
            return finish("progressive_batch_identity_invalid")
        batch_ids.append(batch["batchId"])
    if len(set(batch_ids)) != len(batch_ids):
        return finish("progressive_duplicate_batch")
    for member in members:
        if not scoped(member) or member.get("batchId") not in batch_ids:
            return finish("progressive_orphan_or_out_of_scope_member")
    for report in reports:
        if not scoped(report) or report.get("inventoryId") != inventory["inventoryId"] or report.get("eventId") not in event_ids or report.get("stage") not in ("first", "second", "full"):
            return finish("progressive_orphan_or_unclassified_report")
    for event in events:
        batch = next((row for row in batches if row["batchId"] == event.get("batchId")), None)
        params = {"projectId": project, "organizationId": organization, "event": deepcopy(event),
                  "batch": {**deepcopy(batch), "members": deepcopy([row for row in members if row.get("batchId") == batch["batchId"]])} if batch else None}
        for stage in ("first", "second", "full"):
            params[stage + "Reports"] = deepcopy([row for row in reports if row["eventId"] == event["eventId"] and row["stage"] == stage])
        outcomes.append({**evaluate_one(params), "eventId": event["eventId"]})
    return finish()
