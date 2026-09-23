"""OCR-only outbound text for approved Jev evaluations.

Document/project identifiers and rule results stay local. The text is selected
through the same frozen-version, page-range and correction rules as review OCR.
"""

from __future__ import annotations

from typing import Any

from libs.review_input_data import latest_selected_parses, ocr_parse_usable
from libs.review_orchestrator.jev_state import (
    MAX_STATE_CHARS,
    _document_text,
    scoped_document_states,
)


def approved_ocr_text(state: dict[str, Any], scope: dict[str, Any]) -> tuple[str, str]:
    """Return (status, whole OCR); never return a partial document as ready."""
    requested = {str(item) for item in scope.get("inputDocumentVersionIds") or [] if item}
    if len(requested) != 1:
        return "invalid_scope", ""
    try:
        # This validates that the requested version belongs to the project and
        # tenant before we inspect its OCR. Its formatted state is never sent.
        scoped_document_states(state, scope, [])
        parse = latest_selected_parses(state, scope, requested).get(next(iter(requested)))
    except ValueError:
        return "invalid_scope", ""
    if not parse:
        return "no_ocr_text", ""
    if not ocr_parse_usable(parse):
        return "ocr_not_ready", ""
    text = _document_text(parse)
    if not text:
        return "no_ocr_text", ""
    if len(text) > MAX_STATE_CHARS:
        return "overlong_document", ""
    return "ready", text
