from copy import deepcopy

import pytest
from test_r37_closure_facts import fixture as closure_fixture
from test_r37_progressive import sourced

from libs.business_pack import load_business_pack
from libs.review_document_scope import freeze_document_scope
from libs.review_orchestrator.r37_facts import build_r37_business_facts
from libs.review_orchestrator.runtime_tools import dispatch_runtime_tool, runtime_tool_catalog
from libs.review_tools import compile_node_tool_plan, execute_node_tool_plan


def table(state, schema):
    return next(row for row in state["ocr_parse_results"][0]["tables"] if row["businessSchema"] == schema)


def fixture():
    state, run = closure_fixture()
    case = table(state, "ndt_nonconformance_cases")["normalizedRows"][0]
    case["commissionId"] = "CM1"
    groups = {"ndt_nonconformance_procedure": [sourced(status="conforming")],
              "ndt_nonconformance_commissions": [sourced(commissionId="CM1", objectIds=["W0"], status="conforming")],
              "ndt_nonconformance_notices": [{**deepcopy(case), "status": "conforming"}],
              "ndt_nonconformance_feedback": [{**deepcopy(case), "status": "conforming"}]}
    tables = state["ocr_parse_results"][0]["tables"]
    for schema, records in groups.items():
        tables.append({"tableId": schema, "businessSchema": schema, "normalizedRows": records,
                       "pageNo": len(tables) + 1, "bbox": [0, 0, 100, 100], "structureConfidence": 0.9})
    return state, run


def execute(state, run):
    run["documentScopeSnapshot"] = freeze_document_scope(run, state)
    facts = build_r37_business_facts(state, run)
    plan = compile_node_tool_plan(load_business_pack("engineering_inspection_v1"), "R37", available_tools={row["name"] for row in runtime_tool_catalog()})
    return execute_node_tool_plan(plan, facts=facts, document_version_ids=run["inputDocumentVersionIds"],
        evidence_facts=facts["judgment"]["claimedFacts"], evidence_refs=facts["judgment"]["evidenceRefs"],
        tool_runner=lambda name, args: dispatch_runtime_tool(state, name, args, context={"reviewRun": run}))


@pytest.mark.parametrize("case,expected", [("ok", "passed"), ("unqualified", "failed"), ("missing_notice", "evidence_insufficient"), ("missing_progression", "evidence_insufficient"), ("low_confidence", "evidence_insufficient"), ("contradictory_applicability", "evidence_insufficient"), ("not_applicable", "not_applicable")])
def test_real_r37_plan_preserves_roles_and_results(case, expected):
    state, run = fixture()
    if case == "unqualified":
        table(state, "ndt_reinspection_reports")["normalizedRows"][0]["status"] = "unqualified"
    elif case == "missing_notice":
        table(state, "ndt_nonconformance_notices")["normalizedRows"] = []
    elif case == "missing_progression":
        table(state, "ndt_progressive_reports")["normalizedRows"] = []
    elif case == "low_confidence":
        table(state, "ndt_defect_closure_links")["structureConfidence"] = 0.4
    elif case in ("contradictory_applicability", "not_applicable"):
        table(state, "ndt_nonconformance_context")["normalizedRows"][0]["required"] = False
        if case == "not_applicable":
            table(state, "ndt_nonconformance_inventory")["normalizedRows"][0]["caseCount"] = 0
            table(state, "ndt_progressive_inventory")["normalizedRows"][0]["eventCount"] = 0
            for schema in ("ndt_nonconformance_cases", "ndt_progressive_events", "ndt_progressive_reports", "ndt_defect_dispositions", "ndt_reinspection_reports", "ndt_defect_closure_links"):
                table(state, schema)["normalizedRows"] = []
    before = deepcopy(state)
    output = execute(state, run)
    assert output["result"] == expected, output
    assert len(output["atomicResults"]) == 3
    assert state == before


@pytest.mark.parametrize("schema", ["ndt_nonconformance_notices", "ndt_nonconformance_feedback", "ndt_defect_dispositions", "ndt_reinspection_reports"])
@pytest.mark.parametrize("event", ["OTHER", None, ""])
def test_same_case_and_round_cannot_use_other_or_missing_event_records(schema, event):
    state, run = fixture()
    record = table(state, schema)["normalizedRows"][0]
    if event is None:
        record.pop("eventId", None)
    else:
        record["eventId"] = event
    assert execute(state, run)["result"] == "evidence_insufficient"


@pytest.mark.parametrize("schema", ["ndt_nonconformance_notices", "ndt_nonconformance_feedback", "ndt_defect_dispositions", "ndt_reinspection_reports"])
def test_valid_witness_does_not_hide_extra_cross_event_record(schema):
    state, run = fixture()
    records = table(state, schema)["normalizedRows"]
    records.append({**deepcopy(records[0]), "eventId": "OTHER"})
    assert execute(state, run)["result"] == "evidence_insufficient"
