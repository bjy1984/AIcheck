"""Reconcile progressive defect obligations with the latest evidenced reinspection round.

Both component results are recalculated from input records, never accepted from callers.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any

from libs.review_orchestrator.deterministic_tools import result
from libs.review_tools.r37_progressive import evaluate_r37_progressive_inspection
from libs.review_tools.r37_reinspection import evaluate_r37_reinspection


def evaluate_r37_defect_closure(arguments: dict[str, Any]) -> dict[str, Any]:
    rows, sources = [], []
    progression, reinspection = {}, {}
    project, organization = arguments.get("projectId"), arguments.get("organizationId")

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
            and isinstance(ref.get("documentVersionId"), str) and ref["documentVersionId"].strip()
            and type(ref.get("pageNo")) is int and ref["pageNo"] > 0 for ref in values) else []

    def finish(reason=None):
        statuses = {row["result"] for row in rows}
        status = "failed" if "failed" in statuses else "evidence_insufficient" if reason or "evidence_insufficient" in statuses else "passed" if rows else "not_applicable"
        output = result("evaluate_r37_defect_closure", status,
            facts={"closureChecks": deepcopy(rows), "reason": reason, "progression": progression, "reinspection": reinspection,
                   "batchAcceptance": "not_evaluated"}, checks=[], rule_version="r37-progression-reinspection-closure-v2")
        output["evidenceRefs"] = deepcopy(sources)
        return output

    if "case" in arguments or "event" in arguments or "progressiveInventory" not in arguments or "caseInventory" not in arguments:
        return finish("closure_requires_both_complete_inventories")
    progression = evaluate_r37_progressive_inspection(arguments)
    sources.extend(progression.get("evidenceRefs", []))
    if progression["result"] not in ("passed", "not_applicable"):
        return finish("progressive_coverage_unresolved")
    # A caller's global applicability flag cannot suppress known repair obligations.
    reinspection = evaluate_r37_reinspection({key: deepcopy(value) for key, value in arguments.items() if key != "applicability"})
    sources.extend(reinspection.get("evidenceRefs", []))
    outcomes = reinspection["facts"].get("caseResults", [])
    if any("caseId" not in row for row in outcomes):
        return finish("reinspection_inventory_invalid")
    required = {(event["eventId"], obj) for event in progression["facts"]["eventResults"]
                for obj in event.get("facts", {}).get("repairRequiredObjectIds", [])}
    applicability = arguments.get("applicability")
    if required and isinstance(applicability, dict) and applicability.get("required") is False:
        return finish("applicability_conflicts_with_defect_obligations")
    inventory, progressive_inventory = arguments["caseInventory"], arguments["progressiveInventory"]
    cases, links = inventory.get("cases"), arguments.get("closureLinks")
    if not isinstance(cases, list) or not isinstance(links, list):
        return finish("closure_links_or_cases_missing")
    by_subject = {}
    for case in cases:
        if not isinstance(case.get("eventId"), str):
            return finish("case_event_unidentified")
        subject = case["eventId"], case["objectId"]
        if subject not in required and case.get("exceedsAcceptance") is not False:
            return finish("defect_case_not_represented_by_progressive_inventory")
        by_subject.setdefault(subject, []).append(case)
    link_map = {}
    for link in links:
        if not isinstance(link, dict) or link.get("projectId") != project or link.get("organizationId") != organization or not refs(link):
            return finish("closure_link_identity_or_evidence_missing")
        if link.get("caseInventoryId") != inventory["inventoryId"] or link.get("progressiveInventoryId") != progressive_inventory["inventoryId"]:
            return finish("closure_link_inventory_mismatch")
        if any(not isinstance(link.get(key), str) for key in ("eventId", "objectId", "caseId")) or type(link.get("repairRound")) is not int:
            return finish("closure_link_fields_invalid")
        subject = link["eventId"], link["objectId"]
        if subject not in required or subject in link_map:
            return finish("closure_link_orphan_or_ambiguous")
        link_map[subject] = link
        sources.extend(refs(link))
    for event_id, object_id in sorted(required):
        subject = event_id, object_id
        candidates, link = by_subject.get(subject, []), link_map.get(subject)
        row = {"eventId": event_id, "objectId": object_id, "result": "evidence_insufficient"}
        if not candidates or link is None:
            rows.append({**row, "reason": "closure_link_or_case_missing"})
            continue
        latest = max(case["repairRound"] for case in candidates)
        active = [case for case in candidates if case["repairRound"] == latest]
        if len(active) != 1 or link["repairRound"] != latest or link["caseId"] != active[0]["caseId"]:
            rows.append({**row, "reason": "closure_does_not_uniquely_match_latest_round"})
            continue
        event = next(item for item in arguments["progressiveEvents"] if item["eventId"] == event_id)
        originals = [item for item in arguments["originalInspections"] if isinstance(item, dict) and item.get("inspectionId") == active[0].get("originalInspectionId")]
        requirements = originals[0].get("requirements", []) if len(originals) == 1 else []
        compatible = [item for item in requirements if isinstance(item, dict) and all(item.get(key) == event[key] for key in ("method", "scope", "acceptanceCriteriaId"))] if isinstance(requirements, list) else []
        failures = [item for item in [event, *arguments["progressiveReports"]] if item.get("eventId") == event_id and item.get("objectId") == object_id and item.get("status") == "unqualified"]
        earlier = {(case["caseId"], case["repairRound"]) for case in candidates if case["repairRound"] < latest}
        failures.extend(item for item in arguments["reinspections"] if isinstance(item, dict) and item.get("inventoryId") == inventory["inventoryId"]
                        and type(item.get("repairRound")) is int and isinstance(item.get("caseId"), str)
                        and (item["caseId"], item["repairRound"]) in earlier and item.get("status") == "unqualified")
        times = [instant(item.get("inspectedAt")) for item in failures]
        dispositions = [item for item in arguments["dispositions"] if isinstance(item, dict) and item.get("inventoryId") == inventory["inventoryId"] and item.get("caseId") == link["caseId"] and item.get("objectId") == object_id and item.get("repairRound") == latest]
        completed = instant(dispositions[0].get("completedAt")) if len(dispositions) == 1 else None
        if len(compatible) != 1 or not times or any(value is None for value in times) or completed is None or completed < max(times):
            rows.append({**row, "reason": "repair_basis_or_time_not_aligned_with_defect"})
            continue
        matching = [item for item in outcomes if item["caseId"] == link["caseId"] and item["objectId"] == object_id and item["repairRound"] == latest]
        status = matching[0]["result"] if len(matching) == 1 else "evidence_insufficient"
        rows.append({**row, "caseId": link["caseId"], "repairRound": latest,
                     "result": status if status in ("passed", "failed") else "evidence_insufficient", "reason": "latest_reinspection_evaluated"})
    return finish()
