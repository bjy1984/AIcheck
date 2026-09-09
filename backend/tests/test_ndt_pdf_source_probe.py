import json

import fitz

from scripts.probe_ndt_pdf_sources import main, probe_pdf


def test_native_pdf_probe_exposes_unread_pages_and_does_not_invent_identity(tmp_path):
    path = tmp_path / "PT-PROC-01-version-A.pdf"
    with fitz.open() as document:
        document.new_page()  # Empty or scanned-only pages cannot be claimed as extracted.
        document.new_page().insert_text((50, 50), "NDT sample without explicit identity labels")
        document.save(path)
    result = probe_pdf(path)
    assert result["pageCount"] == 2
    assert result["pagesWithoutText"] == [1]
    assert result["pagesWithText"] == [2]
    assert "procedure_no" in result["missingRequiredFields"]
    assert "procedure_revision" in result["missingRequiredFields"]
    assert result["businessAcceptance"] == "not_evaluated"
    assert result["visualOcrExecuted"] is False
    assert result["profileSelection"] == "explicit_probe_override"
    assert any(item["code"] == "PDF_TEXT_LAYER_PARTIAL" and item["pageNos"] == [1]
               for item in result["diagnostics"])
    assert probe_pdf(path)["sha256"] == result["sha256"]


def test_probe_batch_retains_readable_files_and_returns_failure_for_missing_input(tmp_path, monkeypatch):
    path = tmp_path / "readable.pdf"
    with fitz.open() as document:
        document.new_page()
        document.save(path)
    output = tmp_path / "reports" / "probe.json"
    monkeypatch.setattr("sys.argv", ["probe", str(tmp_path / "missing.pdf"), str(path), "--output", str(output)])
    assert main() == 1
    reports = json.loads(output.read_text())["documents"]
    assert reports[0]["errorType"] == "FileNotFoundError"
    assert reports[1]["pagesWithoutText"] == [1]
    assert reports[1]["businessAcceptance"] == "not_evaluated"
