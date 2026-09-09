import json
from copy import deepcopy

import pytest

from libs.business_pack import load_business_pack
from libs.integrations.errors import IntegrationServiceError
from libs.review_document_scope import freeze_document_scope
from libs.review_orchestrator.checklist_mode import (
    build_checklist_items,
    normalize_checklist_output,
)
from libs.review_rule_snapshot import freeze_effective_rule
from libs.review_tools.condition_execution import prepare_condition_results


def case(value, *, applicable=True):
    pack = load_business_pack("engineering_inspection_v1")
    run = {"projectId": "P", "nodeId": 24, "businessPackId": pack["id"], "inputDocumentVersionIds": ["D"]}
    conditions = {"schemaVersion": "rule-conditions-v1", "checks": [
        {"id": "C", "atomicCheckId": "AC-R24-01", "field": "thickness", "operator": "gte", "expected": 10}]}
    if not applicable:
        conditions["applicability"] = {"id": "A", "field": "thickness", "operator": "lt", "expected": 0}
    rule = {"id": "CUSTOM", "nodeIds": [24], "businessPackId": pack["id"], "executionConditions": conditions}
    state = {"ocr_parse_results": [{"documentVersionId": "D", "fields": [
        {"id": "F", "name": "thickness", "value": value, "pageNo": 1, "bbox": [0, 0, 10, 10]}]}]}
    run["documentScopeSnapshot"] = freeze_document_scope(run, state)
    run["effectiveRuleSnapshot"] = freeze_effective_rule(run, rule)
    rows = list(prepare_condition_results(state, run, pack).values())
    context = {"checklistItems": build_checklist_items(pack, 24, effective_rule=rule),
               "atomicToolExecution": {"atomicResults": rows}}
    return run, context


def normalize(run, context, verdict, refs=None, *, rows=None, guard=None, grounding=None):
    payload = rows if rows is not None else [{"itemId": "AC-R24-01", "verdict": verdict,
        "evidenceRefs": refs if refs is not None else deepcopy(context["atomicToolExecution"]["atomicResults"][0]["toolResults"][0].get("evidenceRefs") or []), "note": "工具判定说明"}]
    return normalize_checklist_output(run, context, json.dumps({"checklist": payload}),
        base={"confidence": 0.8}, grounding_input=grounding or {}, guard=guard or (lambda drafts, _: drafts),
        clone=deepcopy, bounded_confidence=lambda value, **kwargs: 0.8)


@pytest.mark.parametrize("value,applicable,verdict", [(11, True, "符合"), (9, True, "不符合"),
                                                     (None, True, "证据不足"), (11, False, "不适用")])
def test_four_condition_states_survive_checklist_generation(value, applicable, verdict):
    run, context = case(value, applicable=applicable)
    original = deepcopy(context)
    drafts = normalize(run, context, verdict)
    assert drafts[0]["checklistVerdict"] == verdict
    assert context == original
    with pytest.raises(IntegrationServiceError) as error:
        normalize(run, context, "不符合" if verdict != "不符合" else "符合")
    assert error.value.reason == "REVIEW_CHECKLIST_TOOL_CONFLICT"


@pytest.mark.parametrize("damage", ["missing", "duplicate", "stale_rule", "stale_source", "stale_plan"])
def test_missing_or_stale_tool_results_cannot_be_used(damage):
    run, context = case(11)
    rows = context["atomicToolExecution"]["atomicResults"]
    if damage == "missing":
        rows.clear()
    elif damage == "duplicate":
        rows.append(deepcopy(rows[0]))
    else:
        key = {"stale_rule": "ruleSnapshotHash", "stale_source": "sourceSnapshotHash", "stale_plan": "conditionPlanHash"}[damage]
        rows[0]["toolResults"][0][key] = "WRONG"
    with pytest.raises(IntegrationServiceError):
        normalize(run, context, "符合", refs=[{"documentVersionId": "D", "pageNo": 1}])


