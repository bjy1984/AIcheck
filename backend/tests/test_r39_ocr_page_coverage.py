from copy import deepcopy

import pytest
from test_r39_facts import evaluate
from test_r39_reference_ocr_fields import fixture

from libs.ocr.page_coverage import CODE
from libs.review_page_scope import restrict_parse_result


@pytest.mark.parametrize("known_failure", [False, True])
@pytest.mark.parametrize("scope", [None, {"start": 1, "end": 7}, {"start": 1, "end": 9}])
def test_reference_preserves_findings_but_does_not_pass_unread_selected_pages(known_failure, scope):
    state, run = fixture()
    parse = state["ocr_parse_results"][1]
    parse["quality"] = {"reasons": [CODE]}
    parse["metadata"] = {"recognitionPageCoverage": {"complete": False, "unprocessedPageNos": [9]}}
    if known_failure:
        next(row for row in parse["fields"] if row["fieldCode"] == "procedure_revision")["fieldValue"] = "C"
        next(row for row in parse["fragments"] if row["text"] == "版次：B")["text"] = "版次：C"
    if scope:
        run["inputDocumentPageRanges"] = {"PV1": scope}
    before = deepcopy(state)
    _, result = evaluate(state, run, "evaluate_r39_procedure_reference")
    incomplete = scope is None or scope["end"] == 9
    assert result["result"] == ("failed" if known_failure else "evidence_insufficient" if incomplete else "passed")
    if incomplete:
        assert result["facts"]["coverage"]["complete"] is False
        issue = result["facts"]["selectionIssues"][0]
        assert issue["code"] == "r39_ocr_page_coverage_incomplete"
        assert issue["pageNos"] == [9]
    assert state == before


@pytest.mark.parametrize("pages", [[], None, [True], [9, "unknown"]])
def test_unlocated_gap_cannot_be_excluded_by_a_page_range(pages):
    state, run = fixture()
    parse = state["ocr_parse_results"][1]
    parse["quality"] = {"reasons": [CODE]}
    parse["metadata"] = {"localRenderCoverage": {"complete": False, "unrenderedPageNos": pages}}
    run["inputDocumentPageRanges"] = {"PV1": {"start": 1, "end": 7}}
    _, result = evaluate(state, run, "evaluate_r39_procedure_reference")
    assert result["result"] == "evidence_insufficient"
    assert result["facts"]["selectionIssues"][0]["gapLocationKnown"] is False


def test_range_projection_keeps_only_relevant_gap_and_no_unscoped_text():
    parse = {"documentVersionId": "V1", "text": "private outside text", "quality": {"reasons": [CODE]},
             "metadata": {"summary": "private summary", "localRenderCoverage": {"complete": False, "unrenderedPageNos": [2, 99]}}}
    scoped = restrict_parse_result(parse, {"start": 1, "end": 3})
    assert scoped["reviewCoverageGap"] == {"code": CODE, "pageNos": [2], "gapLocationKnown": True}
    assert "metadata" not in scoped
    assert "text" not in scoped
    narrower = restrict_parse_result(scoped, {"start": 1, "end": 1})
    assert narrower["reviewCoverageGap"] is None
