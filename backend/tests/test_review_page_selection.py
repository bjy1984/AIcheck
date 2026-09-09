from copy import deepcopy
from types import SimpleNamespace

import fitz
import pytest

from apps.api import review_input_selection as selection


@pytest.fixture
def page_selection(monkeypatch, tmp_path):
    path = tmp_path / "version.pdf"
    with fitz.open() as pdf:
        for _ in range(3):
            pdf.new_page()
        pdf.save(path)
    state = {"versions": [{"id": "V", "documentId": "D", "storageKey": "fixed", "tenantId": "T"}],
             "documents": [{"id": "D", "currentVersionId": "V"}],
             "node_evidence_links": [{"id": "IN", "documentVersionId": "V", "pageNo": 2},
                                     {"id": "OUT", "documentVersionId": "V", "pageNo": 1}]}
    captured = {}
    monkeypatch.setenv("AICHECK_WORKSTATIONS_ENABLED", "true")
    monkeypatch.setenv("AICHECK_REVIEW_PAGE_RANGES_ENABLED", "true")
    monkeypatch.setattr(selection, "actor_visible_evidence_repository", lambda *args: SimpleNamespace(state=deepcopy(state)))
    def readiness(repo, project, node):
        captured.update(repo.state)
        return {"readyForFormalReview": False}
    monkeypatch.setattr(selection, "build_node_evidence_readiness", readiness)
    services = SimpleNamespace(tenant_id_for_record=lambda row: row.get("tenantId"),
                               request_tenant_id=lambda _: "T", document_body_uploaded=lambda *args: True,
                               local_storage_path=lambda key: path if key == "fixed" else None,
                               project_document_storage_object=lambda _: None)
    body = {"inputDocumentVersionIds": ["V"], "inputDocumentPageRanges": {"V": {"start": 2, "end": 3}},
            "auditInputMode": "ocr_llm"}
    return services, body, state, captured


def test_authorized_original_and_scoped_readiness(page_selection):
    services, body, state, captured = page_selection
    before = deepcopy(state)
    versions, readiness = selection.resolve_review_input_selection(services, None, "P", 16, body)
    assert versions == ["V"]
    assert readiness["inputSelection"]["documentPageRanges"] == body["inputDocumentPageRanges"]
    assert readiness["inputSelection"]["originalPageCounts"] == {"V": 3}
    assert [row["id"] for row in captured["node_evidence_links"]] == ["IN"]
    assert state == before


@pytest.mark.parametrize("change,reason", [
    ({"inputDocumentPageRanges": {"V": {"start": 2, "end": 4}}}, "实际页数"),
    ({"inputDocumentPageRanges": {"V": {"start": 0, "end": 2}}}, "范围无效"),
    ({"inputDocumentPageRanges": {"OTHER": {"start": 1, "end": 2}}}, "范围无效"),
    ({"inputDocumentVersionIds": ["OTHER"]}, "可访问范围"),
    ({"auditInputMode": "pure_llm"}, "OCR"),
])
def test_invalid_selection_rejected_before_readiness(page_selection, change, reason):
    services, body, _, captured = page_selection
    body.update(change)
    with pytest.raises(selection.ReviewInputSelectionError, match=reason):
        selection.resolve_review_input_selection(services, None, "P", 16, body)
    assert captured == {}


def test_missing_original_never_uses_current_filename(page_selection):
    services, body, _, captured = page_selection
    services.local_storage_path = lambda _: None
    with pytest.raises(selection.ReviewInputSelectionError, match="PDF页数"):
        selection.resolve_review_input_selection(services, None, "P", 16, body)
    assert captured == {}


def test_disabled_rollout_and_missing_explicit_version_are_rejected(page_selection, monkeypatch):
    services, body, _, _ = page_selection
    monkeypatch.delenv("AICHECK_REVIEW_PAGE_RANGES_ENABLED")
    with pytest.raises(selection.ReviewInputSelectionError, match="全链路"):
        selection.resolve_review_input_selection(services, None, "P", 16, body)
    monkeypatch.setenv("AICHECK_REVIEW_PAGE_RANGES_ENABLED", "true")
    del body["inputDocumentVersionIds"]
    with pytest.raises(selection.ReviewInputSelectionError, match="明确选择"):
        selection.resolve_review_input_selection(services, None, "P", 16, body)
