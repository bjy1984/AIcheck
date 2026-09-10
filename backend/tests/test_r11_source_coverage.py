from copy import deepcopy

import pytest
from test_r11_parameters import call, fixture

from libs.review_document_scope import freeze_document_scope
from libs.review_orchestrator.design_facts import build_design_business_facts


def evaluate(state, run):
    run["documentScopeSnapshot"] = freeze_document_scope(run, state)
    facts = build_design_business_facts(state, run)
    return call(facts["r11"].get("projectParameters", {})), facts


@pytest.mark.parametrize("different", [False, True])
@pytest.mark.parametrize("end", [None, 3, 9])
def test_selected_unread_pages_block_pass_but_keep_known_parameter_difference(end, different):
    state, run = fixture()
    parse = state["ocr_parse_results"][0]
    parse["metadata"] = {"recognitionPageCoverage": {"complete": False, "unprocessedPageNos": [9]}}
    if end:
        run["inputDocumentPageRanges"] = {"PLAN": {"start": 1, "end": end}}
    if different:
        parse["tables"][1]["normalizedRows"][0]["value"] = "16Mn"
    before = deepcopy(state)
    output, facts = evaluate(state, run)
    assert output["result"] == ("failed" if different else "passed" if end == 3 else "evidence_insufficient")
    assert bool(facts["r11"]["selectionIssues"]) == (end != 3)
    assert output["facts"]["coverage"]["complete"] == (end == 3)
    assert state == before


@pytest.mark.parametrize("case", ["duplicate_version", "duplicate_document", "duplicate_parse", "missing_parse", "unknown_gap"])
def test_source_ambiguity_or_unknown_page_gap_never_passes(case):
    state, run = fixture()
    if case == "duplicate_version": state["versions"].append(deepcopy(state["versions"][0]))
    if case == "duplicate_document": state["documents"].append(deepcopy(state["documents"][0]))
    if case == "duplicate_parse":
        extra = deepcopy(state["ocr_parse_results"][0]);extra.update(id="OTHER", tables=[])
        state["ocr_parse_results"].append(extra)
    if case == "missing_parse":
        state["versions"].append({"id": "EXTRA", "documentId": state["documents"][0]["id"], "tenantId": "T"})
        run["inputDocumentVersionIds"].append("EXTRA")
    if case == "unknown_gap":
        state["ocr_parse_results"][0]["metadata"] = {"recognitionPageCoverage": {"complete": False, "unprocessedPageNos": []}}
        run["inputDocumentPageRanges"] = {"PLAN": {"start": 1, "end": 3}}
    output, _ = evaluate(state, run)
    assert output["result"] == "evidence_insufficient"


def test_unselected_parse_gap_does_not_expand_selected_scope():
    state, run = fixture()
    extra = deepcopy(state["ocr_parse_results"][0])
    extra.update(id="OTHER", documentVersionId="OTHER", metadata={"recognitionPageCoverage": {"complete": False}})
    state["ocr_parse_results"].append(extra)
    assert evaluate(state, run)[0]["result"] == "passed"


def test_source_identity_ambiguity_also_blocks_negative_comparison():
    state, run = fixture()
    state["versions"].append(deepcopy(state["versions"][0]))
    state["ocr_parse_results"][0]["tables"][1]["normalizedRows"][0]["value"] = "16Mn"
    assert evaluate(state, run)[0]["result"] == "evidence_insufficient"


@pytest.mark.parametrize("different", [False, True])
def test_real_node_plan_receives_selected_source_issues(different):
    from libs.business_pack import load_business_pack
    from libs.review_orchestrator.runtime_tools import dispatch_runtime_tool, runtime_tool_catalog
    from libs.review_tools import compile_node_tool_plan, execute_node_tool_plan

    state, run = fixture()
    state["ocr_parse_results"][0]["metadata"] = {"recognitionPageCoverage": {"complete": False, "unprocessedPageNos": [9]}}
    if different:
        state["ocr_parse_results"][0]["tables"][1]["normalizedRows"][0]["value"] = "16Mn"
    _, facts = evaluate(state, run)
    plan = compile_node_tool_plan(load_business_pack("engineering_inspection_v1"), "R11",
                                  available_tools={item["name"] for item in runtime_tool_catalog()})
    output = execute_node_tool_plan(plan, facts=facts, document_version_ids=run["inputDocumentVersionIds"],
        evidence_facts=facts["judgment"]["claimedFacts"], evidence_refs=facts["judgment"]["evidenceRefs"],
        tool_runner=lambda name, args: dispatch_runtime_tool(state, name, args, context={"reviewRun": run}))
    atomic = next(row for row in output["atomicResults"] if row["atomicCheckId"] == "AC-R11-02")
    assert atomic["result"] == ("failed" if different else "evidence_insufficient")
    assert output["result"] != "passed"


@pytest.mark.parametrize("applicable", [False, True])
def test_direct_single_object_call_cannot_ignore_coverage_issue(applicable):
    from test_r11_parameters import arguments

    body = arguments()
    body["basis"]["applicable"] = applicable
    body["selectionIssues"] = [{"code": "r11_selected_pages_incomplete"}]
    output = call(body)
    assert output["result"] == "evidence_insufficient"
    assert output["facts"]["selectionIssues"] == body["selectionIssues"]
