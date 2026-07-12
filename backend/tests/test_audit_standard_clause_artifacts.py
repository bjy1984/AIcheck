from __future__ import annotations

from pathlib import Path

import fitz

from scripts import audit_standard_clause_artifacts as artifact_audit


def test_pdf_page_count_falls_back_to_pymupdf(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "sample.pdf"
    document = fitz.open()
    document.new_page()
    document.new_page()
    document.save(source)
    document.close()
    monkeypatch.setattr(artifact_audit.shutil, "which", lambda _name: None)

    assert artifact_audit.pdf_page_count(source) == 2
