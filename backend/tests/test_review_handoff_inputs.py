from copy import deepcopy

import pytest
from test_review_workstations import run_for

from libs.review_document_scope import ensure_document_sources, freeze_document_scope
from libs.review_handoff_inputs import (
    effective_handoff_inputs,
    freeze_handoff_inputs,
    handoff_dependency_status,
    handoff_prompt_payload,
    initialize_handoff_inputs,
)
from libs.review_handoff_verification import append_verification
from libs.review_handoffs import create_handoff_draft
from libs.review_rule_snapshot import freeze_effective_rule


@pytest.fixture
def inputs():
    state = {"documents": [{"id": "DOC", "projectId": "P", "tenantId": "T", "currentVersionId": "V"}],
             "versions": [{"id": "V", "documentId": "DOC", "tenantId": "T", "hash": "original"}],
             "ocr_parse_results": [{"id": "OCR", "documentVersionId": "V", "tenantId": "T", "pages": [{"pageNo": 1, "text": "original"}]}],
             "review_runs": [], "review_handoffs": []}
    for node, name in ((24, "SOURCE"), (35, "TARGET"), (35, "NEXT")):
        run = run_for(node)
        run.update(id=name, reviewRunId=name, projectId="P", tenantId="T", inputHash=name,
                   inputDocumentVersionIds=["V"], status="completed", outputHash="OUTPUT")
        run["documentScopeSnapshot"] = freeze_document_scope(run, state)
        run["effectiveRuleSnapshot"] = freeze_effective_rule(run, {"id": f"RULE-{node}", "version": "1"})
        state["review_runs"].append(run)
    source, target, run = state["review_runs"]
    subject = {"objectType": "weld", "objectId": "W1", "eventId": "EV1", "repairRound": 0}
    draft = create_handoff_draft(source, target, kind="facts", subject=subject,
                                payload={"observation": "核对焊口W1返修记录"}, evidence_refs=[{"documentVersionId": "V", "pageNo": 1}])
    record = {"id": draft["id"], "projectId": "P", "tenantId": "T", "draft": draft}
    append_verification(record, {"snapshotHash": draft["snapshotHash"], "expectedPreviousId": None,
        "subject": subject, "outcome": "verified", "objectMatchConfirmed": True,
        "evidenceSupportConfirmed": True, "note": "已核对对象与原文"}, actor="INSPECTOR", created_at="2026-09-09T00:00:00Z")
    state["review_handoffs"].append(record)
    selection = {"subject": subject, "confirmedSameObject": True,
                 "items": [{"handoffId": draft["id"], "verificationId": record["verifications"][-1]["id"]}]}
    return state, run, selection


def test_frozen_inputs_are_used_as_grounded_context_and_preserve_history(inputs):
    state, run, selection = inputs
    original = deepcopy(state["review_handoffs"])
    run["handoffSelection"] = deepcopy(selection)
    initialize_handoff_inputs(run, state)
    assert run["inputHash"] != "NEXT" and "handoffSelection" not in run
    result = handoff_prompt_payload(run, state)
    assert result["verifiedHandoffs"][0]["subject"]["objectId"] == "W1"
    assert result["verifiedHandoffs"][0]["evidenceRefs"] == [{"documentVersionId": "V", "pageNo": 1}]
    result["verifiedHandoffs"][0]["payload"]["observation"] = "changed"
    assert state["review_handoffs"] == original
    assert effective_handoff_inputs(run, state)[0]["draft"]["payload"]["observation"] != "changed"
    assert handoff_dependency_status(run, state)["status"] == "current"


@pytest.mark.parametrize("change", ["object", "event", "repair", "confirmation", "verification", "tenant", "recipient", "duplicate", "evidence"])
def test_wrong_identity_or_unselected_evidence_cannot_be_used(inputs, change):
    state, run, selection = inputs
    if change in {"object", "event", "repair"}:
        selection["subject"] = {**selection["subject"], {"object": "objectId", "event": "eventId", "repair": "repairRound"}[change]: "OTHER"}
    elif change == "confirmation":
        selection["confirmedSameObject"] = False
    elif change == "verification":
        selection["items"][0]["verificationId"] = "OLD"
    elif change == "tenant":
        run["tenantId"] = "OTHER"
    elif change == "recipient":
        run["nodeId"] = 36
    elif change == "duplicate":
        selection["items"] *= 2
    elif change == "evidence":
        run["inputDocumentVersionIds"] = []
        run["documentScopeSnapshot"] = freeze_document_scope(run, state)
    with pytest.raises(ValueError):
        freeze_handoff_inputs(run, state, selection)
    assert "handoffInputsSnapshot" not in run


