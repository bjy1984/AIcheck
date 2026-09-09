from copy import deepcopy

import pytest

from libs.business_pack import load_business_pack
from libs.review_document_scope import freeze_document_scope
from libs.review_rule_snapshot import freeze_effective_rule
from libs.review_tools.condition_execution import (
    execute_with_condition_replacements,
    prepare_condition_results,
)
from libs.review_tools.executor import execute_node_tool_plan


def example(value):
    pack = deepcopy(load_business_pack("engineering_inspection_v1"))
    run = {"projectId": "P", "nodeId": 24, "businessPackId": pack["id"], "inputDocumentVersionIds": ["D"]}
    rule = {"id": "RULE", "nodeIds": [24], "businessPackId": pack["id"], "executionConditions": {
        "schemaVersion": "rule-conditions-v1", "checks": [
            {"id": "C", "atomicCheckId": "AC-R24-01", "field": "thickness", "operator": "gte", "expected": 10}]}}
    state = {"ocr_parse_results": [{"documentVersionId": "D", "fields": [
        {"id": "F", "name": "thickness", "value": value, "pageNo": 1, "bbox": [0, 0, 10, 10]},
        {"id": "A", "name": "required", "value": False, "pageNo": 1, "bbox": [0, 0, 10, 10]}]}]}
    run["documentScopeSnapshot"] = freeze_document_scope(run, state)
    run["effectiveRuleSnapshot"] = freeze_effective_rule(run, rule)
    plan = [{"atomicCheckId": identity, "compilable": True, "tools": [tool], "parameters": {}}
            for identity, tool in [("AC-R24-01", "old_threshold")] + [(f"AC-R24-0{i}", f"retained_{i}") for i in range(2, 6)]]
    return pack, run, rule, state, plan


@pytest.mark.parametrize("value,not_applicable,expected", [(11, False, "passed"), (9, False, "failed"),
                                                          (None, False, "evidence_insufficient"), (9, True, "not_applicable")])
def test_four_states_replace_old_tool_and_preserve_other_atomic_checks(value, not_applicable, expected):
    pack, run, rule, state, plan = example(value)
    if not_applicable:
        rule["executionConditions"]["applicability"] = {"id": "A", "field": "required", "operator": "eq", "expected": True}
        run["effectiveRuleSnapshot"] = freeze_effective_rule(run, rule)
    replacements = prepare_condition_results(state, run, pack)
    calls = []

    def runner(name, arguments):
        calls.append(name)
        return {"toolName": name, "status": "succeeded", "result": "passed"}

    result = execute_with_condition_replacements(plan, condition_results=replacements,
                                                base_executor=execute_node_tool_plan, tool_runner=runner)
    assert calls == [f"retained_{i}" for i in range(2, 6)]
    assert [item["atomicCheckId"] for item in result["atomicResults"]] == [f"AC-R24-0{i}" for i in range(1, 6)]
    assert result["atomicResults"][0]["result"] == expected
    assert result["summary"]["atomicCheckCount"] == 5
    output = result["atomicResults"][0]["toolResults"][0]
    assert output["ruleSnapshotHash"] == run["effectiveRuleSnapshot"]["snapshotHash"]
    if expected != "evidence_insufficient":
        assert output["evidenceRefs"][0]["documentVersionId"] == "D"


def test_later_rule_edit_does_not_change_frozen_threshold_and_data_change_blocks():
    pack, run, rule, state, _ = example(11)
    rule["executionConditions"]["checks"][0]["expected"] = 20
    assert prepare_condition_results(state, run, pack)["AC-R24-01"]["result"] == "passed"
    state["ocr_parse_results"][0]["fields"][0]["value"] = 21
    with pytest.raises(ValueError, match="sources_changed"):
        prepare_condition_results(state, run, pack)


def test_unknown_replacement_rejected_before_any_legacy_tool_runs():
    _, _, _, _, plan = example(11)
    with pytest.raises(ValueError, match="plan_mismatch"):
        execute_with_condition_replacements(plan, condition_results={"FOREIGN": {}},
                                            base_executor=lambda *a, **k: pytest.fail("must not execute"))