def test_condition_checklist_must_cover_replacement_once_with_evidence():
    run, context = case(11)
    row = {"itemId": "AC-R24-01", "verdict": "符合"}
    for rows in ([], [row, row]):
        with pytest.raises(IntegrationServiceError) as error:
            normalize(run, context, "符合", rows=rows)
        assert error.value.reason == "REVIEW_CHECKLIST_CONDITION_COVERAGE"
    with pytest.raises(IntegrationServiceError) as error:
        normalize(run, context, "符合", refs=[])
    assert error.value.reason == "REVIEW_CHECKLIST_TOOL_EVIDENCE_MISSING"


@pytest.mark.parametrize("discard", [False, True])
def test_grounding_guard_cannot_silently_downgrade_or_drop_condition_result(discard):
    run, context = case(11)

    def guard(drafts, _):
        if discard:
            return []
        drafts[0]["groundingStatus"] = "insufficient_evidence"
        return drafts

    with pytest.raises(IntegrationServiceError) as error:
        normalize(run, context, "符合", guard=guard)
    assert error.value.reason == ("REVIEW_CHECKLIST_CONDITION_COVERAGE" if discard else "REVIEW_CHECKLIST_TOOL_EVIDENCE_REJECTED")


@pytest.mark.parametrize("key,value", [("documentVersionId", "FOREIGN"), ("pageNo", 2),
                                       ("bbox", [10, 10, 20, 20]), ("fieldId", "OTHER"),
                                       ("correctionId", "INVENTED"), ("evidenceLinkId", "UNKNOWN")])
def test_model_cannot_swap_condition_evidence(key, value):
    run, context = case(11)
    ref = deepcopy(context["atomicToolExecution"]["atomicResults"][0]["toolResults"][0]["evidenceRefs"][0])
    ref[key] = value
    with pytest.raises(IntegrationServiceError) as error:
        normalize(run, context, "符合", refs=[ref])
    assert error.value.reason == "REVIEW_CHECKLIST_TOOL_EVIDENCE_MISMATCH"


def test_link_only_citation_resolves_to_tool_evidence_and_preserves_correction():
    run, context = case(11)
    canonical = context["atomicToolExecution"]["atomicResults"][0]["toolResults"][0]["evidenceRefs"]
    canonical[0]["correctionId"] = "C-1"
    link = {"id": "LINK", **canonical[0]}
    original = deepcopy(context)
    result = normalize(run, context, "符合", refs=[{"evidenceLinkId": "LINK"}], grounding={"evidenceLinks": [link]})
    assert result[0]["evidenceRefs"] == canonical
    assert context == original
    with pytest.raises(IntegrationServiceError):
        normalize(run, context, "符合", refs=[{"evidenceLinkId": "LINK", "pageNo": 1}],
                  grounding={"evidenceLinks": [{**link, "pageNo": 2}]})


def test_citing_subset_retains_complete_tool_evidence():
    run, context = case(11)
    canonical = context["atomicToolExecution"]["atomicResults"][0]["toolResults"][0]["evidenceRefs"]
    canonical.append({**canonical[0], "fieldId": "F2", "bbox": [20, 20, 30, 30]})
    result = normalize(run, context, "符合", refs=[deepcopy(canonical[0])])
    assert result[0]["evidenceRefs"] == canonical


def test_bound_condition_evidence_passes_real_grounding_guard():
    from libs.review_grounding import apply_grounding_guardrails

    run, context = case(11)
    canonical = deepcopy(context["atomicToolExecution"]["atomicResults"][0]["toolResults"][0]["evidenceRefs"])
    grounding = {"groundingStatus": "grounded", "reviewMode": "formal", "documentVersionIds": ["D"],
                 "evidenceTextCorpus": ["工具判定说明"], "evidenceLinks": [{"id": "LINK", **canonical[0]}]}
    result = normalize(run, context, "符合", refs=[{"evidenceLinkId": "LINK"}],
                       grounding=grounding, guard=apply_grounding_guardrails)
    assert result[0]["groundingStatus"] == "grounded"
    assert result[0]["evidenceRefs"] == canonical
