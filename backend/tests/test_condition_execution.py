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
