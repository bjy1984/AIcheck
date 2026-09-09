from __future__ import annotations

import pytest

from libs.review_rule_snapshot import effective_rule_snapshot, freeze_effective_rule


def test_rule_and_returned_values_are_copied():
    run = {"projectId": "P1", "nodeId": 24, "businessPackId": "pack"}
    rule = {"id": "R24", "criteria": "original", "aiExecution": {"limit": 3}}
    run["effectiveRuleSnapshot"] = freeze_effective_rule(run, rule)
    rule["aiExecution"]["limit"] = 9
    first = effective_rule_snapshot(run)
    assert first["aiExecution"]["limit"] == 3
    first["criteria"] = "changed"
    assert effective_rule_snapshot(run)["criteria"] == "original"
    run["effectiveRuleSnapshot"]["rule"]["criteria"] = "tampered"
    with pytest.raises(ValueError, match="hash_mismatch"):
        effective_rule_snapshot(run)


@pytest.mark.parametrize("key,value", [("projectId", "P2"), ("nodeId", 25), ("businessPackId", "other")])
def test_frozen_rule_cannot_be_reused_outside_run_scope(key, value):
    run = {"projectId": "P1", "nodeId": 24, "businessPackId": "pack"}
    run["effectiveRuleSnapshot"] = freeze_effective_rule(run, {"id": "R24"})
    run[key] = value
    with pytest.raises(ValueError, match="scope_mismatch"):
        effective_rule_snapshot(run)


def test_legacy_is_not_backfilled_and_missing_rule_cannot_be_frozen():
    assert effective_rule_snapshot({}) is None
    with pytest.raises(ValueError, match="effective_rule_missing"):
        freeze_effective_rule({}, {})
