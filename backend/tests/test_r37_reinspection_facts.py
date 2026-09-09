from copy import deepcopy

import pytest
from test_r37_facts import fixture as witness_fixture
from test_r37_reinspection import arguments

from libs.review_document_scope import freeze_document_scope
from libs.review_orchestrator.r37_facts import build_r37_business_facts
from libs.review_orchestrator.runtime_tools import dispatch_runtime_tool
from libs.review_tools.executor import build_tool_arguments


def fixture():
    state, run = witness_fixture()
    data = arguments()
    tables = state["ocr_parse_results"][0]["tables"]
    tables[3]["normalizedRows"] = [data["case"]]
    for schema, rows in (("ndt_original_inspections", [data["originalInspection"]]), ("ndt_defect_dispositions", [data["disposition"]]), ("ndt_reinspection_reports", data["reinspections"])):
        tables.append({"tableId": schema, "businessSchema": schema, "pageNo": len(tables) + 1, "bbox": [0, 0, 100, 100], "structureConfidence": 0.9, "normalizedRows": deepcopy(rows)})
    return state, run


def execute(state, run):
    run["documentScopeSnapshot"] = freeze_document_scope(run, state)
    facts = build_r37_business_facts(state, run)
    params = build_tool_arguments("evaluate_r37_reinspection", {}, facts=facts, explicit={},
        document_version_ids=run["inputDocumentVersionIds"], evidence_facts=[], evidence_refs=[])
    return facts, dispatch_runtime_tool(state, "evaluate_r37_reinspection", params, context={"reviewRun": run})


def test_inventory_reinspection_from_independent_selected_records():
    state, run = fixture()
    state["ocr_parse_results"][0]["tables"][-1]["normalizedRows"][0]["evidenceRefs"] = [{"documentVersionId": "OTHER", "pageNo": 99}]
    before = deepcopy(state)
    facts, output = execute(state, run)
    assert output["result"] == "passed", output
    assert len(output["facts"]["caseResults"]) == 1
    assert output["ruleVersion"] == "r37-reinspection-inventory-v1"
    assert facts["r37"]["reinspections"][0]["evidenceRefs"][0]["pageNo"] == 10
    assert {ref["documentVersionId"] for ref in output["evidenceRefs"]} == {"V1"}
    assert state == before
    state["ocr_parse_results"][0]["tables"][-1]["normalizedRows"][0]["status"] = "unqualified"
    with pytest.raises(ValueError, match="sources_changed"):
        build_r37_business_facts(state, run)


@pytest.mark.parametrize("case", ["unselected", "missing_original", "ambiguous_original", "missing_disposition", "duplicate_case", "count", "old_round", "orphan", "wrong_project", "missing_reinspection"])
def test_incomplete_inventory_or_source_records_cannot_pass(case):
    state, run = fixture()
    tables = state["ocr_parse_results"][0]["tables"]
    if case == "unselected":
        run["inputDocumentVersionIds"] = []
    elif case == "missing_original":
        tables[-3]["normalizedRows"] = []
    elif case == "ambiguous_original":
        tables[-3]["normalizedRows"] *= 2
    elif case == "missing_disposition":
        tables[-2]["normalizedRows"] = []
    elif case == "duplicate_case":
        tables[3]["normalizedRows"] *= 2
        tables[2]["normalizedRows"][0]["caseCount"] = 2
    elif case == "count":
        tables[2]["normalizedRows"][0]["caseCount"] = 0
    elif case == "old_round":
        tables[-1]["normalizedRows"][0]["repairRound"] = 0
    elif case == "orphan":
        tables[-1]["normalizedRows"].append({**tables[-1]["normalizedRows"][0], "caseId": "OTHER"})
    elif case == "wrong_project":
        tables[-1]["normalizedRows"][0]["projectId"] = "OTHER"
    else:
        tables[-1]["normalizedRows"] = []
    assert execute(state, run)[1]["result"] == "evidence_insufficient"


def test_every_case_is_evaluated_and_empty_complete_inventory_is_not_applicable():
    state, run = fixture()
    tables = state["ocr_parse_results"][0]["tables"]
    second = deepcopy(tables[3]["normalizedRows"][0])
    second.update(caseId="C2", objectId="W2", originalInspectionId="I2")
    tables[3]["normalizedRows"].append(second)
    tables[2]["normalizedRows"][0]["caseCount"] = 2
    output = execute(state, run)[1]
    assert output["result"] == "evidence_insufficient"
    assert len(output["facts"]["caseResults"]) == 2
    tables[3]["normalizedRows"] = []
    tables[2]["normalizedRows"][0]["caseCount"] = 0
    tables[-2]["normalizedRows"] = tables[-1]["normalizedRows"] = []
    assert execute(state, run)[1]["result"] == "not_applicable"


@pytest.mark.parametrize("case,expected", [("failed", "failed"), ("not_applicable", "not_applicable"), ("low_confidence", "evidence_insufficient")])
def test_reinspection_results_and_source_gate(case, expected):
    state, run = fixture()
    tables = state["ocr_parse_results"][0]["tables"]
    if case == "failed":
        tables[-1]["normalizedRows"][0]["status"] = "unqualified"
    elif case == "not_applicable":
        tables[0]["normalizedRows"][0]["required"] = False
    else:
        tables[-1]["structureConfidence"] = 0.4
    facts, output = execute(state, run)
    if case == "low_confidence":
        params = build_tool_arguments("validate_evidence_grounding", {"parameters": {"minConfidence": 0.75}}, facts=facts, explicit={},
            document_version_ids=run["inputDocumentVersionIds"], evidence_facts=facts["judgment"]["claimedFacts"], evidence_refs=facts["judgment"]["evidenceRefs"])
        output = dispatch_runtime_tool(state, "validate_evidence_grounding", params, context={"reviewRun": run})
    assert output["result"] == expected


def test_explicit_single_case_arguments_are_not_silently_replaced_by_inventory_mode():
    state, run = fixture()
    facts, _ = execute(state, run)
    params = build_tool_arguments("evaluate_r37_reinspection", {}, facts=facts, explicit=arguments(),
        document_version_ids=run["inputDocumentVersionIds"], evidence_facts=[], evidence_refs=[])
    assert "caseInventory" not in params
    assert dispatch_runtime_tool(state, "evaluate_r37_reinspection", params, context={"reviewRun": run})["result"] == "passed"
    params["caseInventory"] = facts["r37"]["caseInventory"]
    assert dispatch_runtime_tool(state, "evaluate_r37_reinspection", params, context={"reviewRun": run})["result"] == "evidence_insufficient"
