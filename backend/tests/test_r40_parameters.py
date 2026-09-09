from copy import deepcopy

import pytest
from test_r40_record_correspondence import fixture

from libs.review_orchestrator.r40_facts import build_r40_business_facts
from libs.review_tools.business_tools import dispatch_business_tool
from libs.review_tools.executor import build_tool_arguments


def inputs():
    state, run = fixture()
    tables = state["ocr_parse_results"][0]["tables"]
    member = tables[1]["normalizedRows"][0]
    member.update(requiredParameters=["detection_ratio"], parameterRequirementsComplete=True)
    scope = {key: member[key] for key in ("projectId", "objectId", "method", "eventId")}
    for schema, values in (("ndt_parameter_requirements", {"value": 10, "operator": "gte"}), ("ndt_parameter_values", {"value": 20})):
        tables.append({"tableId": schema, "businessSchema": schema, "pageNo": 1, "structureConfidence": .95,
                       "contentMarkdown": "合成检测比例要求与记录值", "normalizedRows": [{**scope, "parameter": "detection_ratio", "unit": "%", **values}]})
    return state, run


def evaluate(state, run):
    facts = build_r40_business_facts(state, run)
    arguments = build_tool_arguments("evaluate_r40_parameters", {"parameters": {}}, facts=facts, explicit={},
        document_version_ids=["V"], evidence_facts=facts["judgment"]["claimedFacts"], evidence_refs=facts["judgment"]["evidenceRefs"])
    return dispatch_business_tool("evaluate_r40_parameters", arguments)


@pytest.mark.parametrize("case,expected", [("above", "passed"), ("boundary", "passed"), ("below", "failed"),
    ("units", "evidence_insufficient"), ("bool", "evidence_insufficient"), ("nan", "evidence_insufficient"),
    ("missing", "evidence_insufficient"), ("duplicate", "evidence_insufficient"), ("wrong_event", "evidence_insufficient"),
    ("low_confidence", "evidence_insufficient"), ("undeclared", "evidence_insufficient"), ("not_applicable", "not_applicable")])
def test_explicit_requirements_compare_only_same_event_and_units(case, expected):
    state, run = inputs()
    tables = state["ocr_parse_results"][0]["tables"]
    value = tables[-1]["normalizedRows"][0]
    if case == "boundary": value["value"] = 10
    if case == "below": value["value"] = 9
    if case == "units": value["unit"] = "fraction"
    if case == "bool": value["value"] = True
    if case == "nan": value["value"] = float("nan")
    if case == "missing": tables[-1]["normalizedRows"] = []
    if case == "duplicate": tables[-1]["normalizedRows"] *= 2
    if case == "wrong_event": value["eventId"] = "OTHER"
    if case == "low_confidence": tables[-1]["structureConfidence"] = .3
    if case == "undeclared": value["parameter"] = "other"
    if case == "not_applicable":
        tables[1]["normalizedRows"][0]["applicable"] = False
        tables[-1]["normalizedRows"] = tables[-2]["normalizedRows"] = []
    output = evaluate(state, run)
    assert output["result"] == expected
    assert output["facts"]["wholeRuleAcceptance"] == "not_evaluated"


def test_known_failure_remains_when_another_required_parameter_is_missing():
    state, run = inputs()
    tables = state["ocr_parse_results"][0]["tables"]
    tables[1]["normalizedRows"][0]["requiredParameters"].append("technical_grade")
    tables[-1]["normalizedRows"][0]["value"] = 9
    before = deepcopy(state)
    assert evaluate(state, run)["result"] == "failed"
    assert state == before


@pytest.mark.parametrize("operator,expected,actual,unit,status", [("lte", 10, 11, "%", "failed"),
    ("lte", 10, 10, "%", "passed"), ("eq", "AB", "AB", "", "passed"),
    ("eq", "AB", "A", "", "failed"), ("gte", "AB", "A", "", "evidence_insufficient")])
def test_comparison_operator_is_explicit(operator, expected, actual, unit, status):
    state, run = inputs()
    tables = state["ocr_parse_results"][0]["tables"]
    tables[-2]["normalizedRows"][0].update(operator=operator, value=expected, unit=unit)
    tables[-1]["normalizedRows"][0].update(value=actual, unit=unit)
    assert evaluate(state, run)["result"] == status


def test_actual_binding_executes_parameter_check_without_releasing_rule():
    from libs.business_pack import load_business_pack
    from libs.review_orchestrator.runtime_tools import dispatch_runtime_tool, runtime_tool_catalog
    from libs.review_tools import compile_node_tool_plan, execute_node_tool_plan

    state, run = inputs()
    facts = build_r40_business_facts(state, run)
    plan = compile_node_tool_plan(load_business_pack("engineering_inspection_v1"), "R40",
        available_tools={row["name"] for row in runtime_tool_catalog()})
    output = execute_node_tool_plan(plan, facts=facts, document_version_ids=["V"],
        evidence_facts=facts["judgment"]["claimedFacts"], evidence_refs=facts["judgment"]["evidenceRefs"],
        tool_runner=lambda name, args: dispatch_runtime_tool(state, name, args, context={"reviewRun": run}))
    tool = next(row for row in output["atomicResults"][0]["toolResults"] if row["toolName"] == "evaluate_r40_parameters")
    assert tool["result"] == "passed"
    assert tool["evidenceRefs"]
    assert output["result"] == "evidence_insufficient"
