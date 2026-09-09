from copy import deepcopy

import fitz
import pytest

from apps.ocr_service.pages import public_document_pages, render_document_pages
from apps.ocr_service.service import OcrService
from libs.ocr.page_coverage import CODE, attach_render_coverage
from libs.ocr_readiness import parse_result_outcome_status, parse_result_quality_blockers


@pytest.mark.parametrize("limit", [2, 4])
def test_actual_pdf_render_limit_reaches_public_outcome(tmp_path, monkeypatch, limit):
    monkeypatch.setenv("AICHECK_OCR_PAGE_CACHE_DIR", str(tmp_path / "cache"))
    source = tmp_path / "four-pages.pdf"
    with fitz.open() as document:
        for _ in range(4):
            document.new_page(width=72, height=72).insert_text((5, 20), "Text")
        document.save(source)
    pages = public_document_pages(render_document_pages(source, profile={"preprocessPolicy": {"maxPages": limit, "renderDpi": 72}}))
    result = {"status": "success", "outcomeStatus": "completed", "pages": pages,
              "fragments": [{"pageNo": 1, "text": "Text"}], "quality": {"status": "usable", "reasons": []}}
    original_fragments = deepcopy(result["fragments"])
    OcrService().record_parse_result(result, update_readiness=False)
    assert parse_result_outcome_status(result) == ("partial" if limit == 2 else "completed")
    assert (CODE in parse_result_quality_blockers(result)) is (limit == 2)
    assert result["fragments"] == original_fragments
    if limit == 2:
        assert result["metadata"]["localRenderCoverage"]["unrenderedPageNos"] == [3, 4]
        before = deepcopy(result)
        attach_render_coverage(result)
        assert result == before


def test_native_text_on_unrendered_pages_cannot_hide_visual_gap_or_other_failure():
    result = {"status": "failed", "outcomeStatus": "failed", "quality": {"status": "failed", "reasons": ["other"]},
              "pages": [{"pageNo": 1, "totalPages": 2, "renderedPages": [1], "truncated": True},
                        {"pageNo": 2, "width": 100, "height": 100}]}
    attach_render_coverage(result)
    assert result["metadata"]["localRenderCoverage"]["unrenderedPageNos"] == [2]
    assert result["outcomeStatus"] == "failed"
    assert result["quality"]["status"] == "failed"
    assert result["quality"]["reasons"] == sorted([CODE, "other"])


def test_official_and_native_pages_without_render_truncation_are_unchanged():
    result = {"status": "success", "pages": [{"pageNo": 1}], "metadata": {"selectedPageNos": [1]}}
    before = deepcopy(result)
    attach_render_coverage(result)
    assert result == before


def test_readiness_exposes_missing_pages_instead_of_generic_missing_fields():
    from test_ocr_readiness import FakeRepo, document, parse_result

    from libs.ocr_readiness import build_document_ocr_readiness

    result = parse_result(fragments=[{"pageNo": 1, "text": "Text", "bbox": [0, 0, 10, 10]}])
    result["pages"] = [{"pageNo": 1, "totalPages": 28, "renderedPages": [1], "truncated": True}]
    attach_render_coverage(result)
    readiness = build_document_ocr_readiness(FakeRepo([result]), document())
    assert readiness["status"] == "incomplete"
    reason = readiness["blockingReasons"][0]
    assert reason["code"] == CODE
    assert reason["pageNos"] == list(range(2, 29))
    assert "第 2–28 页" in reason["message"]
    assert reason["actionKey"] == "review_ocr"
    assert "上传" not in reason["message"]