@pytest.mark.parametrize("change", ["source_output", "ocr", "revoked", "snapshot"])
def test_dependency_changes_require_manual_revalidation_without_rewriting_results(inputs, change):
    state, run, selection = inputs
    run["handoffInputsSnapshot"] = freeze_handoff_inputs(run, state, selection)
    run["findingDrafts"] = [{"title": "历史结果保持原样"}]
    before = deepcopy(run)
    if change == "source_output":
        state["review_runs"][0]["outputHash"] = "NEW"
    elif change == "ocr":
        state["ocr_parse_results"][0]["pages"][0]["text"] = "NEW"
    elif change == "revoked":
        record = state["review_handoffs"][0]
        append_verification(record, {"snapshotHash": record["draft"]["snapshotHash"], "expectedPreviousId": record["verifications"][-1]["id"],
            "subject": selection["subject"], "outcome": "rejected", "objectMatchConfirmed": False,
            "evidenceSupportConfirmed": False, "note": "重新核验发现不匹配"}, actor="INSPECTOR", created_at="2026-09-09T01:00:00Z")
    else:
        run["handoffInputsSnapshot"]["items"][0]["draft"]["payload"]["observation"] = "tampered"
        before = deepcopy(run)
    assert handoff_dependency_status(run, state)["requiresRevalidation"] is True
    assert handoff_dependency_status(run, state)["automaticRerun"] is False
    with pytest.raises(Exception, match="REVIEW_INPUT_CHANGED_RECREATE_RUN"):
        ensure_document_sources(run, state)
    assert run == before


def test_object_selection_cannot_conflict_with_condition_mapping(inputs):
    state, run, selection = inputs
    run["conditionObjectMapping"] = {"selection": {"subject": {"objectType": "weld", "objectId": "W2"}}}
    with pytest.raises(ValueError, match="condition_object_mismatch"):
        freeze_handoff_inputs(run, state, selection)
    run["conditionObjectMapping"]["selection"]["subject"]["objectId"] = "W1"
    assert freeze_handoff_inputs(run, state, selection)["subject"]["objectId"] == "W1"
    run["auditInputMode"] = "pure_llm"
    with pytest.raises(ValueError, match="requires_ocr_mode"):
        freeze_handoff_inputs(run, state, selection)


def test_changed_ancestor_invalidates_transitive_dependency(inputs):
    state, middle, selection = inputs
    middle["handoffSelection"] = selection
    initialize_handoff_inputs(middle, state)
    original_target = deepcopy(middle)
    original_target.update(id="FINAL-TARGET", reviewRunId="FINAL-TARGET", nodeId=39,
                           workstationSnapshot=run_for(39)["workstationSnapshot"])
    original_target.pop("handoffInputsSnapshot")
    original_target["documentScopeSnapshot"] = freeze_document_scope(original_target, state)
    original_target["effectiveRuleSnapshot"] = freeze_effective_rule(original_target, {"id": "RULE-39"})
    final = deepcopy(original_target)
    final.update(id="FINAL", reviewRunId="FINAL")
    state["review_runs"].extend([original_target, final])
    draft = create_handoff_draft(middle, original_target, kind="facts", subject=selection["subject"],
        payload={"observation": "第二次交接"}, evidence_refs=[{"documentVersionId": "V", "pageNo": 1}])
    record = {"id": draft["id"], "projectId": "P", "tenantId": "T", "draft": draft}
    append_verification(record, {"snapshotHash": draft["snapshotHash"], "expectedPreviousId": None,
        "subject": selection["subject"], "outcome": "verified", "objectMatchConfirmed": True,
        "evidenceSupportConfirmed": True, "note": "已核验"}, actor="INSPECTOR", created_at="2026-09-09T01:00:00Z")
    state["review_handoffs"].append(record)
    final["handoffInputsSnapshot"] = freeze_handoff_inputs(final, state, {**selection,
        "items": [{"handoffId": record["id"], "verificationId": record["verifications"][-1]["id"]}]})
    assert handoff_dependency_status(final, state)["status"] == "current"
    state["review_runs"][0]["outputHash"] = "CHANGED-ANCESTOR"
    assert handoff_dependency_status(final, state)["requiresRevalidation"] is True
