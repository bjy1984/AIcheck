from libs.review_tools.executor import (
    aggregate_atomic_results,
    aggregate_planned_tool_results,
    is_evidence_gate_plan,
)


def test_support_success_preserves_dedicated_not_applicable_but_not_failed_grounding():
    item = {"tools": ["decision", "validate_evidence_grounding"], "parameters": {"decisionTool": "decision"}}
    output = [{"toolName": "decision", "result": "not_applicable", "status": "succeeded"},
              {"toolName": "validate_evidence_grounding", "result": "passed", "status": "succeeded"}]
    assert aggregate_planned_tool_results(item, output) == "not_applicable"
    output[1]["result"] = "evidence_insufficient"
    assert aggregate_planned_tool_results(item, output) == "evidence_insufficient"
    output[1].update(result="passed", status="error")
    assert aggregate_planned_tool_results(item, output) == "execution_error"


def test_ambiguous_decision_declaration_cannot_hide_other_business_tools():
    item = {"tools": ["decision", "other_decision"], "parameters": {"decisionTool": "decision"}}
    output = [{"toolName": "decision", "result": "not_applicable"}, {"toolName": "other_decision", "result": "passed"}]
    assert aggregate_planned_tool_results(item, output) == "evidence_insufficient"
    assert not is_evidence_gate_plan({**item, "parameters": {"resultRole": "evidence_gate"}})
    assert not is_evidence_gate_plan({"tools": [], "parameters": {"resultRole": "evidence_gate"}})


def test_evidence_only_checks_cannot_supply_a_business_decision():
    gate = {"resultRole": "evidence_gate", "result": "passed"}
    assert aggregate_atomic_results([gate]) == "evidence_insufficient"
    assert aggregate_atomic_results([{"result": "not_applicable"}, gate]) == "not_applicable"
    assert aggregate_atomic_results([{"result": "passed"}, gate]) == "passed"
    assert aggregate_atomic_results([{"result": "not_applicable"}, {**gate, "result": "evidence_insufficient"}]) == "evidence_insufficient"
    # Undeclared existing plans keep their prior behavior.
    assert aggregate_atomic_results([{"result": "not_applicable"}, {"result": "passed"}]) == "passed"
