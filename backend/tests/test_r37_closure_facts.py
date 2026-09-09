from copy import deepcopy

import pytest
from test_r37_closure import arguments

from libs.review_document_scope import freeze_document_scope
from libs.review_orchestrator.r37_facts import build_r37_business_facts
from libs.review_orchestrator.runtime_tools import dispatch_runtime_tool
from libs.review_tools.executor import build_tool_arguments


def fixture():
    body = arguments()
    groups = {"ndt_nonconformance_context": [{"projectId": "P1", "organizationId": "ORG1", "required": True}],
              "ndt_nonconformance_inventory": [body["caseInventory"]], "ndt_nonconformance_cases": body["caseInventory"]["cases"],
              "ndt_original_inspections": body["originalInspections"], "ndt_defect_dispositions": body["dispositions"],
              "ndt_reinspection_reports": body["reinspections"], "ndt_progressive_inventory": [body["progressiveInventory"]],
              "ndt_progressive_events": body["progressiveEvents"], "ndt_inspection_batches": body["inspectionBatches"],
              "ndt_inspection_batch_members": body["inspectionBatchMembers"], "ndt_progressive_reports": body["progressiveReports"],
              "ndt_defect_closure_links": body["closureLinks"]}
    tables = [{"tableId": schema, "businessSchema": schema, "pageNo": index + 1, "bbox": [0, 0, 100, 100],
               "structureConfidence": 0.9, "normalizedRows": deepcopy(rows)} for index, (schema, rows) in enumerate(groups.items())]
    state = {"documents": [{"id": "D1", "projectId": "P1", "tenantId": "T1"}], "versions": [{"id": "V1", "documentId": "D1", "tenantId": "T1"}],
             "ocr_parse_results": [{"documentVersionId": "V1", "tenantId": "T1", "tables": tables}]}
    run = {"projectId": "P1", "tenantId": "T1", "nodeId": 37, "inputDocumentVersionIds": ["V1"]}
    return state, run


def execute(state, run):
    run["documentScopeSnapshot"] = freeze_document_scope(run, state)
    facts = build_r37_business_facts(state, run)
    params = build_tool_arguments("evaluate_r37_defect_closure", {}, facts=facts, explicit={}, document_version_ids=run["inputDocumentVersionIds"], evidence_facts=[], evidence_refs=[])
    return facts, dispatch_runtime_tool(state, "evaluate_r37_defect_closure", params, context={"reviewRun": run})


@pytest.mark.parametrize("case,expected", [("ok", "passed"), ("missing_link", "evidence_insufficient"), ("unselected", "evidence_insufficient"), ("foreign_link", "evidence_insufficient")])
def test_scoped_sources_reach_closure_tool(case, expected):
    state, run = fixture()
    links = state["ocr_parse_results"][0]["tables"][-1]
    if case == "missing_link":
        links["normalizedRows"] = []
    elif case == "unselected":
        run["inputDocumentVersionIds"] = []
    elif case == "foreign_link":
        links["normalizedRows"][0]["projectId"] = "OTHER"
    facts, output = execute(state, run)
    assert output["result"] == expected
    if case == "ok":
        assert facts["r37"]["closureLinks"][0]["evidenceRefs"][0]["pageNo"] == 12
        links["normalizedRows"][0]["repairRound"] = 0
        with pytest.raises(ValueError, match="sources_changed"):
            build_r37_business_facts(state, run)


def test_closure_link_confidence_reaches_evidence_gate():
    state, run = fixture()
    state["ocr_parse_results"][0]["tables"][-1]["structureConfidence"] = 0.4
    facts, _ = execute(state, run)
    params = build_tool_arguments("validate_evidence_grounding", {"parameters": {"minConfidence": 0.75}}, facts=facts, explicit={},
        document_version_ids=run["inputDocumentVersionIds"], evidence_facts=facts["judgment"]["claimedFacts"], evidence_refs=facts["judgment"]["evidenceRefs"])
    assert dispatch_runtime_tool(state, "validate_evidence_grounding", params, context={"reviewRun": run})["result"] == "evidence_insufficient"
