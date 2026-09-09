"""R36 typed plan and design tables; ambiguous plan identity remains unavailable."""
from __future__ import annotations

from typing import Any

from libs.review_orchestrator.material_facts import build_material_judgment
from libs.review_orchestrator.ndt_table_facts import read_ndt_tables

R36_TABLES = {"ndt_plan_context": "contexts", "ndt_plan_approval": "plans",
              "ndt_plan_items": "items", "ndt_design_requirements": "requirements"}


def build_r36_business_facts(state: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
    groups = read_ndt_tables(state, run, R36_TABLES, node_id=36)
    judgment = build_material_judgment([(f"r36-{kind}", rows, ("objectId", "projectId")) for kind, rows in groups.items()])
    facts: dict[str, Any] = {"projectId": run["projectId"], "requirements": groups["requirements"]}
    if len(groups["contexts"]) == 1 and groups["contexts"][0].get("projectId") == run["projectId"]:
        context = groups["contexts"][0]
        facts["applicability"] = {"required": context.get("required"), "evidenceRefs": context["evidenceRefs"]}
    if len(groups["plans"]) == 1:
        facts["plan"] = {**groups["plans"][0], "items": groups["items"]}
    return {"r36": facts, **judgment}