def test_unchanged_legacy_execution_contract():
    _, _, _, _, plan = example(11)
    sentinel = {"legacy": True}
    assert execute_with_condition_replacements(plan, condition_results={}, base_executor=lambda *a, **k: sentinel) is sentinel


def test_partial_base_plan_is_rejected_before_tools_execute():
    pack, run, _, state, plan = example(11)
    replacements = prepare_condition_results(state, run, pack)
    with pytest.raises(ValueError, match="coverage_mismatch"):
        execute_with_condition_replacements(plan[:-1], condition_results=replacements,
                                            base_executor=lambda *a, **k: pytest.fail("must not execute"))


def test_rule_engine_step_uses_frozen_replacement_with_project_rule_id(monkeypatch):
    from types import SimpleNamespace

    from libs.review_orchestrator import execution as ex

    pack, run, _, state, _ = example(11)
    run["reviewRunId"] = "RR-CONDITIONS"
    state["rule_check_results"] = []
    monkeypatch.setattr(ex, "repo", SimpleNamespace(state=state, clone=deepcopy))
    monkeypatch.setattr(ex, "execute_agent_tool", lambda *a, **k: {"status": "succeeded", "result": "passed", "verificationCount": 0})
    monkeypatch.setattr(ex, "append_tool_call", lambda *a, **k: None)
    context = {"project": {"businessPackSnapshot": pack}, "clausePackageSnapshot": {"clauses": [{"clauseReferenceId": "TEST-CLAUSE"}]}}
    ex.run_step(run, "run_rule_engine", context)
    results = state["rule_check_results"][0]["atomicCheckResults"]
    assert len(results) == 5
    replacement = next(row for row in results if row["atomicCheckId"] == "AC-R24-01")
    assert replacement["toolResults"][0]["toolName"] == "evaluate_saved_conditions"
    assert replacement["result"] == "passed"
    assert context["currentRule"]["id"] == "RULE"


def test_condition_capture_archives_exact_input_result_and_links_events():
    import json

    from libs.raw_vault import InMemoryRawVaultStore, RawCapture, verify_event_chain

    pack, run, _, state, _ = example(11)
    run.update(reviewRunId="RR-CAPTURE", tenantId="TENANT-LAB")
    store = InMemoryRawVaultStore()
    results = prepare_condition_results(state, run, pack, raw_capture=RawCapture(store=store))
    output = results["AC-R24-01"]["toolResults"][0]
    events = store.events_for_run("TENANT-LAB", "RR-CAPTURE")
    assert [event.event_type for event in events] == ["tool.call.requested", "tool.call.completed"]
    request = json.loads(store.payload_for(events[0].id))
    response = json.loads(store.payload_for(events[1].id))
    assert request["conditions"]["checks"][0]["expected"] == 10
    assert request["facts"]["thickness"]["value"] == 11
    assert response["result"] == "passed"
    assert response["conditionResults"]["checks"][0]["evidenceRefs"]
    assert events[0].provider_tool_call_id == events[1].provider_tool_call_id == output["toolCallId"]
    assert output["rawCapture"]["requestEventId"] == events[0].id
    assert verify_event_chain(events, store.payload_for).status == "verified"


@pytest.mark.parametrize("fail_on", [1, 2])
def test_capture_failure_does_not_return_successful_condition_result(fail_on):
    from libs.integrations.errors import IntegrationServiceError
    from libs.raw_vault import InMemoryRawVaultStore, RawCapture

    class FailingStore(InMemoryRawVaultStore):
        calls = 0

        def append(self, *args, **kwargs):
            self.calls += 1
            if self.calls == fail_on:
                raise OSError("storage unavailable")
            return super().append(*args, **kwargs)

    pack, run, _, state, _ = example(11)
    run["reviewRunId"] = "RR-CAPTURE-FAIL"
    reports = []
    with pytest.raises(IntegrationServiceError) as error:
        prepare_condition_results(state, run, pack, raw_capture=RawCapture(store=FailingStore(), failure_reporter=reports.append))
    assert error.value.reason == "CONDITION_TOOL_CAPTURE_FAILED"
    assert reports[0]["eventType"] == ("tool.call.requested" if fail_on == 1 else "tool.call.completed")


