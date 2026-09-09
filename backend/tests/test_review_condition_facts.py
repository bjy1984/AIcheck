from copy import deepcopy

import pytest

from libs.review_condition_facts import condition_facts_from_run
from libs.review_document_scope import freeze_document_scope
from libs.rule_conditions import evaluate_conditions


def example():
    run = {"projectId": "P", "nodeId": 24, "businessPackId": "B", "inputDocumentVersionIds": ["D"]}
    field = {"id": "F", "fieldName": "thickness", "value": 0, "unit": "mm", "pageNo": 1, "bbox": [0, 0, 10, 10]}
    state = {"ocr_parse_results": [{"documentVersionId": "D", "fields": [field]}], "fact_corrections": []}
    run["documentScopeSnapshot"] = freeze_document_scope(run, state)
    conditions = {"schemaVersion": "rule-conditions-v1", "checks": [
        {"id": "C", "field": "thickness", "operator": "gte", "expected": 1, "unit": "mm"}]}
    return run, state, conditions


def test_server_ocr_preserves_zero_and_locator_and_does_not_mutate_source():
    run, state, conditions = example()
    before = deepcopy(state)
    facts, diagnostics = condition_facts_from_run(state, run, conditions)
    assert diagnostics == {}
    assert facts["thickness"]["value"] == 0
    assert facts["thickness"]["evidenceRefs"][0]["fieldId"] == "F"
    assert evaluate_conditions(conditions, facts)["result"] == "fail"
    facts["thickness"]["evidenceRefs"][0]["bbox"][0] = 5
    assert state == before


@pytest.mark.parametrize("change,reason", [("duplicate", "field_ambiguous_requires_object_mapping"),
                                          ("missing", "field_missing"), ("locator", "field_locator_missing_or_invalid")])
def test_missing_ambiguous_and_unlocatable_data_never_pass(change, reason):
    run, state, conditions = example()
    fields = state["ocr_parse_results"][0]["fields"]
    if change == "duplicate":
        fields.append(deepcopy(fields[0]))
    elif change == "missing":
        fields.clear()
    else:
        fields[0].pop("bbox")
    run["documentScopeSnapshot"] = freeze_document_scope(run, state)
    facts, diagnostics = condition_facts_from_run(state, run, conditions)
    assert diagnostics["thickness"] == reason
    assert evaluate_conditions(conditions, facts)["result"] == "evidence_insufficient"


def test_selected_active_correction_used_and_later_change_blocked():
    run, state, conditions = example()
    state["fact_corrections"] = [{"id": "FIX", "fieldId": "F", "fieldName": "thickness", "projectId": "P",
                                  "nodeId": 24, "documentVersionId": "D", "status": "active", "correctedValue": 2}]
    run["documentScopeSnapshot"] = freeze_document_scope(run, state)
    facts, _ = condition_facts_from_run(state, run, conditions)
    assert evaluate_conditions(conditions, facts)["result"] == "pass"
    assert facts["thickness"]["evidenceRefs"][0]["correctionId"] == "FIX"
    state["fact_corrections"][0]["correctedValue"] = 3
    with pytest.raises(ValueError, match="sources_changed"):
        condition_facts_from_run(state, run, conditions)


def test_other_document_is_ignored_and_old_run_cannot_claim_frozen_sources():
    run, state, conditions = example()
    state["ocr_parse_results"].append({"documentVersionId": "FOREIGN", "fields": [
        {"fieldName": "thickness", "value": 100, "unit": "mm", "pageNo": 1, "bbox": [0, 0, 10, 10]}]})
    facts, diagnostics = condition_facts_from_run(state, run, conditions)
    assert diagnostics == {} and facts["thickness"]["value"] == 0
    run["documentScopeSnapshot"] = freeze_document_scope(run)
    with pytest.raises(ValueError, match="requires_frozen_document_scope"):
        condition_facts_from_run(state, run, conditions)


def mapped_example():
    from libs.review_condition_facts import condition_candidates_from_run
    run, state, conditions = example()
    second = deepcopy(state["ocr_parse_results"][0]["fields"][0])
    second.update(id="SECOND", value=5, objectType="weld", objectId="W2")
    state["ocr_parse_results"][0]["fields"].append(second)
    run["documentScopeSnapshot"] = freeze_document_scope(run, state)
    candidates = condition_candidates_from_run(state, run, conditions)
    mapping = {"subject": {"objectType": "weld", "objectId": "W2"}, "confirmedSameObject": True,
               "fields": {"thickness": candidates["thickness"][1]["candidateId"]}}
    return run, state, conditions, mapping


def test_explicit_object_mapping_uses_exact_source_and_preserves_ambiguity_without_selection():
    run, state, conditions, mapping = mapped_example()
    facts, diagnostics = condition_facts_from_run(state, run, conditions, object_mapping=mapping)
    assert diagnostics == {} and facts["thickness"]["value"] == 5
    assert facts["thickness"]["evidenceRefs"][0]["fieldId"] == "SECOND"
    assert evaluate_conditions(conditions, facts)["result"] == "pass"
    assert condition_facts_from_run(state, run, conditions)[0] == {}
    mapping["fields"] = {}
    facts, diagnostics = condition_facts_from_run(state, run, conditions, object_mapping=mapping)
    assert facts == {} and diagnostics["thickness"] == "field_object_mapping_required"


@pytest.mark.parametrize("change,reason", [("foreign", "candidate_missing"), ("subject", "subject_mismatch"),
                                           ("unconfirmed", "confirmation_required"), ("unknown_field", "fields_invalid")])
def test_object_mapping_never_accepts_forged_or_unconfirmed_selection(change, reason):
    run, state, conditions, mapping = mapped_example()
    if change == "foreign":
        mapping["fields"]["thickness"] = "OTHER"
    elif change == "subject":
        mapping["subject"]["objectId"] = "W1"
    elif change == "unconfirmed":
        mapping["confirmedSameObject"] = False
    else:
        mapping["fields"]["other"] = "anything"
    with pytest.raises(ValueError, match=reason):
        condition_facts_from_run(state, run, conditions, object_mapping=mapping)


def test_object_mapping_rejects_changed_sources_and_duplicate_candidates():
    run, state, conditions, mapping = mapped_example()
    state["ocr_parse_results"][0]["fields"].append(deepcopy(state["ocr_parse_results"][0]["fields"][1]))
    with pytest.raises(ValueError, match="sources_changed"):
        condition_facts_from_run(state, run, conditions, object_mapping=mapping)
    run["documentScopeSnapshot"] = freeze_document_scope(run, state)
    with pytest.raises(ValueError, match="candidate_missing_or_ambiguous"):
        condition_facts_from_run(state, run, conditions, object_mapping=mapping)
