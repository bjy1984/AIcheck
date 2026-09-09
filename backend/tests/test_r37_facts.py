from copy import deepcopy

import pytest
from test_r37_tools import arguments

from libs.review_document_scope import freeze_document_scope
from libs.review_orchestrator.r37_facts import R37_TABLES, build_r37_business_facts
from libs.review_orchestrator.runtime_tools import dispatch_runtime_tool
from libs.review_tools.executor import build_tool_arguments


def fixture():
    data = arguments()
    groups = {**data, "contexts": [{"projectId": "P1", "organizationId": "ORG1", "required": True}],
              "procedures": [data["procedure"]], "inventories": [data["caseInventory"]], "cases": data["caseInventory"]["cases"]}
    tables = [{"tableId": schema, "businessSchema": schema, "pageNo": index + 1, "bbox": [0, 0, 100, 100],
               "structureConfidence": 0.9, "normalizedRows": deepcopy(groups[key])} for index, (schema, key) in enumerate(R37_TABLES.items())]
    state = {"documents": [{"id": "D1", "projectId": "P1", "tenantId": "T1"}],
             "versions": [{"id": "V1", "documentId": "D1", "tenantId": "T1"}],
             "ocr_parse_results": [{"documentVersionId": "V1", "tenantId": "T1", "tables": tables}]}
    run = {"projectId": "P1", "tenantId": "T1", "nodeId": 37, "inputDocumentVersionIds": ["V1"]}
    return state, run


def execute(state, run):
    run["documentScopeSnapshot"] = freeze_document_scope(run, state)
    facts = build_r37_business_facts(state, run)
    params = build_tool_arguments("evaluate_ndt_nonconformance", {}, facts=facts, explicit={},
        document_version_ids=run["inputDocumentVersionIds"], evidence_facts=[], evidence_refs=[])
    return facts, dispatch_runtime_tool(state, "evaluate_ndt_nonconformance", params, context={"reviewRun": run})


def test_selected_source_records_reach_runtime_and_replace_embedded_references():
    state, run = fixture()
    tables = state["ocr_parse_results"][0]["tables"]
    tables[-1]["normalizedRows"][0]["evidenceRefs"] = [{"documentVersionId": "SECRET", "pageNo": 9}]
    before = deepcopy(state)
    facts, output = execute(state, run)
    assert output["result"] == "passed"
    ref = facts["r37"]["feedback"][0]["evidenceRefs"][0]
    assert ref["documentVersionId"] == "V1" and ref["tableId"] == "ndt_nonconformance_feedback" and ref["pageNo"] == 7
    assert state == before
    tables[-1]["normalizedRows"][0]["status"] = "nonconforming"
    with pytest.raises(ValueError, match="sources_changed"):
        build_r37_business_facts(state, run)


@pytest.mark.parametrize("case", ["unselected", "tenant", "project", "version", "ambiguous_context", "ambiguous_inventory", "missing_cases", "other_inventory", "missing_feedback", "other_feedback_inventory", "old_round", "template", "unknown_schema"])
def test_unavailable_ambiguous_or_unmatched_sources_cannot_pass(case):
    state, run = fixture()
    tables = state["ocr_parse_results"][0]["tables"]
    if case == "unselected":
        run["inputDocumentVersionIds"] = []
    elif case == "tenant":
        state["ocr_parse_results"][0]["tenantId"] = "OTHER"
    elif case == "project":
        state["documents"][0]["projectId"] = "OTHER"
    elif case == "version":
        state["versions"] = []
    elif case == "ambiguous_context":
        tables[0]["normalizedRows"] *= 2
    elif case == "ambiguous_inventory":
        tables[2]["normalizedRows"] *= 2
    elif case == "missing_cases":
        tables[3]["normalizedRows"] = []  # Embedded inventory.cases must not substitute for independent evidence.
    elif case == "other_inventory":
        tables[3]["normalizedRows"][0]["inventoryId"] = "OTHER"
    elif case == "missing_feedback":
        tables[-1]["normalizedRows"] = []
    elif case == "other_feedback_inventory":
        tables[-1]["normalizedRows"][0]["inventoryId"] = "OTHER"
    elif case == "old_round":
        tables[-1]["normalizedRows"][0]["repairRound"] = 0
    elif case == "template":
        tables[-1]["normalizedRows"][0]["status"] = "template"
    else:
        tables[-1]["businessSchema"] = "generic_table"
    assert execute(state, run)[1]["result"] == "evidence_insufficient"


@pytest.mark.parametrize("confidence,expected", [(0.9, "passed"), (0.4, "evidence_insufficient"), (None, "evidence_insufficient")])
def test_witness_source_confidence_reaches_real_evidence_gate(confidence, expected):
    state, run = fixture()
    state["ocr_parse_results"][0]["tables"][-1]["structureConfidence"] = confidence
    facts, _ = execute(state, run)
    params = build_tool_arguments("validate_evidence_grounding", {"parameters": {"minConfidence": 0.75}}, facts=facts, explicit={},
        document_version_ids=run["inputDocumentVersionIds"], evidence_facts=facts["judgment"]["claimedFacts"], evidence_refs=facts["judgment"]["evidenceRefs"])
    assert dispatch_runtime_tool(state, "validate_evidence_grounding", params, context={"reviewRun": run})["result"] == expected
