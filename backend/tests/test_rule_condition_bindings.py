from copy import deepcopy

import pytest

from libs.business_pack import load_business_pack
from libs.rule_condition_bindings import compile_condition_bindings


def example():
    pack = deepcopy(load_business_pack("engineering_inspection_v1"))
    rule = {"id": "RULE-LAB", "revision": 1, "nodeIds": [24], "businessPackId": pack["id"],
            "executionConditions": {"schemaVersion": "rule-conditions-v1", "checks": [
                {"id": "C1", "atomicCheckId": "AC-R24-01", "field": "thickness", "operator": "gte", "expected": 10},
                {"id": "C2", "atomicCheckId": "AC-R24-01", "field": "thickness", "operator": "lte", "expected": 20}]}}
    return rule, pack


def test_replacements_group_conditions_and_preserve_every_other_atomic_item():
    rule, pack = example()
    plan = compile_condition_bindings(rule, pack)
    assert len(plan["replacements"]) == 1
    assert len(plan["replacements"][0]["conditions"]["checks"]) == 2
    assert plan["retainedAtomicCheckIds"] == ["AC-R24-02", "AC-R24-03", "AC-R24-04", "AC-R24-05"]
    assert plan["formalExecutable"] is False
    plan["replacements"][0]["conditions"]["checks"][0]["expected"] = 99
    assert rule["executionConditions"]["checks"][0]["expected"] == 10


@pytest.mark.parametrize("target", [None, "AC-R25-01", "UNKNOWN", 24])
def test_invalid_or_cross_node_mapping_is_rejected(target):
    rule, pack = example()
    if target is None:
        rule["executionConditions"]["checks"][0].pop("atomicCheckId")
    else:
        rule["executionConditions"]["checks"][0]["atomicCheckId"] = target
    with pytest.raises(ValueError):
        compile_condition_bindings(rule, pack)


@pytest.mark.parametrize("change", ["pack", "nodes", "missing_binding", "duplicate_binding"])
def test_inconsistent_base_catalog_is_rejected(change):
    rule, pack = example()
    if change == "pack":
        rule["businessPackId"] = "other"
    elif change == "nodes":
        rule["nodeIds"] = [24, 25]
    elif change == "missing_binding":
        pack["atomicCheckToolBindings"] = [b for b in pack["atomicCheckToolBindings"] if b["atomicCheckId"] != "AC-R24-02"]
    else:
        pack["atomicCheckToolBindings"].append(deepcopy(next(b for b in pack["atomicCheckToolBindings"] if b["atomicCheckId"] == "AC-R24-01")))
    with pytest.raises(ValueError):
        compile_condition_bindings(rule, pack)


def test_condition_and_binding_changes_change_plan_identity():
    rule, pack = example()
    first = compile_condition_bindings(rule, pack)
    rule["executionConditions"]["checks"][0]["expected"] = 11
    second = compile_condition_bindings(rule, pack)
    assert first["conditionsHash"] != second["conditionsHash"] and first["planHash"] != second["planHash"]
    next(b for b in pack["atomicCheckToolBindings"] if b["atomicCheckId"] == "AC-R24-02")["parameters"] = {"changed": True}
    third = compile_condition_bindings(rule, pack)
    assert second["baseBindingsHash"] != third["baseBindingsHash"] and second["planHash"] != third["planHash"]
