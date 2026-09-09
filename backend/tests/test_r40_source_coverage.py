from copy import deepcopy

import pytest
from test_r40_record_correspondence import evaluate, fixture

from libs.review_document_scope import freeze_document_scope


@pytest.mark.parametrize("mismatch", [False, True])
@pytest.mark.parametrize("end,expected", [(None, "evidence_insufficient"), (3, "passed"), (9, "evidence_insufficient")])
def test_unread_pages_cannot_create_complete_correspondence(end, expected, mismatch):
    state, run = fixture()
    parse = state["ocr_parse_results"][0]
    parse["metadata"] = {"recognitionPageCoverage": {"complete": False, "unprocessedPageNos": [9]}}
    if end:
        run["inputDocumentPageRanges"] = {"V": {"start": 1, "end": end}}
    if mismatch:
        parse["tables"][3]["normalizedRows"][0]["recordId"] = "WRONG"
    if run.get("inputDocumentPageRanges"):
        run["documentScopeSnapshot"] = freeze_document_scope(run, state)
    before = deepcopy(state)
    output = evaluate(state, run)
    assert output["result"] == ("failed" if mismatch else expected)
    assert bool(output["facts"]["selectionIssues"]) is (end != 3)
    assert state == before


@pytest.mark.parametrize("case", ["duplicate_version", "duplicate_document", "extra_parse", "missing_parse", "unknown_gap", "excluded_report_page"])
def test_ambiguous_or_unread_source_cannot_be_used_as_complete(case):
    state, run = fixture()
    parse = state["ocr_parse_results"][0]
    if case == "duplicate_version": state["versions"].append(deepcopy(state["versions"][0]))
    if case == "duplicate_document": state["documents"].append(deepcopy(state["documents"][0]))
    if case == "extra_parse":
        extra = deepcopy(parse)
        extra.update(id="OTHER", tables=[])
        state["ocr_parse_results"].append(extra)
    if case == "missing_parse":
        state["versions"].append({"id": "UNREAD", "documentId": "D", "tenantId": "T"})
        run["inputDocumentVersionIds"].append("UNREAD")
    if case == "unknown_gap":
        parse["metadata"] = {"recognitionPageCoverage": {"complete": False, "unprocessedPageNos": []}}
        run["inputDocumentPageRanges"] = {"V": {"start": 1, "end": 3}}
    if case == "excluded_report_page":
        parse["tables"][3]["pageNo"] = 9
        run["inputDocumentPageRanges"] = {"V": {"start": 1, "end": 3}}
    if run.get("inputDocumentPageRanges"):
        run["documentScopeSnapshot"] = freeze_document_scope(run, state)
    assert evaluate(state, run)["result"] == "evidence_insufficient"


def test_ambiguous_version_cannot_support_a_failure_either():
    state, run = fixture()
    state["versions"].append(deepcopy(state["versions"][0]))
    state["ocr_parse_results"][0]["tables"][3]["normalizedRows"][0]["recordId"] = "WRONG"
    assert evaluate(state, run)["result"] == "evidence_insufficient"


def test_unselected_unread_document_does_not_expand_task_scope():
    state, run = fixture()
    extra = deepcopy(state["ocr_parse_results"][0])
    extra.update(id="OTHER", documentVersionId="OTHER")
    extra["metadata"] = {"recognitionPageCoverage": {"complete": False, "unprocessedPageNos": [1]}}
    state["ocr_parse_results"].append(extra)
    assert evaluate(state, run)["result"] == "passed"
