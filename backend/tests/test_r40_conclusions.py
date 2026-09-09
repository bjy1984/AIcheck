from copy import deepcopy

import pytest
from test_r40_ocr_records import raw_fixture

from libs.review_orchestrator.r40_facts import build_r40_business_facts
from libs.review_tools.business_tools import dispatch_business_tool
from libs.review_tools.executor import build_tool_arguments


def inputs(record_value="合格", report_value="合格"):
    state, run = raw_fixture()
    for parse, value in zip(state["ocr_parse_results"][1:], (record_value, report_value), strict=True):
        parse["fragments"].append({"text": "结论：" + value, "pageNo": 6, "bbox": [1, 2, 30, 40], "confidence": .95})
        parse["fields"].append({"fieldCode": "conclusion", "fieldValue": value, "pageNo": 6, "bbox": [1, 2, 30, 40], "confidence": .95})
    return state, run


def evaluate(state, run):
    facts = build_r40_business_facts(state, run)
    arguments = build_tool_arguments("evaluate_r40_conclusions", {"parameters": {}}, facts=facts, explicit={},
        document_version_ids=run["inputDocumentVersionIds"], evidence_facts=facts["judgment"]["claimedFacts"], evidence_refs=facts["judgment"]["evidenceRefs"])
    return dispatch_business_tool("evaluate_r40_conclusions", arguments)


@pytest.mark.parametrize("left,right,expected", [("合格", "合格", "passed"), ("符合", "合格", "passed"), ("不符合", "不合格", "passed"), ("不合格", "不合格", "passed"),
    ("不合格", "合格", "failed"), ("合格", "不合格", "failed"), ("待评定", "合格", "evidence_insufficient")])
def test_corresponding_original_conclusions_are_compared_without_rejudging_acceptance(left, right, expected):
    state, run = inputs(left, right)
    before = deepcopy(state)
    output = evaluate(state, run)
    assert output["result"] == expected
    assert output["facts"]["wholeRuleAcceptance"] == "not_evaluated"
    assert state == before
    if expected in {"passed", "failed"}:
        assert {ref["documentVersionId"] for ref in output["evidenceRefs"]} == {"REC-V", "REP-V"}


@pytest.mark.parametrize("case", ["missing", "wrong_quote", "low_confidence", "other_event", "outside_pages"])
def test_unsupported_conclusion_cannot_produce_a_positive_comparison(case):
    from libs.review_document_scope import freeze_document_scope

    state, run = inputs()
    report = state["ocr_parse_results"][2]
    if case == "missing": report["fields"].pop()
    if case == "wrong_quote": report["fragments"][-1]["text"] = "结论：不合格"
    if case == "low_confidence": report["fields"][-1]["confidence"] = .3
    if case == "other_event":
        next(row for row in report["fields"] if row["fieldCode"] == "detection_event_no")["fieldValue"] = "OTHER"
        report["fragments"][2]["text"] = "检测事件编号：OTHER"
    if case == "outside_pages":
        run["inputDocumentPageRanges"] = {"REP-V": {"start": 1, "end": 5}}
        run["documentScopeSnapshot"] = freeze_document_scope(run, state)
    assert evaluate(state, run)["result"] == "evidence_insufficient"


def test_actual_node_binding_executes_conclusion_comparison_and_preserves_blocker():
    from libs.business_pack import load_business_pack
    from libs.review_orchestrator.runtime_tools import dispatch_runtime_tool, runtime_tool_catalog
    from libs.review_tools import compile_node_tool_plan, execute_node_tool_plan

    state, run = inputs("不合格", "合格")
    facts = build_r40_business_facts(state, run)
    plan = compile_node_tool_plan(load_business_pack("engineering_inspection_v1"), "R40",
        available_tools={row["name"] for row in runtime_tool_catalog()})
    output = execute_node_tool_plan(plan, facts=facts, document_version_ids=run["inputDocumentVersionIds"],
        evidence_facts=facts["judgment"]["claimedFacts"], evidence_refs=facts["judgment"]["evidenceRefs"],
        tool_runner=lambda name, args: dispatch_runtime_tool(state, name, args, context={"reviewRun": run}))
    decision = output["atomicResults"][0]
    tool = next(row for row in decision["toolResults"] if row["toolName"] == "evaluate_r40_conclusions")
    assert tool["result"] == "failed"
    assert output["result"] == "failed"
    assert "pending_capability:report_results" in decision["warnings"]
