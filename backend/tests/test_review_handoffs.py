from copy import deepcopy

import pytest
from test_review_workstations import run_for

from libs.review_handoffs import ReviewHandoffError, create_handoff_draft, validate_handoff_draft


def runs():
    source, target = run_for(24), run_for(35)
    for run, name in ((source, "SOURCE"), (target, "TARGET")):
        run.update(id=name, tenantId="TENANT", inputHash=name, inputDocumentVersionIds=["VERSION-1"])
    return source, target


SUBJECT = {"objectType": "weld", "objectId": "W-101", "repairRound": 1, "eventId": "EVENT-1"}
EVIDENCE = [{"documentVersionId": "VERSION-1", "pageNo": 2}]


def test_handoff_cannot_export_evidence_outside_selected_pages():
    from libs.review_document_scope import freeze_document_scope
    source, target = runs()
    source["inputDocumentPageRanges"] = {"VERSION-1": {"start": 2, "end": 3}}
    source["documentScopeSnapshot"] = freeze_document_scope(source)
    create_handoff_draft(source, target, kind="facts", subject=SUBJECT, payload={"note": "review"}, evidence_refs=EVIDENCE)
    with pytest.raises(ReviewHandoffError, match="outside_source_pages"):
        create_handoff_draft(source, target, kind="facts", subject=SUBJECT, payload={"note": "review"},
                             evidence_refs=[{"documentVersionId": "VERSION-1", "pageNo": 4}])


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


@pytest.mark.parametrize("event", [None, "", " ", True, 1, " EVENT-1"])
def test_new_handoffs_require_explicit_nonblank_event(event):
    source, target = runs()
    with pytest.raises(ReviewHandoffError, match="event_identity_required"):
        create_handoff_draft(source, target, kind="facts", subject={**SUBJECT, "eventId": event},
                             payload={"value": 1}, evidence_refs=EVIDENCE)


def test_same_object_round_different_events_are_distinct_and_cannot_be_substituted():
    source, target = runs()
    first = create_handoff_draft(source, target, kind="facts", subject=SUBJECT,
                                 payload={"value": 1}, evidence_refs=EVIDENCE)
    other_subject = {**SUBJECT, "eventId": "EVENT-2"}
    second = create_handoff_draft(source, target, kind="facts", subject=other_subject,
                                  payload={"value": 1}, evidence_refs=EVIDENCE)
    assert first["schemaVersion"] == "review-handoff-draft-v3"
    assert first["id"] != second["id"]
    with pytest.raises(ReviewHandoffError, match="subject_changed"):
        validate_handoff_draft(first, source, target, subject=other_subject)
    assert first["objectMatchStatus"] == "unverified"


def test_historical_v1_validates_without_inventing_event_or_rewriting_id():
    from libs.review_workstations import digest

    source, target = runs()
    historical = create_handoff_draft(source, target, kind="facts", subject=SUBJECT,
                                      payload={"value": 1}, evidence_refs=EVIDENCE)
    from libs.review_handoffs import _identity

    historical["target"] = _identity(target)
    historical["schemaVersion"] = "review-handoff-draft-v1"
    historical["subject"].pop("eventId")
    content = {key: value for key, value in historical.items() if key not in {"id", "snapshotHash"}}
    historical["snapshotHash"] = digest(content)
    historical["id"] = "HANDOFF-" + digest(content)[:24].upper()
    before = deepcopy(historical)
    validate_handoff_draft(historical, source, target, subject=historical["subject"])
    assert historical == before
    with pytest.raises(ReviewHandoffError, match="subject_changed"):
        validate_handoff_draft(historical, source, target, subject=SUBJECT)
    with pytest.raises(ReviewHandoffError, match="subject_invalid"):
        create_handoff_draft(source, target, kind="facts", subject=historical["subject"],
                             payload={"value": 1}, evidence_refs=EVIDENCE)


@pytest.mark.parametrize("field,value", [
    ("status", "running"), ("status", "completed"),
    ("outputHash", "NEW-OUTPUT"), ("findingDrafts", [{"id": "OWN-FINDING"}]),
])
def test_receiver_progress_does_not_expire_v3_but_source_progress_does(field, value):
    source, target = runs()
    record = create_handoff_draft(source, target, kind="facts", subject=SUBJECT,
                                  payload={"value": 1}, evidence_refs=EVIDENCE)
    before = deepcopy(record)
    target[field] = value
    validate_handoff_draft(record, source, target, subject=SUBJECT)
    source[field] = value
    with pytest.raises(ReviewHandoffError, match="run_version_changed"):
        validate_handoff_draft(record, source, target, subject=SUBJECT)
    assert record == before


@pytest.mark.parametrize("field,value", [
    ("inputHash", "OTHER"), ("documentScopeSnapshot", {"changed": True}),
    ("effectiveRuleSnapshot", {"changed": True}), ("inputDocumentVersionIds", ["OTHER"]),
    ("id", "OTHER"), ("tenantId", "OTHER"),
])
def test_receiver_input_and_scope_changes_still_expire_v3(field, value):
    source, target = runs()
    record = create_handoff_draft(source, target, kind="facts", subject=SUBJECT,
                                  payload={"value": 1}, evidence_refs=EVIDENCE)
    if field == "documentScopeSnapshot":
        from libs.review_document_scope import freeze_document_scope
        value = freeze_document_scope(target, {})
    target[field] = value
    with pytest.raises(ReviewHandoffError, match="run_version_changed"):
        validate_handoff_draft(record, source, target, subject=SUBJECT)


def test_v2_historical_receiver_identity_retains_original_output_binding():
    from libs.review_handoffs import _build_handoff_draft

    source, target = runs()
    old = _build_handoff_draft(source, target, kind="facts", subject=SUBJECT,
                              payload={"value": 1}, evidence_refs=EVIDENCE,
                              schema="review-handoff-draft-v2")
    before = deepcopy(old)
    validate_handoff_draft(old, source, target, subject=SUBJECT)
    target["status"] = "running"
    with pytest.raises(ReviewHandoffError, match="run_version_changed"):
        validate_handoff_draft(old, source, target, subject=SUBJECT)
    assert old == before
