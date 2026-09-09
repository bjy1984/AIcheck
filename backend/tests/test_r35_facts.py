from copy import deepcopy

import pytest
from test_r35_tools import arguments

from libs.review_document_scope import freeze_document_scope
from libs.review_orchestrator.r35_facts import R35_TABLES, build_r35_business_facts
from libs.review_tools.business_tools import dispatch_business_tool
from libs.review_tools.executor import build_tool_arguments


def fixture():
    data = arguments()
    records = {**data, "equipment": [{"projectId": "P1", "organizationId": "NDT1", "equipmentId": "UT1"}],
               "activities": [{"projectId": "P1", "organizationId": "NDT1", "activityDate": data["activityDate"], "required": True}]}
    tables = [{"tableId": schema, "businessSchema": schema, "pageNo": index + 1, "bbox": [0, 0, 100, 100],
               "normalizedRows": deepcopy(records[group])} for index, (schema, group) in enumerate(R35_TABLES.items())]
    state = {"documents": [{"id": "D1", "projectId": "P1", "tenantId": "T1"}],
             "versions": [{"id": "V1", "documentId": "D1", "tenantId": "T1"}],
             "ocr_parse_results": [{"documentVersionId": "V1", "tenantId": "T1", "tables": tables}]}
    run = {"projectId": "P1", "tenantId": "T1", "nodeId": 35, "inputDocumentVersionIds": ["V1"]}
    return state, run


def execute(state, run):
    run["documentScopeSnapshot"] = freeze_document_scope(run, state)
    facts = build_r35_business_facts(state, run)
    params = build_tool_arguments("evaluate_ndt_quality_system", {}, facts=facts, explicit={},
                                  document_version_ids=run["inputDocumentVersionIds"], evidence_facts=[], evidence_refs=[])
    return facts, dispatch_business_tool("evaluate_ndt_quality_system", params)


def test_r35_selected_tables_reach_dedicated_tool_with_real_locations():
    state, run = fixture()
    before = deepcopy(state)
    facts, output = execute(state, run)
    assert output["result"] == "passed"
    assert output["ruleVersion"] == "r35-site-quality-system-v1"
    reference = facts["r35"]["manual"][0]["evidenceRefs"][0]
    assert reference["documentVersionId"] == "V1" and reference["pageNo"] == 1
    assert reference["tableId"] == "ndt_quality_manual" and reference["rowIndex"] == 0
    assert state == before


@pytest.mark.parametrize("case", ["no_selection", "other_tenant", "other_project", "missing_version", "ambiguous_activity", "template", "unrecognized_schema"])
def test_r35_unavailable_or_ambiguous_ocr_cannot_pass(case):
    state, run = fixture()
    tables = state["ocr_parse_results"][0]["tables"]
    if case == "no_selection":
        run["inputDocumentVersionIds"] = []
    elif case == "other_tenant":
        state["ocr_parse_results"][0]["tenantId"] = "OTHER"
    elif case == "other_project":
        state["documents"][0]["projectId"] = "OTHER"
    elif case == "missing_version":
        state["versions"] = []
    elif case == "ambiguous_activity":
        tables[-1]["normalizedRows"].append(deepcopy(tables[-1]["normalizedRows"][0]))
    elif case == "template":
        tables[3]["normalizedRows"][0]["status"] = "template"
    elif case == "unrecognized_schema":
        tables[0]["businessSchema"] = "generic_table"
    assert execute(state, run)[1]["result"] == "evidence_insufficient"


def test_r35_wrong_embedded_reference_is_replaced_and_source_drift_is_rejected():
    state, run = fixture()
    state["ocr_parse_results"][0]["tables"][0]["normalizedRows"][0]["evidenceRefs"] = [{"documentVersionId": "SECRET", "pageNo": 99}]
    facts, output = execute(state, run)
    assert output["result"] == "passed"
    assert facts["r35"]["manual"][0]["evidenceRefs"][0]["documentVersionId"] == "V1"
    state["ocr_parse_results"][0]["tables"][0]["normalizedRows"][0]["status"] = "nonconforming"
    with pytest.raises(ValueError, match="sources_changed"):
        build_r35_business_facts(state, run)


@pytest.mark.parametrize("confidence,conflicted,expected", [(None, False, "evidence_insufficient"), (0.6, False, "evidence_insufficient"), (0.9, True, "evidence_insufficient"), (0.9, False, "passed")])
def test_r35_extracted_claims_reach_existing_evidence_gate(confidence, conflicted, expected):
    from libs.review_orchestrator.deterministic_tools import validate_evidence_grounding

    state, run = fixture()
    for table in state["ocr_parse_results"][0]["tables"]:
        table["structureConfidence"] = confidence
        for row in table["normalizedRows"]:
            row["conflicted"] = conflicted
    facts, _ = execute(state, run)
    params = build_tool_arguments("validate_evidence_grounding", {"parameters": {"minConfidence": 0.75}},
                                  facts=facts, explicit={}, document_version_ids=["V1"],
                                  evidence_facts=facts["judgment"]["claimedFacts"], evidence_refs=facts["judgment"]["evidenceRefs"])
    assert validate_evidence_grounding(params)["result"] == expected
    assert all(row["evidenceRefIds"] for row in facts["judgment"]["claimedFacts"])


@pytest.mark.parametrize("scenario,expected", [("passed", "passed"), ("failed", "failed"), ("missing", "evidence_insufficient"), ("not_applicable", "not_applicable"), ("not_applicable_only_activity", "not_applicable"), ("not_applicable_low_confidence", "evidence_insufficient"), ("low_confidence", "evidence_insufficient")])
def test_r35_real_binding_plan_four_states(scenario, expected):
    from libs.business_pack import load_business_pack
    from libs.review_orchestrator.runtime_tools import dispatch_runtime_tool, runtime_tool_catalog
    from libs.review_tools import compile_node_tool_plan, execute_node_tool_plan

    state, run = fixture()
    tables = state["ocr_parse_results"][0]["tables"]
    for table in tables:
        table["structureConfidence"] = 0.9
    if scenario == "failed":
        tables[3]["normalizedRows"][0]["status"] = "nonconforming"
    elif scenario == "missing":
        tables[3]["normalizedRows"] = []
    elif scenario.startswith("not_applicable"):
        tables[-1]["normalizedRows"][0]["required"] = False
        if scenario == "not_applicable_only_activity":
            tables[:] = [tables[-1]]
        elif scenario == "not_applicable_low_confidence":
            tables[-1]["structureConfidence"] = 0.5
    elif scenario == "low_confidence":
        tables[3]["structureConfidence"] = 0.5
    facts, _ = execute(state, run)
    plan = compile_node_tool_plan(load_business_pack("engineering_inspection_v1"), "R35",
                                  available_tools={item["name"] for item in runtime_tool_catalog()})
    output = execute_node_tool_plan(plan, facts=facts, document_version_ids=["V1"],
        evidence_facts=facts["judgment"]["claimedFacts"], evidence_refs=facts["judgment"]["evidenceRefs"],
        tool_runner=lambda name, args: dispatch_runtime_tool(state, name, args, context={"reviewRun": run}))
    assert output["result"] == expected, output
    assert len(output["atomicResults"]) == 2
