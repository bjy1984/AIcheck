"""Approved test calls may contain whole selected OCR, not local review metadata."""

from copy import deepcopy

from libs.jev_evaluation_input import approved_ocr_text
from libs.review_document_scope import freeze_document_scope


def _case():
    state = {
        "documents": [{"id": "D-PRIVATE", "projectId": "P-PRIVATE",
                       "fileName": "PRIVATE-FILENAME.pdf", "tenantId": "T-PRIVATE"}],
        "versions": [{"id": "V-PRIVATE", "documentId": "D-PRIVATE"}],
        "ocr_parse_results": [{"id": "OLD", "documentVersionId": "V-PRIVATE",
                               "finishedAt": "2026-09-01T00:00:00Z",
                               "fields": [{"fieldName": "grade", "pageNo": 2, "value": "STALE"}]},
                              {"id": "NEW", "documentVersionId": "V-PRIVATE",
                               "finishedAt": "2026-09-02T00:00:00Z",
                               "fields": [{"fieldName": "grade", "pageNo": 2, "value": "CURRENT"},
                                          {"fieldName": "grade", "pageNo": 4, "value": "OUTSIDE"}]}],
        "fact_corrections": [{"projectId": "P-PRIVATE", "nodeId": 14,
                              "documentVersionId": "V-PRIVATE", "fieldId": "F1",
                              "status": "active", "fieldName": "grade", "pageNo": 2,
                              "correctedValue": "HUMAN"}],
    }
    scope = {"projectId": "P-PRIVATE", "tenantId": "T-PRIVATE", "nodeId": 14,
             "inputDocumentVersionIds": ["V-PRIVATE"],
             "inputDocumentPageRanges": {"V-PRIVATE": {"start": 2, "end": 3}}}
    scope["documentScopeSnapshot"] = freeze_document_scope(scope, state)
    return state, scope


def test_whole_selected_ocr_keeps_page_scope_and_correction_without_local_metadata():
    state, scope = _case()
    status, text = approved_ocr_text(state, scope)
    assert status == "ready"
    assert "HUMAN" in text
    assert all(value not in text for value in ("STALE", "CURRENT", "OUTSIDE", "P-PRIVATE",
                                               "D-PRIVATE", "V-PRIVATE", "T-PRIVATE",
                                               "PRIVATE-FILENAME"))
    assert "[第 2 页]" in text


def test_failed_latest_ocr_and_foreign_project_never_use_old_or_wrong_source():
    state, scope = _case()
    latest = next(row for row in state["ocr_parse_results"] if row["id"] == "NEW")
    latest["status"] = "failed"
    scope["documentScopeSnapshot"] = freeze_document_scope(scope, state)
    assert approved_ocr_text(state, scope) == ("ocr_not_ready", "")
    other = deepcopy(scope)
    other["projectId"] = "OTHER-PROJECT"
    assert approved_ocr_text(state, other) == ("invalid_scope", "")


def test_ocr_over_limit_is_skipped_without_excerpt():
    state, scope = _case()
    state["ocr_parse_results"][-1]["fragments"] = [{"pageNo": 2, "text": "長" * 40_001}]
    scope["documentScopeSnapshot"] = freeze_document_scope(scope, state)
    assert approved_ocr_text(state, scope) == ("overlong_document", "")
