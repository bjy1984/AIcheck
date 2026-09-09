from copy import deepcopy

import pytest
from test_condition_execution import example

from libs.review_condition_facts import condition_candidates_from_run
from libs.review_condition_mapping import (
    effective_condition_mapping,
    freeze_condition_mapping,
    initialize_condition_mapping,
)
from libs.review_document_scope import freeze_document_scope
from libs.review_rule_snapshot import freeze_effective_rule
from libs.review_tools.condition_execution import prepare_condition_results


def mapped(value=11):
    pack, run, rule, state, _ = example(value)
    rule["revision"] = 1
    run["tenantId"] = "T"
    run["inputHash"] = "BASE"
    extra = deepcopy(state["ocr_parse_results"][0]["fields"][0])
    extra.update(id="OTHER", value=5)
    state["ocr_parse_results"][0]["fields"].append(extra)
    run["documentScopeSnapshot"] = freeze_document_scope(run, state)
    run["effectiveRuleSnapshot"] = freeze_effective_rule(run, rule)
    candidates = condition_candidates_from_run(state, run, rule["executionConditions"])
    request = {"ruleVersionId": "RULE", "ruleRevision": 1,
               "sourceSnapshotHash": run["documentScopeSnapshot"]["snapshotHash"],
               "selection": {"subject": {"objectType": "weld", "objectId": "W1"}, "confirmedSameObject": True,
                             "fields": {"thickness": candidates["thickness"][0]["candidateId"]}}}
    return pack, run, rule, state, request


@pytest.mark.parametrize("value,result", [(11, "passed"), (5, "failed"), (None, "evidence_insufficient")])
def test_execution_uses_frozen_selection_instead_of_ambiguous_field_order(value, result):
    pack, run, _, state, request = mapped(value)
    run["conditionObjectMapping"] = request
    initialize_condition_mapping(run, state)
    assert "conditionObjectMapping" not in run and run["inputHash"] != "BASE"
    request["selection"]["subject"]["objectId"] = "EDITED"
    assert effective_condition_mapping(run, state)["subject"]["objectId"] == "W1"
    output = prepare_condition_results(state, run, pack)["AC-R24-01"]
    assert output["result"] == result
    assert output["toolResults"][0]["conditionObjectMappingSnapshotHash"] == run["conditionObjectMappingSnapshot"]["snapshotHash"]


@pytest.mark.parametrize("field,value", [("ruleRevision", 2), ("ruleRevision", True), ("sourceSnapshotHash", "OTHER"),
                                        ("ruleVersionId", "OTHER"), ("selection", None)])
def test_stale_or_invalid_trial_cannot_be_frozen(field, value):
    _, run, _, state, request = mapped()
    request[field] = value
    with pytest.raises(ValueError, match="condition_mapping"):
        freeze_condition_mapping(run, state, request)


def test_scope_and_snapshot_tampering_and_changed_source_are_rejected():
    _, run, _, state, request = mapped()
    run["conditionObjectMappingSnapshot"] = freeze_condition_mapping(run, state, request)
    before = deepcopy(run)
    run["conditionObjectMappingSnapshot"]["selection"]["subject"]["objectId"] = "OTHER"
    with pytest.raises(ValueError, match="snapshot_changed"):
        effective_condition_mapping(run, state)
    run = deepcopy(before)
    run["tenantId"] = "OTHER"
    with pytest.raises(ValueError, match="scope_changed"):
        effective_condition_mapping(run, state)
    state["ocr_parse_results"][0]["fields"][0]["value"] = 99
    with pytest.raises(ValueError, match="sources_changed"):
        effective_condition_mapping(before, state)


def test_different_object_selections_change_input_hash_and_legacy_is_untouched():
    _, run, _, state, request = mapped()
    original = deepcopy(run)
    initialize_condition_mapping(run, state)
    assert run == original and effective_condition_mapping(run, state) is None
    other = deepcopy(run)
    run["conditionObjectMapping"] = deepcopy(request)
    other["conditionObjectMapping"] = deepcopy(request)
    other["conditionObjectMapping"]["selection"]["subject"]["objectId"] = "W2"
    initialize_condition_mapping(run, state)
    initialize_condition_mapping(other, state)
    assert run["inputHash"] != other["inputHash"]


def test_mapped_applicability_can_return_not_applicable():
    pack, run, rule, state, request = mapped()
    rule["executionConditions"]["applicability"] = {"id": "A", "field": "required", "operator": "eq", "expected": True}
    run["effectiveRuleSnapshot"] = freeze_effective_rule(run, rule)
    candidates = condition_candidates_from_run(state, run, rule["executionConditions"])
    request["selection"]["fields"]["required"] = candidates["required"][0]["candidateId"]
    run["conditionObjectMapping"] = request
    initialize_condition_mapping(run, state)
    assert prepare_condition_results(state, run, pack)["AC-R24-01"]["result"] == "not_applicable"


def test_api_selection_validates_current_rule_and_exact_input_scope():
    from types import SimpleNamespace

    from apps.api.review_condition_selection import prepare_condition_selection

    pack, _, rule, state, request = mapped()
    services = SimpleNamespace(
        repo=SimpleNamespace(state=state, require_project=lambda _: {}, clone=deepcopy,
                             ensure_deferred_loaded=lambda *args: None),
        business_pack_for_project=lambda _: pack,
        current_published_rule_for_node=lambda *args, **kwargs: rule,
        request_tenant_id=lambda _: "T",
    )
    body = {"conditionObjectMapping": request}
    selected = prepare_condition_selection(services, None, "P", 24, body, ["D"], {})
    assert selected == request and selected is not request
    with pytest.raises(ValueError, match="sources_changed"):
        prepare_condition_selection(services, None, "P", 24, body, ["OTHER"], {})
    rule["revision"] = 2
    with pytest.raises(ValueError, match="rule_changed"):
        prepare_condition_selection(services, None, "P", 24, body, ["D"], {})
    rule.pop("executionConditions")
    with pytest.raises(ValueError, match="没有可执行条件"):
        prepare_condition_selection(services, None, "P", 24, body, ["D"], {})
