"""R11 explicit single-object sources; source ambiguity never selects a first row."""
from copy import deepcopy

from libs.review_orchestrator.deterministic_tools import validate_evidence_grounding
from libs.review_orchestrator.material_facts import build_material_judgment
from libs.review_orchestrator.ndt_table_facts import read_ndt_tables
from libs.review_tools.r11_parameters import SCOPE_FIELDS

TABLES = {"construction_comparison_context": "contexts", "construction_comparison_basis": "bases",
          "construction_comparison_parameters": "parameters"}


def build_r11_business_facts(state, run):
    groups = read_ndt_tables(state, run, TABLES, node_id=11)
    judgment = build_material_judgment([(name, rows, ("projectId", "objectId")) for name, rows in groups.items()])
    facts = {"sourceIssues": [], "sourceRecords": deepcopy(groups)}
    output = {"r11": facts, **judgment}
    if len(groups["contexts"]) != 1 or len(groups["bases"]) != 1:
        facts["sourceIssues"].append("r11_context_or_basis_ambiguous")
        return output
    scope = {key: groups["contexts"][0].get(key) for key in SCOPE_FIELDS}
    rows = [row for items in groups.values() for row in items]
    if any(any(row.get(key) != scope[key] for key in SCOPE_FIELDS) for row in rows):
        facts["sourceIssues"].append("r11_source_object_conflict")
        return output
    for key in ("planVersionId", "designVersionId"):
        versions = [row for row in state.get("versions", []) if row.get("id") == scope[key]
                    and row.get("tenantId") == run["tenantId"]]
        if scope[key] not in run.get("inputDocumentVersionIds", []) or len(versions) != 1:
            facts["sourceIssues"].append("r11_version_not_selected")
            return output
        documents = [row for row in state.get("documents", []) if row.get("id") == versions[0].get("documentId")
                     and row.get("projectId") == run["projectId"] and row.get("tenantId") == run["tenantId"]]
        if len(documents) != 1:
            facts["sourceIssues"].append("r11_document_outside_project")
            return output
    malformed = any(type(row["evidence"].get("confidence")) not in (int, float)
                    or not 0 <= row["evidence"]["confidence"] <= 1 or type(row.get("conflicted", False)) is not bool for row in rows)
    if malformed:
        facts["sourceIssues"].append("r11_source_confidence_invalid")
        return output
    checked = validate_evidence_grounding({**judgment["judgment"], "facts": judgment["judgment"]["claimedFacts"], "minConfidence": .75})
    if checked["result"] != "passed":
        facts["sourceIssues"].append("r11_source_gate_failed")
        return output
    facts["projectParameters"] = {"projectId": run["projectId"], "scope": scope,
                                 "basis": deepcopy(groups["bases"][0]), "parameters": deepcopy(groups["parameters"])}
    return output
