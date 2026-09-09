from copy import deepcopy

import pytest
from test_r36_tools import arguments

from libs.business_pack import load_business_pack
from libs.review_document_scope import freeze_document_scope
from libs.review_orchestrator.r36_facts import build_r36_business_facts
from libs.review_orchestrator.runtime_tools import dispatch_runtime_tool, runtime_tool_catalog
from libs.review_tools import compile_node_tool_plan, execute_node_tool_plan


def fixture():
    data = arguments()
    def table(schema, rows):
        return {"tableId": schema, "businessSchema": schema, "pageNo": 2, "bbox": [0, 0, 100, 100],
                "structureConfidence": 0.9, "normalizedRows": deepcopy(rows)}
    state = {"documents": [{"id": item, "projectId": "P1", "tenantId": "T1"} for item in ("DESIGN", "PLAN")],
             "versions": [{"id": item + "-V1", "documentId": item, "tenantId": "T1"} for item in ("DESIGN", "PLAN")],
             "ocr_parse_results": [
                 {"documentVersionId": "DESIGN-V1", "tenantId": "T1", "tables": [
                     table("ndt_plan_context", [{"projectId": "P1", "required": True}]),
                     table("ndt_design_requirements", data["requirements"])]},
                 {"documentVersionId": "PLAN-V1", "tenantId": "T1", "tables": [
                     table("ndt_plan_approval", [data["plan"]]), table("ndt_plan_items", data["plan"]["items"])]}]}
    run = {"projectId": "P1", "tenantId": "T1", "nodeId": 36, "inputDocumentVersionIds": ["DESIGN-V1", "PLAN-V1"]}
    return state, run


def execute(state, run):
    run["documentScopeSnapshot"] = freeze_document_scope(run, state)
    facts = build_r36_business_facts(state, run)
    plan = compile_node_tool_plan(load_business_pack("engineering_inspection_v1"), "R36",
                                  available_tools={row["name"] for row in runtime_tool_catalog()})
    output = execute_node_tool_plan(plan, facts=facts, document_version_ids=run["inputDocumentVersionIds"],
        evidence_facts=facts["judgment"]["claimedFacts"], evidence_refs=facts["judgment"]["evidenceRefs"],
        tool_runner=lambda name, args: dispatch_runtime_tool(state, name, args, context={"reviewRun": run}))
    return facts, output


@pytest.mark.parametrize("case,expected", [("ok", "passed"), ("ratio", "failed"), ("missing", "evidence_insufficient"), ("optional", "not_applicable"), ("low_confidence", "evidence_insufficient"), ("ambiguous", "evidence_insufficient"), ("unselected", "evidence_insufficient")])
def test_r36_typed_sources_through_actual_node_plan(case, expected):
    state, run = fixture()
    tables = state["ocr_parse_results"][1]["tables"]
    if case == "ratio":
        tables[1]["normalizedRows"][0]["ratioPercent"] = 10
    elif case == "missing":
        tables[1]["normalizedRows"] = []
    elif case == "optional":
        state["ocr_parse_results"][0]["tables"][0]["normalizedRows"][0]["required"] = False
    elif case == "low_confidence":
        tables[1]["structureConfidence"] = 0.5
    elif case == "ambiguous":
        tables[0]["normalizedRows"].append(deepcopy(tables[0]["normalizedRows"][0]))
    elif case == "unselected":
        run["inputDocumentVersionIds"] = ["DESIGN-V1"]
    before = deepcopy(state)
    _, output = execute(state, run)
    assert output["result"] == expected, output
    assert len(output["atomicResults"]) == 2
    assert state == before


@pytest.mark.parametrize("case", ["tenant", "project", "version"])
def test_r36_source_registry_scope_is_required(case):
    state, run = fixture()
    if case == "tenant":
        state["ocr_parse_results"][1]["tenantId"] = "OTHER"
    elif case == "project":
        state["documents"][1]["projectId"] = "OTHER"
    else:
        state["versions"].pop()
    assert execute(state, run)[1]["result"] == "evidence_insufficient"


def test_r36_evidence_is_from_actual_source_and_changes_require_new_run():
    state, run = fixture()
    state["ocr_parse_results"][1]["tables"][1]["normalizedRows"][0]["evidenceRefs"] = [{"documentVersionId": "OTHER", "pageNo": 99}]
    facts, output = execute(state, run)
    assert output["result"] == "passed"
    ref = facts["r36"]["plan"]["items"][0]["evidenceRefs"][0]
    assert ref["documentVersionId"] == "PLAN-V1" and ref["pageNo"] == 2
    state["ocr_parse_results"][1]["tables"][1]["normalizedRows"][0]["ratioPercent"] = 5
    with pytest.raises(ValueError, match="sources_changed"):
        build_r36_business_facts(state, run)


def test_r36_standard_requirement_table_reaches_full_plan_with_source_gate():
    state, run = fixture()
    requirement_table = state["ocr_parse_results"][0]["tables"][1]
    standard = deepcopy(requirement_table)
    standard.update(tableId="STANDARD-REQUIREMENT", businessSchema="ndt_standard_requirements")
    standard["normalizedRows"][0].update(standardRef="EXPLICIT-STANDARD", clauseRef="8.3", ratioPercent=100)
    state["ocr_parse_results"][0]["tables"].append(standard)
    facts, output = execute(state, run)
    assert output["result"] == "failed"
    assert facts["r36"]["standardRequirements"][0]["evidenceRefs"][0]["tableId"] == "STANDARD-REQUIREMENT"
    state["ocr_parse_results"][1]["tables"][1]["normalizedRows"][0]["ratioPercent"] = 100
    assert execute(state, run)[1]["result"] == "passed"
    standard["structureConfidence"] = 0.4
    assert execute(state, run)[1]["result"] == "evidence_insufficient"
