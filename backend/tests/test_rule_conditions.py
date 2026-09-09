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


@pytest.mark.parametrize("applicable,thickness,result", [
    (True, 11, "pass"), (True, 9, "fail"), (True, None, "evidence_insufficient"),
    (False, None, "not_applicable"), (False, 1, "not_applicable"), (None, 11, "evidence_insufficient"),
])
def test_applicability_precedes_checks_without_guessing(applicable, thickness, result):
    specification = conditions()
    specification["applicability"] = {"id": "required", "field": "required", "operator": "eq", "expected": True}
    facts = {
        "required": {"value": applicable, "evidenceRefs": ["DESIGN-1"]},
        "thickness": {"value": thickness, "unit": "mm", "evidenceRefs": ["MEASURE-1"]},
    }
    output = evaluate_conditions(specification, facts)
    assert output["result"] == result
    assert len(output["checks"]) == 1
    if applicable is False:
        assert output["checks"][0]["evidenceRefs"] == ["DESIGN-1"]
        assert output["checks"][0]["reason"] == "applicability_not_met"
    if applicable is None:
        assert output["reason"] == "applicability_unknown"


def test_applicability_without_evidence_is_not_a_skip():
    specification = conditions()
    specification["applicability"] = {"id": "required", "field": "required", "operator": "eq", "expected": True}
    output = evaluate_conditions(specification, {"required": {"value": False}})
    assert output["result"] == "evidence_insufficient"
    assert output["applicability"]["reason"] == "evidence_reference_missing"
    specification["checks"][0]["operator"] = "UNSUPPORTED"
    with pytest.raises(ValueError, match="unsupported"):
        evaluate_conditions(specification, {"required": {"value": False, "evidenceRefs": ["E1"]}})


def leaf(identity):
    return {"id": identity, "field": identity, "operator": "eq", "expected": True}


@pytest.mark.parametrize("group,left,right,expected", [
    ("all", True, True, "pass"), ("all", True, None, "evidence_insufficient"),
    ("all", False, None, "not_applicable"), ("all", None, None, "evidence_insufficient"),
    ("any", True, None, "pass"), ("any", False, None, "evidence_insufficient"),
    ("any", False, False, "not_applicable"), ("any", None, None, "evidence_insufficient"),
])
def test_compound_applicability_preserves_unknown(group, left, right, expected):
    specification = conditions()
    specification["applicability"] = {group: [leaf("A"), leaf("B")]}
    facts = {"A": {"value": left, "evidenceRefs": ["EA"]}, "B": {"value": right, "evidenceRefs": ["EB"]},
             "thickness": {"value": 11, "unit": "mm", "evidenceRefs": ["EM"]}}
    output = evaluate_conditions(specification, facts)
    assert output["result"] == expected
    assert len(output["applicability"]["children"]) == 2


@pytest.mark.parametrize("value,expected", [(True, "not_applicable"), (False, "pass"), (None, "evidence_insufficient")])
def test_negating_unknown_does_not_make_it_true(value, expected):
    specification = conditions()
    specification["applicability"] = {"not": leaf("A")}
    output = evaluate_conditions(specification, {"A": {"value": value, "evidenceRefs": ["EA"]},
        "thickness": {"value": 11, "unit": "mm", "evidenceRefs": ["EM"]}})
    assert output["result"] == expected


@pytest.mark.parametrize("expression", [{"all": []}, {"any": [], "not": leaf("A")},
    {"not": None}, {"all": [leaf("A"), leaf("A")]}, {"any": [leaf(str(i)) for i in range(201)]}])
def test_malformed_or_oversized_applicability_rejected(expression):
    specification = conditions()
    specification["applicability"] = expression
    with pytest.raises(ValueError):
        validate_conditions(specification)


def test_nested_applicability_and_depth_limit():
    specification = conditions()
    specification["applicability"] = {"all": [leaf("A"), {"not": {"any": [leaf("B"), leaf("C")]}}]}
    facts = {key: {"value": value, "evidenceRefs": [key]} for key, value in [("A", True), ("B", False), ("C", False)]}
    facts["thickness"] = {"value": 11, "unit": "mm", "evidenceRefs": ["M"]}
    assert evaluate_conditions(specification, facts)["result"] == "pass"
    expression = leaf("A")
    for _ in range(10):
        expression = {"not": expression}
    specification["applicability"] = expression
    with pytest.raises(ValueError, match="invalid_applicability"):
        evaluate_conditions(specification, facts)
