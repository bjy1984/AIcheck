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


def approved_ocr_text(state: dict[str, Any], scope: dict[str, Any], *,
                      versions: list[str] | None = None) -> tuple[str, str]:
    """Return (status, whole OCR); never return a partial document as ready.

    `versions` 只取冻结范围内的一部分资料（逐份核对事实时用）；冻结的运行本身原样校验，
    不改写它的版本清单，页范围照旧生效。
    """
    frozen = [str(item) for item in scope.get("inputDocumentVersionIds") or [] if item]
    requested_order = frozen if versions is None else [str(item) for item in versions if item]
    requested = set(requested_order)
    if (not requested or len(requested) != len(requested_order) or len(set(frozen)) != len(frozen)
            or not requested <= set(frozen)):
        return "invalid_scope", ""
    try:
        # This validates that the requested version belongs to the project and
        # tenant before we inspect its OCR. Its formatted state is never sent.
        scoped_document_states(state, scope, [])
        parses = latest_selected_parses(state, scope, requested)
    except ValueError:
        return "invalid_scope", ""
    parts = []
    for index, version_id in enumerate(requested_order, 1):
        parse = parses.get(version_id)
        if not parse:
            attempts = sum(str(row.get("documentVersionId") or "") == version_id
                           for row in state.get("ocr_parse_results") or [] if isinstance(row, dict))
            return ("ambiguous_ocr_attempt" if attempts > 1 else "no_ocr_text"), ""
        if not ocr_parse_usable(parse):
            return "ocr_not_ready", ""
        text = _document_text(parse)
        if not text:
            return "no_ocr_text", ""
        parts.append(f"[资料 {index}]\n{text}" if len(requested_order) > 1 else text)
    text = "\n".join(parts)
    if len(text) > MAX_STATE_CHARS:
        return "overlong_document", ""
    return "ready", text
