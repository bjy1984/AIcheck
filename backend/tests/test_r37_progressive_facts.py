from copy import deepcopy

import pytest
from test_r37_facts import fixture as witness_fixture
from test_r37_progressive import arguments, sourced

from libs.review_document_scope import freeze_document_scope
from libs.review_orchestrator.r37_facts import build_r37_business_facts
from libs.review_orchestrator.runtime_tools import dispatch_runtime_tool
from libs.review_tools.executor import build_tool_arguments


def fixture():
    state, run = witness_fixture()
    data = arguments()
    groups = {"ndt_progressive_inventory": [sourced(inventoryId="PG1", complete=True, eventCount=1)],
              "ndt_progressive_events": [{**data["event"], "inventoryId": "PG1"}],
              "ndt_inspection_batches": [data["batch"]], "ndt_inspection_batch_members": data["batch"]["members"],
              "ndt_progressive_reports": [{**row, "inventoryId": "PG1", "stage": "first"} for row in data["firstReports"]]}
    tables = state["ocr_parse_results"][0]["tables"]
    for schema, rows in groups.items():
        tables.append({"tableId": schema, "businessSchema": schema, "pageNo": len(tables) + 1, "bbox": [0, 0, 100, 100], "structureConfidence": 0.9, "normalizedRows": deepcopy(rows)})
    return state, run


def source(state, schema):
    return next(row for row in state["ocr_parse_results"][0]["tables"] if row["businessSchema"] == schema)


def execute(state, run):
    run["documentScopeSnapshot"] = freeze_document_scope(run, state)
    facts = build_r37_business_facts(state, run)
    params = build_tool_arguments("evaluate_r37_progressive_inspection", {}, facts=facts, explicit={},
        document_version_ids=run["inputDocumentVersionIds"], evidence_facts=[], evidence_refs=[])
    return facts, dispatch_runtime_tool(state, "evaluate_r37_progressive_inspection", params, context={"reviewRun": run})


def test_independent_batch_and_event_records_reach_runtime_with_real_refs():
    state, run = fixture()
    reports = source(state, "ndt_progressive_reports")
    reports["normalizedRows"][0]["evidenceRefs"] = [{"documentVersionId": "OTHER", "pageNo": 99}]
    before = deepcopy(state)
    facts, output = execute(state, run)
    assert output["result"] == "passed", output
    assert len(output["facts"]["eventResults"]) == 1
    assert output["facts"]["batchAcceptance"] == "not_evaluated"
    assert output["facts"]["repairRequiredObjectIds"] == ["W0"]
    assert {row["documentVersionId"] for row in output["evidenceRefs"]} == {"V1"}
    assert facts["r37"]["progressiveReports"][0]["evidenceRefs"][0]["pageNo"] == 12
    assert state == before
    reports["normalizedRows"][0]["scope"] = "OTHER"
    with pytest.raises(ValueError, match="sources_changed"):
        build_r37_business_facts(state, run)


@pytest.mark.parametrize("case", ["unselected", "count", "ambiguous_inventory", "duplicate_event", "missing_members", "duplicate_batch", "old_inventory", "orphan_event", "wrong_stage", "foreign_member", "wrong_project"])
def test_incomplete_or_cross_event_sources_do_not_pass(case):
    state, run = fixture()
    if case == "unselected":
        run["inputDocumentVersionIds"] = []
    elif case == "count":
        source(state, "ndt_progressive_inventory")["normalizedRows"][0]["eventCount"] = 0
    elif case == "ambiguous_inventory":
        source(state, "ndt_progressive_inventory")["normalizedRows"] *= 2
    elif case == "duplicate_event":
        source(state, "ndt_progressive_events")["normalizedRows"] *= 2
        source(state, "ndt_progressive_inventory")["normalizedRows"][0]["eventCount"] = 2
    elif case == "missing_members":
        source(state, "ndt_inspection_batch_members")["normalizedRows"] = []
    elif case == "duplicate_batch":
        source(state, "ndt_inspection_batches")["normalizedRows"] *= 2
    elif case == "foreign_member":
        source(state, "ndt_inspection_batch_members")["normalizedRows"][0]["batchId"] = "OTHER"
    else:
        key, value = {"old_inventory": ("inventoryId", "OTHER"), "orphan_event": ("eventId", "OTHER"), "wrong_stage": ("stage", "unknown"), "wrong_project": ("projectId", "OTHER")}[case]
        source(state, "ndt_progressive_reports")["normalizedRows"][0][key] = value
    assert execute(state, run)[1]["result"] == "evidence_insufficient"


def test_second_event_cannot_borrow_first_events_reports():
    state, run = fixture()
    events = source(state, "ndt_progressive_events")["normalizedRows"]
    events.append({**events[0], "eventId": "E2"})
    source(state, "ndt_progressive_inventory")["normalizedRows"][0]["eventCount"] = 2
    output = execute(state, run)[1]
    assert output["result"] == "evidence_insufficient"
    assert [row["result"] for row in output["facts"]["eventResults"]] == ["passed", "evidence_insufficient"]


def test_complete_empty_inventory_and_evidence_gate():
    state, run = fixture()
    source(state, "ndt_progressive_reports")["structureConfidence"] = 0.4
    facts, _ = execute(state, run)
    params = build_tool_arguments("validate_evidence_grounding", {"parameters": {"minConfidence": 0.75}}, facts=facts, explicit={},
        document_version_ids=run["inputDocumentVersionIds"], evidence_facts=facts["judgment"]["claimedFacts"], evidence_refs=facts["judgment"]["evidenceRefs"])
    assert dispatch_runtime_tool(state, "validate_evidence_grounding", params, context={"reviewRun": run})["result"] == "evidence_insufficient"
    source(state, "ndt_progressive_inventory")["normalizedRows"][0]["eventCount"] = 0
    source(state, "ndt_progressive_events")["normalizedRows"] = []
    source(state, "ndt_progressive_reports")["normalizedRows"] = []
    assert execute(state, run)[1]["result"] == "not_applicable"
