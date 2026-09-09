"""Selected-version, source-gated R40 record/report event inventory."""
from copy import deepcopy

from libs.ocr.page_coverage import review_coverage_gap
from libs.review_input_data import selected_parse_results
from libs.review_orchestrator.deterministic_tools import validate_evidence_grounding
from libs.review_orchestrator.material_facts import build_material_judgment
from libs.review_orchestrator.ndt_table_facts import read_ndt_tables
from libs.review_orchestrator.r40_ocr_parameters import supplement_ocr_parameters
from libs.review_orchestrator.r40_ocr_records import supplement_ocr_records
from libs.review_orchestrator.r40_ocr_requirements import supplement_ocr_requirements

TABLES = {"ndt_event_inventory": "inventories", "ndt_event_members": "members",
          "ndt_event_records": "records", "ndt_event_reports": "reports",
          "ndt_parameter_requirements": "requirements", "ndt_parameter_values": "values"}


def build_r40_business_facts(state, run):
    groups = read_ndt_tables(state, run, TABLES, node_id=40)
    issues = []
    parses = selected_parse_results(state, {}, context={"reviewRun": run})
    for version_id in sorted(set(run.get("inputDocumentVersionIds") or [])):
        versions = [row for row in state.get("versions", []) if row.get("id") == version_id
                    and row.get("tenantId") == run["tenantId"]]
        documents = [row for row in state.get("documents", []) if len(versions) == 1
                     and row.get("id") == versions[0].get("documentId") and row.get("tenantId") == run["tenantId"]
                     and row.get("projectId") == run["projectId"]]
        candidates = [row for row in parses if row.get("documentVersionId") == version_id
                      and row.get("tenantId") == run["tenantId"]]
        if len(versions) != 1 or len(documents) != 1 or len(candidates) != 1:
            issues.append({"code": "r40_selected_source_missing_or_ambiguous", "documentVersionId": version_id})
            continue
        gap = review_coverage_gap(candidates[0])
        if gap:
            issues.append({**gap, "code": "r40_selected_pages_incomplete", "documentVersionId": version_id})
    raw_fields, raw_issues = supplement_ocr_records(parses, run, groups)
    parameter_fields, parameter_issues = supplement_ocr_parameters(parses, run, groups)
    requirement_fields, requirement_issues = supplement_ocr_requirements(parses, run, groups)
    raw_fields.extend([*parameter_fields, *requirement_fields])
    issues.extend([*raw_issues, *parameter_issues, *requirement_issues])
    groups["ocrIdentityFields"] = raw_fields
    judgment = build_material_judgment([(name, rows, ("value",) if name == "ocrIdentityFields" else ("projectId",)) for name, rows in groups.items()])
    facts = {"sourceIssues": [], "sourceRecords": deepcopy(groups)}
    evidence = judgment["judgment"]
    rows = [row for items in groups.values() for row in items]
    if (any(issue["code"] == "r40_selected_source_missing_or_ambiguous" for issue in issues)
            or len(groups["inventories"]) != 1 or any(type(row["evidence"].get("confidence")) not in (int, float)
            or not .75 <= row["evidence"]["confidence"] <= 1 for row in rows)
            or validate_evidence_grounding({**evidence, "facts": evidence["claimedFacts"], "minConfidence": .75})["result"] != "passed"):
        facts["sourceIssues"].append("r40_inventory_or_source_unavailable")
    else:
        inventory = deepcopy(groups["inventories"][0])
        inventory["members"] = deepcopy(groups["members"])
        facts["recordReportCorrespondence"] = {"projectId": run["projectId"], "inventory": inventory,
                                               "records": deepcopy(groups["records"]), "reports": deepcopy(groups["reports"]), "selectionIssues": issues}
    if "recordReportCorrespondence" in facts:
        facts["parameterComparison"] = {"projectId": run["projectId"], "inventory": deepcopy(inventory),
            "requirements": deepcopy(groups["requirements"]), "values": deepcopy(groups["values"]), "selectionIssues": issues}
    facts["selectionIssues"] = issues
    return {"r40": facts, **judgment}
