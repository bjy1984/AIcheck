"""R37 scoped typed witness records; inventory contents come from separate sourced rows."""
from __future__ import annotations

from typing import Any

from libs.review_orchestrator.material_facts import build_material_judgment
from libs.review_orchestrator.ndt_table_facts import read_ndt_tables

R37_TABLES = {"ndt_nonconformance_context": "contexts", "ndt_nonconformance_procedure": "procedures",
              "ndt_nonconformance_inventory": "inventories", "ndt_nonconformance_cases": "cases",
              "ndt_nonconformance_commissions": "commissions", "ndt_nonconformance_notices": "notices",
              "ndt_nonconformance_feedback": "feedback", "ndt_original_inspections": "originalInspections",
              "ndt_defect_dispositions": "dispositions", "ndt_reinspection_reports": "reinspections",
              "ndt_progressive_inventory": "progressiveInventories", "ndt_progressive_events": "progressiveEvents",
              "ndt_inspection_batches": "inspectionBatches", "ndt_inspection_batch_members": "inspectionBatchMembers",
              "ndt_progressive_reports": "progressiveReports", "ndt_defect_closure_links": "closureLinks"}


def build_r37_business_facts(state: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
    groups = read_ndt_tables(state, run, R37_TABLES, node_id=37)
    judgment = build_material_judgment([(f"r37-{kind}", rows, ("caseId", "objectId", "projectId")) for kind, rows in groups.items()])
    facts = {"projectId": run["projectId"], **{key: groups[key] for key in ("commissions", "notices", "feedback", "originalInspections", "dispositions", "reinspections", "progressiveEvents", "inspectionBatches", "inspectionBatchMembers", "progressiveReports", "closureLinks")}}
    if len(groups["contexts"]) == 1 and groups["contexts"][0].get("projectId") == run["projectId"]:
        context = groups["contexts"][0]
        facts["organizationId"] = context.get("organizationId")
        facts["applicability"] = {"required": context.get("required"), "evidenceRefs": context["evidenceRefs"]}
    if len(groups["procedures"]) == 1:
        facts["procedure"] = groups["procedures"][0]
    if len(groups["inventories"]) == 1:
        facts["caseInventory"] = {**groups["inventories"][0], "cases": groups["cases"]}
    if len(groups["progressiveInventories"]) == 1:
        facts["progressiveInventory"] = groups["progressiveInventories"][0]
    return {"r37": facts, **judgment}
