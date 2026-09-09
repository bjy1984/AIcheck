"""R35 typed OCR tables from frozen inputs; never infer implementation from file presence."""
from __future__ import annotations

from typing import Any

from libs.review_orchestrator.material_facts import build_material_judgment
from libs.review_orchestrator.ndt_table_facts import read_ndt_tables

R35_TABLES = {
    "ndt_quality_manual": "manual", "ndt_controlled_forms": "controlledForms",
    "ndt_appointments": "appointments", "ndt_implementation_records": "implementationRecords",
    "ndt_equipment_inventory": "equipment", "ndt_calibration_reports": "calibrationReports",
    "ndt_site_activity": "activities",
}



def build_r35_business_facts(state: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
    groups = read_ndt_tables(state, run, R35_TABLES, node_id=35)
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
