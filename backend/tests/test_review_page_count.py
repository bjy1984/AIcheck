from types import SimpleNamespace

import fitz
import pytest

from apps.api.review_page_count import fixed_version_page_count


def test_page_count_uses_fixed_original_not_ocr_or_current_filename(tmp_path):
    original = tmp_path / "fixed.pdf"
    with fitz.open() as pdf:
        for _ in range(4):
            pdf.new_page()
        pdf.save(original)
    services = SimpleNamespace(local_storage_path=lambda key: original if key == "fixed" else None,
                               project_document_storage_object=lambda version: None)
    assert fixed_version_page_count(services, {"storageKey": "fixed", "pageCount": 900}) == 4
    with pytest.raises(ValueError, match="unavailable"):
        fixed_version_page_count(services, {"storageKey": "missing", "fileName": "fixed.pdf"})


def test_remote_stream_is_closed_and_temporary_file_removed(tmp_path):
    with fitz.open() as pdf:
        pdf.new_page()
        contents = pdf.tobytes()
    events = []
    response = SimpleNamespace(stream=lambda _: iter([contents[:50], contents[50:]]),
                               close=lambda: events.append("close"), release_conn=lambda: events.append("release"))
    services = SimpleNamespace(local_storage_path=lambda _: None,
                               project_document_storage_object=lambda _: ("bucket", "version-object"),
                               object_storage=SimpleNamespace(client=lambda: SimpleNamespace(get_object=lambda *args: response)))
    assert fixed_version_page_count(services, {"storageKey": "version-object"}) == 1
    assert events == ["close", "release"]
    events.clear()
    response.stream = lambda _: iter([b"not a pdf"])
    with pytest.raises(fitz.FileDataError):
        fixed_version_page_count(services, {"storageKey": "version-object"})
    assert events == ["close", "release"]
