"""R35 typed OCR tables from frozen inputs; never infer implementation from file presence."""
from __future__ import annotations

import math
from copy import deepcopy
from typing import Any

from libs.review_input_data import selected_parse_results
from libs.review_orchestrator.material_facts import build_material_judgment
from libs.review_workstations import digest

R35_TABLES = {
    "ndt_quality_manual": "manual", "ndt_controlled_forms": "controlledForms",
    "ndt_appointments": "appointments", "ndt_implementation_records": "implementationRecords",
    "ndt_equipment_inventory": "equipment", "ndt_calibration_reports": "calibrationReports",
    "ndt_site_activity": "activities",
}



def _table_location(table: dict[str, Any]) -> dict[str, Any]:
    bbox = table.get("bbox")
    valid_bbox = (isinstance(bbox, list) and len(bbox) == 4
                  and all(type(value) in (int, float) and math.isfinite(value) for value in bbox)
                  and bbox[0] >= 0 and bbox[1] >= 0 and bbox[2] > bbox[0] and bbox[3] > bbox[1])
    page = table.get("pageNo")
    text = table.get("contentMarkdown")
    return {"pageNo": page if type(page) is int and page > 0 else None,
            "bbox": deepcopy(bbox) if valid_bbox else None,
            "quotedText": text if isinstance(text, str) and text.strip() else None}

def build_r35_business_facts(state: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
    if (any(not isinstance(run.get(key), str) or not run[key].strip() for key in ("projectId", "tenantId"))
            or run.get("nodeId") != 35):
        raise ValueError("r35_review_identity_incomplete_or_wrong_node")
    groups: dict[str, list] = {value: [] for value in R35_TABLES.values()}
    versions = {row["id"]: row for row in state.get("versions", []) if row.get("tenantId") == run.get("tenantId")}
    documents = {row["id"] for row in state.get("documents", [])
                 if row.get("projectId") == run.get("projectId") and row.get("tenantId") == run.get("tenantId")}
    for parse in selected_parse_results(state, {}, context={"reviewRun": run}):
        version_id = parse.get("documentVersionId")
        if (parse.get("tenantId") != run.get("tenantId") or versions.get(version_id, {}).get("documentId") not in documents):
            continue
        for table in parse.get("tables") or []:
            if not isinstance(table, dict) or table.get("businessSchema") not in R35_TABLES:
                continue
            for index, row in enumerate(table.get("normalizedRows") or []):
                if not isinstance(row, dict):
                    continue
                ref = {"documentVersionId": version_id, **_table_location(table),
                       "tableId": table.get("tableId") or table.get("id"), "rowIndex": index}
                ref["id"] = "R35-REF-" + digest(ref)[:24]
                ref["evidenceRefId"] = ref["id"]
                ref["confidence"] = row.get("confidence", table.get("structureConfidence"))
                # Client/OCR supplied evidenceRefs cannot redirect a record to another document.
                record = {**deepcopy(row), "documentVersionId": version_id, "evidence": ref, "evidenceRefs": [ref]}
                groups[R35_TABLES[table["businessSchema"]]].append(record)
    judgment = build_material_judgment([(f"r35-{kind}", rows, ("status", "equipmentId", "activityDate", "organizationId"))
                                        for kind, rows in groups.items()])
    activities = groups.pop("activities")
    equipment = groups.pop("equipment")
    facts: dict[str, Any] = {**groups, "projectId": run.get("projectId")}
    # No arbitrary first-row choice when the activity identity is ambiguous.
    if len(activities) == 1 and activities[0].get("projectId") == run.get("projectId"):
        activity = activities[0]
        facts.update(organizationId=activity.get("organizationId"), activityDate=activity.get("activityDate"),
                     applicability={"required": activity.get("required"), "evidenceRefs": activity["evidenceRefs"]})
    matched = [row for row in equipment if row.get("projectId") == run.get("projectId")
               and row.get("organizationId") == facts.get("organizationId")]
    facts["equipmentIds"] = [row.get("equipmentId") for row in matched]
    facts["equipmentEvidenceRefs"] = [ref for row in matched for ref in row["evidenceRefs"]]
    return {"r35": facts, **judgment}
