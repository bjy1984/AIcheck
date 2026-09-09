from copy import deepcopy

import pytest

from libs.rule_conditions import evaluate_conditions, validate_conditions


def conditions(limit=10):
    return {"schemaVersion": "rule-conditions-v1", "checks": [
        {"id": "thickness", "field": "thickness", "operator": "gte", "expected": limit, "unit": "mm"}
    ]}


@pytest.mark.parametrize("fact,result,reason", [
    ({"value": 10, "unit": "mm", "evidenceRefs": ["E1"]}, "pass", "condition_evaluated"),
    ({"value": 9.9, "unit": "mm", "evidenceRefs": ["E1"]}, "fail", "condition_evaluated"),
    ({"value": 10, "unit": "cm", "evidenceRefs": ["E1"]}, "evidence_insufficient", "unit_mismatch"),
    ({"value": 10, "unit": "mm"}, "evidence_insufficient", "evidence_reference_missing"),
    ({"value": "10", "unit": "mm", "evidenceRefs": ["E1"]}, "evidence_insufficient", "fact_type_mismatch"),
    ({"value": True, "unit": "mm", "evidenceRefs": ["E1"]}, "evidence_insufficient", "fact_type_mismatch"),
    ({}, "evidence_insufficient", "fact_missing"),
])
def test_condition_does_not_guess_missing_or_incompatible_facts(fact, result, reason):
    output = evaluate_conditions(conditions(), {"thickness": fact})
    assert output["result"] == result
    assert output["checks"][0]["reason"] == reason


def test_editing_threshold_changes_execution_without_changing_input():
    facts = {"thickness": {"value": 10, "unit": "mm", "evidenceRefs": ["E1"]}}
    before = deepcopy(facts)
    assert evaluate_conditions(conditions(10), facts)["result"] == "pass"
    assert evaluate_conditions(conditions(11), facts)["result"] == "fail"
    assert facts == before


@pytest.mark.parametrize("change", [{"operator": "eval"}, {"expected": float("nan")}, {"expected": True}, {"unit": ""}, {"code": "exec()"}])
def test_invalid_conditions_cannot_execute(change):
    value = conditions()
    value["checks"][0].update(change)
    with pytest.raises(ValueError):
        validate_conditions(value)
