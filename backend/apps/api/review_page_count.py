"""Count pages from the authorized, fixed-version original; never fall back by filename."""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import fitz


def fixed_version_page_count(services, version: dict) -> int:
    local = services.local_storage_path(str(version.get("storageKey") or ""))
    if local and local.is_file():
        return _page_count(local)
    storage = services.project_document_storage_object(version)
    client = services.object_storage.client() if storage else None
    if not storage or client is None:
        raise ValueError("review_page_original_unavailable")
    response = client.get_object(*storage)
    try:
        with TemporaryDirectory(prefix="aicheck-review-pages-") as directory:
            path = Path(directory) / "original.pdf"
            with path.open("wb") as output:
                for chunk in response.stream(1024 * 1024):
                    output.write(chunk)
            return _page_count(path)
    finally:
        response.close()
        response.release_conn()


def _page_count(path: Path) -> int:
    with fitz.open(path) as document:
        if not document.is_pdf or document.needs_pass or document.page_count < 1:
            raise ValueError("review_page_original_requires_readable_pdf")
        return document.page_count
