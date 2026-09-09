from copy import deepcopy

import pytest
from test_review_workstations import run_for

from libs.review_handoffs import ReviewHandoffError, create_handoff_draft, validate_handoff_draft


def runs():
    source, target = run_for(24), run_for(35)
    for run, name in ((source, "SOURCE"), (target, "TARGET")):
        run.update(id=name, tenantId="TENANT", inputHash=name, inputDocumentVersionIds=["VERSION-1"])
    return source, target


SUBJECT = {"objectType": "weld", "objectId": "W-101", "repairRound": 1}
EVIDENCE = [{"documentVersionId": "VERSION-1", "pageNo": 2}]


@pytest.mark.parametrize("kind", ["facts", "judgment", "collaboration"])
def test_three_handoff_kinds_freeze_provenance_without_granting_authority(kind):
    source, target = runs()
    payload = {"description": "待核对的焊口信息"}
    draft = create_handoff_draft(source, target, kind=kind, subject=SUBJECT, payload=payload, evidence_refs=EVIDENCE)
    validate_handoff_draft(draft, source, target, subject=SUBJECT)
    assert draft["source"]["stationId"] == "A" and draft["target"]["stationId"] == "E"
    assert draft["authoritative"] is False and draft["objectMatchStatus"] == "unverified"
    payload["description"] = "changed"
    assert draft["payload"]["description"] != payload["description"]
    assert create_handoff_draft(source, target, kind=kind, subject=SUBJECT, payload=draft["payload"], evidence_refs=EVIDENCE)["id"] == draft["id"]


@pytest.mark.parametrize("field,value", [("projectId", "OTHER"), ("tenantId", "OTHER"), ("inputHash", "NEW"), ("outputHash", "NEW"), ("findingDrafts", [{"id": "NEW"}])])
def test_changed_source_cannot_be_reused(field, value):
    source, target = runs()
    draft = create_handoff_draft(source, target, kind="facts", subject=SUBJECT, payload={"value": 1}, evidence_refs=EVIDENCE)
    before = deepcopy(draft)
    source[field] = value
    with pytest.raises(ReviewHandoffError, match="version_changed"):
        validate_handoff_draft(draft, source, target, subject=SUBJECT)
    assert draft == before


def test_cross_scope_wrong_evidence_and_repair_round_are_rejected():
    source, target = runs()
    args = {"kind": "judgment", "subject": SUBJECT, "payload": {"status": "unverified"}, "evidence_refs": EVIDENCE}
    with pytest.raises(ReviewHandoffError, match="scope_mismatch"):
        create_handoff_draft(source, {**target, "projectId": "OTHER"}, **args)
    with pytest.raises(ReviewHandoffError, match="outside_source"):
        create_handoff_draft(source, target, **{**args, "evidence_refs": [{"documentVersionId": "UNSELECTED", "pageNo": 1}]})
    draft = create_handoff_draft(source, target, **args)
    with pytest.raises(ReviewHandoffError, match="subject_changed"):
        validate_handoff_draft(draft, source, target, subject={**SUBJECT, "repairRound": 2})
    draft["authoritative"] = True
    with pytest.raises(ReviewHandoffError, match="snapshot_changed"):
        validate_handoff_draft(draft, source, target, subject=SUBJECT)


@pytest.mark.parametrize("kind", ["facts", "judgment"])
def test_factual_handoffs_require_source_evidence(kind):
    source, target = runs()
    with pytest.raises(ReviewHandoffError, match="evidence_required"):
        create_handoff_draft(source, target, kind=kind, subject=SUBJECT, payload={"value": 1}, evidence_refs=[])


@pytest.mark.parametrize("change", [{"repairRound": True}, {"repairRound": -1}, {"objectId": ""}, {"objectType": "unknown"}])
def test_handoff_object_identity_is_explicit(change):
    source, target = runs()
    with pytest.raises(ReviewHandoffError, match="subject_invalid"):
        create_handoff_draft(source, target, kind="collaboration", subject={**SUBJECT, **change}, payload={"request": "核对"}, evidence_refs=[])


def test_document_list_and_target_version_drift_leave_draft_unchanged():
    source, target = runs()
    draft = create_handoff_draft(source, target, kind="collaboration", subject=SUBJECT, payload={"request": "核对"}, evidence_refs=[])
    changed_source = {**source, "inputDocumentVersionIds": ["NEW-VERSION"]}
    changed_target = {**target, "inputHash": "NEW-INPUT"}
    for left, right in ((changed_source, target), (source, changed_target)):
        with pytest.raises(ReviewHandoffError, match="version_changed"):
            validate_handoff_draft(draft, left, right, subject=SUBJECT)
    validate_handoff_draft(draft, source, target, subject=SUBJECT)
