from copy import deepcopy

import pytest

from apps.api.review_input_selection import (
    ReviewInputSelectionError,
    resolve_review_input_selection,
)
from libs.review_document_scope import freeze_document_scope, validate_document_scope
from libs.review_input_data import selected_parse_results
from libs.review_page_scope import normalize_page_ranges, page_record_in_range


@pytest.mark.parametrize("value", [None, [], {"V": {"start": 0, "end": 3}},
                                  {"V": {"start": True, "end": 3}},
                                  {"V": {"start": 1.0, "end": 3}},
                                  {"V": {"start": 4, "end": 3}},
                                  {"V": {"start": 1}},
                                  {"V": {"start": 1, "end": 3, "extra": 1}},
                                  {"OTHER": {"start": 1, "end": 3}}])
def test_invalid_ranges_rejected(value):
    with pytest.raises(ValueError):
        normalize_page_ranges(value, ["V"])


def test_whole_version_default_and_detached_normalization():
    assert normalize_page_ranges({}, ["V"]) == {}
    source = {"V": {"start": 2, "end": 5}}
    result = normalize_page_ranges(source, ["V"])
    source["V"]["end"] = 9
    assert result == {"V": {"start": 2, "end": 5}}


@pytest.mark.parametrize("record,expected", [({"pageNo": 2}, True), ({"pageNo": 5}, True),
                                           ({"pageNo": 1}, False), ({"pageNo": 6}, False),
                                           ({}, False), ({"pageNo": True}, False),
                                           ({"pageNo": "2"}, False),
                                           ({"pageNo": 2, "endPage": 6}, False),
                                           ({"pageNo": 3, "endPage": 2}, False),
                                           ({"pageNo": 2, "endPage": 5}, True)])
def test_page_positions_are_inclusive_and_fail_closed(record, expected):
    assert page_record_in_range(record, {"start": 2, "end": 5}) is expected


def test_range_changes_invalidate_frozen_scope_and_hash():
    run = {"projectId": "P", "nodeId": 16, "inputDocumentVersionIds": ["V"],
           "inputDocumentPageRanges": {"V": {"start": 2, "end": 5}}}
    run["documentScopeSnapshot"] = freeze_document_scope(run)
    original = deepcopy(run)
    validate_document_scope(run)
    run["inputDocumentPageRanges"]["V"]["end"] = 6
    with pytest.raises(ValueError, match="pages_mismatch"):
        validate_document_scope(run)
    run = deepcopy(original)
    run["documentScopeSnapshot"]["documentPageRanges"]["V"]["end"] = 6
    with pytest.raises(ValueError, match="hash_mismatch"):
        validate_document_scope(run)
    run = deepcopy(original)
    del run["documentScopeSnapshot"]
    with pytest.raises(ValueError, match="snapshot_required"):
        validate_document_scope(run)


def test_old_snapshot_cannot_silently_gain_page_restriction():
    run = {"inputDocumentVersionIds": ["V"]}
    run["documentScopeSnapshot"] = freeze_document_scope(run)
    validate_document_scope(run)
    run["inputDocumentPageRanges"] = {"V": {"start": 2, "end": 5}}
    with pytest.raises(ValueError, match="pages_mismatch"):
        validate_document_scope(run)


@pytest.mark.parametrize("body", [{"inputDocumentPageRanges": {}},
                                  {"inputDocumentVersionIds": ["V"],
                                   "inputDocumentPageRanges": {"V": {"start": 2, "end": 5}}}])
def test_api_never_silently_ignores_requested_ranges(body):
    with pytest.raises(ReviewInputSelectionError, match="全链路验收"):
        resolve_review_input_selection(None, None, "P", 16, body)


def test_common_reader_removes_outside_pages_and_whole_file_fallbacks_without_mutation():
    run = {"projectId": "P", "nodeId": 16, "inputDocumentVersionIds": ["V", "WHOLE"],
           "inputDocumentPageRanges": {"V": {"start": 2, "end": 3}}}
    parse = {"documentVersionId": "V", "fullText": "OUTSIDE", "metadata": {"summary": "OUTSIDE"},
             "fields": [{"pageNo": 2, "value": "IN"}, {"pageNo": 4, "value": "OUTSIDE"},
                        {"value": "UNKNOWN-PAGE"}],
             "tables": [{"pageNo": 2, "endPage": 4, "contentMarkdown": "CROSS-PAGE"},
                        {"pageNo": 2, "normalizedRows": [{"value": "IN"}]},
                        {"pageNo": 2, "normalizedRows": [{"pageNo": 4, "value": "OUTSIDE"}]}],
             "seals": [{"pageNo": 3, "text": "IN"}],
             "fragments": [{"pageNo": 4, "text": "OUTSIDE"}, {"pageNo": 3, "text": "IN"}]}
    whole = {"documentVersionId": "WHOLE", "fullText": "WHOLE-TEXT"}
    state = {"ocr_parse_results": [parse, whole]}
    original = deepcopy(state)
    run["documentScopeSnapshot"] = freeze_document_scope(run, state)
    selected = selected_parse_results(state, {}, context={"reviewRun": run})
    assert selected[0]["fields"] == [{"pageNo": 2, "value": "IN"}]
    assert len(selected[0]["tables"]) == 1
    assert selected[0]["fragments"] == [{"pageNo": 3, "text": "IN"}]
    assert "fullText" not in selected[0] and "metadata" not in selected[0]
    assert selected[1] == whole
    selected[0]["fields"][0]["value"] = "MUTATION"
    assert state == original


@pytest.mark.parametrize("correction_page,expected", [(None, "ORIGINAL"), (1, "ORIGINAL"),
                                                       (3, "ORIGINAL"), (2, "CORRECTED")])
def test_scoped_correction_requires_matching_page(correction_page, expected):
    run = {"projectId": "P", "nodeId": 16, "inputDocumentVersionIds": ["V"],
           "inputDocumentPageRanges": {"V": {"start": 2, "end": 3}}}
    state = {"ocr_parse_results": [{"documentVersionId": "V", "fields": [
        {"fieldName": "grade", "pageNo": 2, "value": "ORIGINAL"}]}],
        "fact_corrections": [{"projectId": "P", "nodeId": 16, "documentVersionId": "V", "fieldId": "F",
                              "status": "active", "fieldName": "grade", "correctedValue": "CORRECTED",
                              "pageNo": correction_page}]}
    run["documentScopeSnapshot"] = freeze_document_scope(run, state)
    result = selected_parse_results(state, {}, context={"reviewRun": run})
    assert result[0]["fields"][0]["value"] == expected
