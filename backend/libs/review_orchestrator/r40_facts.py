"""Selected-version, source-gated R40 record/report event inventory."""
from copy import deepcopy

from libs.review_orchestrator.deterministic_tools import validate_evidence_grounding
from libs.review_orchestrator.material_facts import build_material_judgment
from libs.review_orchestrator.ndt_table_facts import read_ndt_tables

TABLES = {"ndt_event_inventory": "inventories", "ndt_event_members": "members",
          "ndt_event_records": "records", "ndt_event_reports": "reports"}


def build_r40_business_facts(state, run):
    groups = read_ndt_tables(state, run, TABLES, node_id=40)
    judgment = build_material_judgment([(name, rows, ("projectId",)) for name, rows in groups.items()])
    facts = {"sourceIssues": [], "sourceRecords": deepcopy(groups)}
    evidence = judgment["judgment"]
    rows = [row for items in groups.values() for row in items]
    if (len(groups["inventories"]) != 1 or any(type(row["evidence"].get("confidence")) not in (int, float)
            or not .75 <= row["evidence"]["confidence"] <= 1 for row in rows)
            or validate_evidence_grounding({**evidence, "facts": evidence["claimedFacts"], "minConfidence": .75})["result"] != "passed"):
        facts["sourceIssues"].append("r40_inventory_or_source_unavailable")
    else:
        inventory = deepcopy(groups["inventories"][0])
        inventory["members"] = deepcopy(groups["members"])
        facts["recordReportCorrespondence"] = {"projectId": run["projectId"], "inventory": inventory,
                                               "records": deepcopy(groups["records"]), "reports": deepcopy(groups["reports"])}
    return {"r40": facts, **judgment}
