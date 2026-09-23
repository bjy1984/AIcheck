from __future__ import annotations

from copy import deepcopy

import pytest

from libs.review_orchestrator.execution import validate_review_evidence_refs

ANCHOR = {
    "id": "EV-V1-1",
    "documentId": "DOC-1",
    "documentVersionId": "V1",
    "pageNo": 2,
    "bbox": [10, 20, 80, 45],
    "quotedText": "许可范围 GC2",
}
RUN = {
    "projectId": "P1",
    "tenantId": "T1",
    "inputDocumentVersionIds": ["V1"],
    "inputDocumentPageRanges": {"V1": {"start": 2, "end": 3}},
}
STATE = {
    "documents": [{"id": "DOC-1", "projectId": "P1", "tenantId": "T1"}],
    "versions": [{"id": "V1", "documentId": "DOC-1"}],
}


def validate(refs, *, anchor=ANCHOR, run=RUN, state=STATE):
    drafts = [{"title": "许可范围 GC2", "description": "", "evidenceRefs": deepcopy(refs)}]
    result = validate_review_evidence_refs(
        drafts, [deepcopy(anchor)], review_run=deepcopy(run), source_state=deepcopy(state),
    )
    return result, drafts


def test_reference_is_copied_from_the_frozen_source_anchor() -> None:
    result, drafts = validate([{"evidenceLinkId": "EV-V1-1"}])

    assert result["passed"] is True
    assert drafts[0]["evidenceRefs"][0] == {
        "evidenceLinkId": "EV-V1-1", "documentId": "DOC-1",
        "documentVersionId": "V1", "pageNo": 2,
        "bbox": [10, 20, 80, 45], "quotedText": "许可范围 GC2",
    }


def test_source_anchor_alias_resolves_to_the_canonical_link() -> None:
    result, drafts = validate(
        [{"evidenceLinkId": "OCR-1"}],
        anchor={**ANCHOR, "evidenceRefId": "OCR-1"},
    )

    assert result["passed"] is True
    assert drafts[0]["evidenceRefs"][0]["evidenceLinkId"] == "EV-V1-1"


@pytest.mark.parametrize("change", [
    {"documentVersionId": "V0"},
    {"pageNo": 9999},
    {"bbox": [10, 20, 81, 45]},
    {"quotedText": "许可范围 GC1"},
    {"documentId": "DOC-OTHER"},
])
def test_reference_cannot_override_its_source_anchor(change) -> None:
    result, _ = validate([{"evidenceLinkId": "EV-V1-1", **change}])

    assert result["passed"] is False
    assert "EVIDENCE_REF_ANCHOR_MISMATCH" in {item["code"] for item in result["failures"]}


def test_made_up_position_without_a_source_anchor_is_rejected() -> None:
    result, _ = validate([{"documentVersionId": "V1", "pageNo": 9999, "bbox": [0, 0, 1, 1]}])

    assert result["passed"] is False
    assert "EVIDENCE_LINK_NOT_FOUND" in {item["code"] for item in result["failures"]}


def test_invalid_second_reference_does_not_partially_normalize_the_first() -> None:
    refs = [{"evidenceLinkId": "EV-V1-1"}, {"evidenceLinkId": "missing"}]
    result, drafts = validate(refs)

    assert result["passed"] is False
    assert drafts[0]["evidenceRefs"] == refs


def test_source_anchor_must_belong_to_the_frozen_document_and_page_range() -> None:
    outside_page, _ = validate([{"evidenceLinkId": "EV-V1-1"}], run={
        **RUN, "inputDocumentPageRanges": {"V1": {"start": 3, "end": 3}},
    })
    wrong_project, _ = validate([{"evidenceLinkId": "EV-V1-1"}], state={
        **STATE, "documents": [{"id": "DOC-1", "projectId": "P2", "tenantId": "T1"}],
    })

    assert "EVIDENCE_REF_OUTSIDE_PAGE_RANGE" in {item["code"] for item in outside_page["failures"]}
    assert "EVIDENCE_ANCHOR_OUTSIDE_PROJECT" in {item["code"] for item in wrong_project["failures"]}


def test_unlocatable_anchor_and_missing_evidence_cannot_pass_formal_validation() -> None:
    unlocatable, _ = validate([{"evidenceLinkId": "EV-V1-1"}], anchor={**ANCHOR, "bbox": None})
    missing, _ = validate([])

    assert "EVIDENCE_ANCHOR_NOT_LOCATABLE" in {item["code"] for item in unlocatable["failures"]}
    assert "NO_EVIDENCE_REFS" in {item["code"] for item in missing["failures"]}