def test_condition_exception_is_archived_and_propagated(monkeypatch):
    from libs.raw_vault import InMemoryRawVaultStore, RawCapture
    from libs.review_tools import condition_execution

    pack, run, _, state, _ = example(11)
    run.update(reviewRunId="RR-ERROR", tenantId="TENANT-LAB")
    store = InMemoryRawVaultStore()

    def fail(*args):
        raise ValueError("evaluation failed")

    monkeypatch.setattr(condition_execution, "evaluate_conditions", fail)
    with pytest.raises(ValueError, match="evaluation failed"):
        prepare_condition_results(state, run, pack, raw_capture=RawCapture(store=store))
    assert [event.event_type for event in store.events_for_run("TENANT-LAB", "RR-ERROR")] == ["tool.call.requested", "tool.call.failed"]


def semantic_example(value):
    pack, run, rule, state, _ = example(value)
    run.update(nodeId=19, reviewRunId="RR-SEMANTIC")
    rule["nodeIds"] = [19]
    rule["executionConditions"]["checks"][0]["atomicCheckId"] = "AC-R19-01"
    run["documentScopeSnapshot"] = freeze_document_scope(run, state)
    run["effectiveRuleSnapshot"] = freeze_effective_rule(run, rule)
    rows = [{"atomicCheckId": f"AC-R19-0{i}", "result": "failed" if i == 1 else "passed",
             "evidenceRefIds": [f"E-{i}"], "explanation": f"original-{i}"} for i in range(1, 9)]
    return pack, run, rule, state, rows


@pytest.mark.parametrize("value,applicability,target_result,node_result", [
    (11, False, "passed", "passed"), (9, False, "failed", "failed"),
    (None, False, "evidence_insufficient", "evidence_insufficient"), (9, True, "not_applicable", "passed")])
def test_semantic_rule_engine_replaces_target_and_reaggregates_without_rewriting_history(monkeypatch, value, applicability, target_result, node_result):
    from types import SimpleNamespace

    from libs.review_orchestrator import execution as ex

    pack, run, rule, state, rows = semantic_example(value)
    if applicability:
        rule["executionConditions"]["applicability"] = {"id": "A", "field": "required", "operator": "eq", "expected": True}
        run["effectiveRuleSnapshot"] = freeze_effective_rule(run, rule)
    run["r19SemanticReview"] = {"result": "failed", "atomicJudgments": rows}
    original = deepcopy(run["r19SemanticReview"])
    state["rule_check_results"] = []
    monkeypatch.setattr(ex, "repo", SimpleNamespace(state=state, clone=deepcopy))
    monkeypatch.setattr(ex, "execute_agent_tool", lambda *a, **k: pytest.fail("semantic merge must not rerun base tools"))
    monkeypatch.setattr(ex, "append_tool_call", lambda *a, **k: None)
    context = {"project": {"businessPackSnapshot": pack}, "clausePackageSnapshot": {"clauses": [{"clauseReferenceId": "TEST"}]}}
    ex.run_step(run, "run_rule_engine", context)
    result = state["rule_check_results"][0]
    assert result["result"] == node_result
    assert len(result["atomicCheckResults"]) == 8
    assert result["atomicCheckResults"][0]["result"] == target_result
    assert result["atomicCheckResults"][1]["evidenceRefIds"] == ["E-2"]
    assert result["toolExecutionSummary"]["executionMode"] == "semantic_with_condition_replacements"
    assert run["r19SemanticReview"] == original


@pytest.mark.parametrize("corruption", ["missing", "duplicate", "foreign"])
def test_incomplete_semantics_cannot_appear_complete(corruption):
    from libs.review_tools.condition_execution import merge_semantic_condition_results

    pack, run, _, state, rows = semantic_example(11)
    replacements = prepare_condition_results(state, run, pack)
    if corruption == "missing":
        rows.pop()
    elif corruption == "duplicate":
        rows.append(deepcopy(rows[-1]))
    else:
        rows[-1]["atomicCheckId"] = "FOREIGN"
    with pytest.raises(ValueError, match="retained_results_incomplete"):
        merge_semantic_condition_results({"result": "passed", "atomicResults": rows}, replacements)
