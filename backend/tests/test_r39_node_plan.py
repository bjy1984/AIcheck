from copy import deepcopy

import pytest
from test_r39_content_facts import fixture
from test_r39_source_validation import source_table

from libs.business_pack import load_business_pack
from libs.review_document_scope import freeze_document_scope
from libs.review_orchestrator.ndt_fact_builders import NDT_FACT_BUILDERS
from libs.review_orchestrator.runtime_tools import dispatch_runtime_tool, runtime_tool_catalog
from libs.review_tools import compile_node_tool_plan, execute_node_tool_plan
from libs.review_tools.executor import aggregate_planned_tool_results
from scripts import publish_atomic_check_bindings as publisher


def execute(state, run):
    run["documentScopeSnapshot"] = freeze_document_scope(run, state)
    facts = NDT_FACT_BUILDERS[39](state, run)
    plan = compile_node_tool_plan(load_business_pack("engineering_inspection_v1"), "R39", available_tools={row["name"] for row in runtime_tool_catalog()})
    return execute_node_tool_plan(plan, facts=facts, document_version_ids=run["inputDocumentVersionIds"],
        evidence_facts=facts["judgment"]["claimedFacts"], evidence_refs=facts["judgment"]["evidenceRefs"],
        tool_runner=lambda name, args: dispatch_runtime_tool(state, name, args, context={"reviewRun": run}))


def test_actual_binding_runs_all_subtools_but_does_not_claim_complete_coverage():
    state, run = fixture()
    before = deepcopy(state)
    output = execute(state, run)
    assert state == before
    assert output["result"] == "evidence_insufficient"
    assert len(output["atomicResults"]) == 2
    decision, gate = output["atomicResults"]
    names = {row["toolName"]: row for row in decision["toolResults"]}
    for name in ("evaluate_r39_document_content", "evaluate_r39_approval_chain", "evaluate_r39_first_use_validation"):
        assert names[name]["result"] == "passed"
        assert names[name]["facts"]["wholeRuleAcceptance"] == "not_evaluated"
    assert "evaluate_ndt_process" not in names
    assert decision["warnings"] == ["pending_capability:procedure_reference_consistency", "pending_capability:method_specific_technical_requirements", "pending_capability:complete_document_and_application_inventory"]
    assert gate["resultRole"] == "evidence_gate" and gate["result"] == "passed"


@pytest.mark.parametrize("case,expected", [("known_absence", "failed"), ("unapproved", "failed"), ("not_validated", "failed"),
    ("unreliable_failure", "evidence_insufficient"), ("missing", "evidence_insufficient"), ("non_first_use", "evidence_insufficient")])
def test_actual_plan_preserves_findings_and_evidence_gate(case, expected):
    state, run = fixture()
    if case in {"known_absence", "unreliable_failure"}:
        source_table(state, "ndt_content_fields")["normalizedRows"][0].update(presence="absent", value=None)
        if case == "unreliable_failure":
            source_table(state, "ndt_content_fields")["structureConfidence"] = .4
    elif case == "unapproved":
        source_table(state, "ndt_approval_signatures")["normalizedRows"][-1]["approved"] = False
    elif case == "not_validated":
        source_table(state, "ndt_first_use_validation")["normalizedRows"][0]["performed"] = False
    elif case == "missing":
        source_table(state, "ndt_content_fields")["normalizedRows"] = []
    else:
        source_table(state, "ndt_instruction_application")["normalizedRows"][0]["firstUse"] = False
    assert execute(state, run)["result"] == expected


@pytest.mark.parametrize("status", ["passed", "not_applicable", "failed", "execution_error", "evidence_insufficient", "human_review_required"])
def test_pending_capabilities_only_prevent_unsupported_positive_completion(status):
    item = {"tools": ["test"], "parameters": {"pendingCapabilities": ["remaining_work"]}}
    expected = "evidence_insufficient" if status in {"passed", "not_applicable"} else status
    output = {"toolName": "test", "result": status, "status": "error" if status == "execution_error" else "succeeded"}
    assert aggregate_planned_tool_results(item, [output]) == expected


@pytest.mark.parametrize("pending", [None, [], "remaining_work", [""], [True]])
def test_invalid_coverage_declaration_cannot_pass(pending):
    item = {"tools": ["test"], "parameters": {"pendingCapabilities": pending}}
    assert aggregate_planned_tool_results(item, [{"toolName": "test", "result": "passed"}]) == "evidence_insufficient"


def test_pending_capabilities_cannot_be_overridden_by_tool_arguments():
    pack = load_business_pack("engineering_inspection_v1")
    plan = compile_node_tool_plan(pack, "R39", available_tools={row["name"] for row in runtime_tool_catalog()})
    with pytest.raises(ValueError, match="fixed_rule_parameter_override"):
        execute_node_tool_plan(plan, tool_runner=lambda *_: pytest.fail("must reject before calling tools"),
                               tool_arguments={"evaluate_r39_document_content": {"pendingCapabilities": []}})
    with pytest.raises(ValueError, match="Formal review requires"):
        compile_node_tool_plan(pack, "R39", available_tools=set(), require_published=True)


@pytest.mark.parametrize("pending", [["remaining_work"], [], None])
def test_publisher_rejects_pending_declaration_even_if_marked_implemented(monkeypatch, pending):
    pack = {"atomicCheckToolBindingSet": {"atomicCheckCount": 1}, "atomicCheckToolBindings": [
        {"atomicCheckId": "AC-R39-01", "implementationStatus": "implemented", "tools": [], "parameters": {"pendingCapabilities": pending}}]}
    monkeypatch.setattr(publisher, "load_business_pack", lambda _: pack)
    monkeypatch.setattr(publisher, "validate_business_pack", lambda _: {"ok": True})
    with pytest.raises(RuntimeError, match="pending capabilities.*AC-R39-01"):
        publisher.validate_release("test")
