from copy import deepcopy

import pytest

from libs.business_pack import load_business_pack
from libs.review_orchestrator.ndt_fact_builders import NDT_FACT_BUILDERS
from libs.review_tools.business_tools import dispatch_business_tool
from libs.review_tools.executor import build_tool_arguments


def fixture():
    event = {"projectId": "P", "objectId": "W1", "method": "RT", "eventId": "E1"}
    groups = {"ndt_event_inventory": [{"projectId": "P", "complete": True}],
              "ndt_event_members": [{**event, "applicable": True}],
              "ndt_event_records": [{**event, "recordId": "REC1"}],
              "ndt_event_reports": [{**event, "recordId": "REC1"}]}
    state = {"documents": [{"id": "D", "projectId": "P", "tenantId": "T"}],
             "versions": [{"id": "V", "documentId": "D", "tenantId": "T"}],
             "ocr_parse_results": [{"id": "OCR", "documentVersionId": "V", "tenantId": "T", "tables": [
                 {"tableId": name, "businessSchema": name, "pageNo": 1, "structureConfidence": .95,
                  "contentMarkdown": "合成记录原文", "normalizedRows": rows} for name, rows in groups.items()]}]}
    run = {"projectId": "P", "tenantId": "T", "nodeId": 40, "inputDocumentVersionIds": ["V"]}
    return state, run


def evaluate(state, run):
    facts = NDT_FACT_BUILDERS[40](state, run)
    binding = next(row for row in load_business_pack("engineering_inspection_v1")["atomicCheckToolBindings"] if row["atomicCheckId"] == "AC-R40-01")
    arguments = build_tool_arguments("evaluate_ndt_process", binding, facts=facts, explicit={},
        document_version_ids=["V"], evidence_facts=facts["judgment"]["claimedFacts"], evidence_refs=facts["judgment"]["evidenceRefs"])
    return dispatch_business_tool("evaluate_ndt_process", arguments)


@pytest.mark.parametrize("case,expected", [("matched", "passed"), ("mismatch", "failed"),
    ("missing_report", "evidence_insufficient"), ("duplicate", "evidence_insufficient"),
    ("other_event", "evidence_insufficient"), ("low_confidence", "evidence_insufficient"),
    ("other_project", "evidence_insufficient"), ("not_applicable", "not_applicable"),
    ("unknown_applicability", "evidence_insufficient")])
def test_selected_sources_feed_actual_r40_binding(case, expected):
    state, run = fixture()
    tables = state["ocr_parse_results"][0]["tables"]
    if case == "mismatch": tables[3]["normalizedRows"][0]["recordId"] = "REC2"
    if case == "missing_report": tables[3]["normalizedRows"] = []
    if case == "duplicate": tables[3]["normalizedRows"] *= 2
    if case == "other_event": tables[3]["normalizedRows"][0]["eventId"] = "E2"
    if case == "low_confidence": tables[3]["structureConfidence"] = .5
    if case == "other_project": state["documents"][0]["projectId"] = "OTHER"
    if case == "not_applicable":
        tables[1]["normalizedRows"][0]["applicable"] = False
        tables[2]["normalizedRows"] = tables[3]["normalizedRows"] = []
    if case == "unknown_applicability": tables[1]["normalizedRows"][0].pop("applicable")
    before = deepcopy(state)
    output = evaluate(state, run)
    assert output["result"] == expected
    assert output["facts"]["wholeRuleAcceptance"] == "not_evaluated"
    assert state == before
    if expected in {"passed", "failed", "not_applicable"}:
        assert output["evidenceRefs"] and {ref["documentVersionId"] for ref in output["evidenceRefs"]} == {"V"}


def test_actual_node_plan_keeps_remaining_capability_gate():
    from libs.review_orchestrator.runtime_tools import dispatch_runtime_tool, runtime_tool_catalog
    from libs.review_tools import compile_node_tool_plan, execute_node_tool_plan

    state, run = fixture()
    facts = NDT_FACT_BUILDERS[40](state, run)
    pack = load_business_pack("engineering_inspection_v1")
    plan = compile_node_tool_plan(pack, "R40", available_tools={row["name"] for row in runtime_tool_catalog()})
    output = execute_node_tool_plan(plan, facts=facts, document_version_ids=["V"],
        evidence_facts=facts["judgment"]["claimedFacts"], evidence_refs=facts["judgment"]["evidenceRefs"],
        tool_runner=lambda name, args: dispatch_runtime_tool(state, name, args, context={"reviewRun": run}))
    decision = output["atomicResults"][0]
    dedicated = next(row for row in decision["toolResults"] if row["toolName"] == "evaluate_ndt_process")
    assert dedicated["result"] == "passed"
    assert output["result"] == "evidence_insufficient"
    assert "pending_capability:technical_parameters" in decision["warnings"]
    with pytest.raises(ValueError, match="Formal review requires"):
        compile_node_tool_plan(pack, "R40", available_tools=set(), require_published=True)


def test_all_declared_events_are_checked_and_known_mismatch_is_preserved():
    state, run = fixture()
    tables = state["ocr_parse_results"][0]["tables"]
    extra = deepcopy(tables[1]["normalizedRows"][0])
    extra.update(objectId="W2", eventId="E2")
    tables[1]["normalizedRows"].append(extra)
    # A missing second event cannot disappear behind the first matched pair.
    assert evaluate(state, run)["result"] == "evidence_insufficient"
    tables[3]["normalizedRows"][0]["recordId"] = "WRONG"
    assert evaluate(state, run)["result"] == "failed"
