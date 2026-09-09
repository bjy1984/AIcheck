import fitz
import pytest

from apps.ocr_service.engines import PyMuPdfTextLayerEngine
from apps.ocr_service.service import (
    OcrService,
    apply_business_pdf_deep_scan_default_options,
    normalize_ocr_result,
)
from libs.ocr.profiles import profile_for


@pytest.mark.parametrize("selection", [{"profile_id": "ndt_procedure_v1"}, {"document_type": "ndt_procedure"}])
def test_uploaded_ndt_pdf_reaches_visual_pipeline_by_default(tmp_path, monkeypatch, selection):
    source = tmp_path / "mixed.pdf"
    with fitz.open() as document:
        document.new_page()
        document.new_page().insert_text((50, 50), "Native body text")
        document.save(source)
    monkeypatch.setenv("AICHECK_OCR_ALLOWED_LOCAL_DIRS", str(tmp_path))
    service = OcrService()
    service.pipeline = None
    captured = {}

    def reject_fast_path(*args, **kwargs):
        raise AssertionError("NDT documents must reach visual parsing by default")

    def capture_visual(path, **kwargs):
        captured.update(kwargs)
        return {"status": "success", "storageKey": str(path), "fragments": [], "fields": [],
                "tables": [], "seals": [], "diagnostics": [], "metadata": {}}

    monkeypatch.setattr(service, "parse_pdf_text_layer_fast_path", reject_fast_path)
    monkeypatch.setattr(service, "parse_with_local_engines", capture_visual)
    service.parse_document(str(source), options={"disableResultCache": True}, **selection)
    assert captured["profile"]["profileId"] == "ndt_procedure_v1"
    assert captured["options"]["deepScanPdf"] is True
    assert captured["options"]["enableFallback"] is True
    assert captured["options"]["maxPages"] == 12  # Bounded attempt, not a whole-document coverage claim.


@pytest.mark.parametrize("options", [{"textLayerOnly": True}, {"preferTextLayer": True},
                                     {"disablePdfDeepScanDefault": True}, {"deepScanPdf": False}])
def test_ndt_explicit_parsing_preferences_are_preserved(options):
    assert apply_business_pdf_deep_scan_default_options(options, profile_for("ndt_procedure_v1"), suffix=".pdf") == options


@pytest.mark.parametrize("blank_page", [False, True])
def test_native_page_coverage_survives_normalization(tmp_path, blank_page):
    source = tmp_path / "native.pdf"
    with fitz.open() as document:
        document.new_page().insert_text((50, 50), "Text")
        if blank_page:
            document.new_page()
        document.save(source)
    raw = PyMuPdfTextLayerEngine().parse(source)
    result = normalize_ocr_result(raw, "local://native.pdf")
    coverage = result["metadata"]["nativeTextCoverage"]
    assert coverage["pagesWithText"] == [1]
    assert coverage["pagesWithoutText"] == ([2] if blank_page else [])
    assert coverage["visualOcrExecuted"] is False
    assert any(row["code"] == "PDF_TEXT_LAYER_PARTIAL" for row in result["diagnostics"]) is blank_page
