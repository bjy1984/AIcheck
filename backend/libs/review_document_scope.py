"""Freeze the input version IDs; shard selections may narrow context, never the run."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from libs.review_page_scope import normalize_page_ranges
from libs.review_rule_snapshot import _hash


def freeze_document_scope(run: dict[str, Any], state: dict[str, Any] | None = None) -> dict[str, Any]:
    versions = run.get("inputDocumentVersionIds", [])
    if not isinstance(versions, list) or any(not isinstance(item, str) or not item for item in versions):
        raise ValueError("invalid_document_scope_versions")
    snapshot = {
        "schemaVersion": "review-document-scope-v1",
        "projectId": run.get("projectId"), "nodeId": run.get("nodeId"),
        "businessPackId": run.get("businessPackId"),
        "documentVersionIds": deepcopy(versions),
    }
    if "inputDocumentPageRanges" in run:
        snapshot["documentPageRanges"] = normalize_page_ranges(run["inputDocumentPageRanges"], versions)
    if state is not None:
        snapshot["sourceFingerprint"] = document_source_fingerprint(run, state)
    snapshot["snapshotHash"] = _hash(snapshot)
    return snapshot


def validate_document_scope(run: dict[str, Any]) -> None:
    snapshot = run.get("documentScopeSnapshot")
    if snapshot is None:
        if run.get("inputDocumentPageRanges"):
            raise ValueError("document_page_scope_snapshot_required")
        return  # Historical runs retain their original contract.
    if not isinstance(snapshot, dict) or snapshot.get("schemaVersion") != "review-document-scope-v1":
        raise ValueError("invalid_document_scope_snapshot")
    if snapshot.get("snapshotHash") != _hash({key: value for key, value in snapshot.items() if key != "snapshotHash"}):
        raise ValueError("document_scope_hash_mismatch")
    if any(snapshot.get(key) != run.get(key) for key in ("projectId", "nodeId", "businessPackId")):
        raise ValueError("document_scope_identity_mismatch")
    if snapshot.get("documentVersionIds") != (run.get("inputDocumentVersionIds") or []):
        raise ValueError("document_scope_versions_mismatch")
    ranges = normalize_page_ranges(run.get("inputDocumentPageRanges", {}), run.get("inputDocumentVersionIds") or [])
    if snapshot.get("documentPageRanges", {}) != ranges:
        raise ValueError("document_scope_pages_mismatch")


def document_source_fingerprint(run: dict[str, Any], state: dict[str, Any]) -> str:
    allowed = set(run.get("inputDocumentVersionIds") or [])
    parses = [row for row in state.get("ocr_parse_results", [])
              if isinstance(row, dict) and row.get("documentVersionId") in allowed]
    corrections = [row for row in state.get("fact_corrections", [])
                   if isinstance(row, dict) and row.get("documentVersionId") in allowed
                   and row.get("projectId") == run.get("projectId")
                   and str(row.get("nodeId")) == str(run.get("nodeId"))
                   and row.get("status") == "active"
                   and (row.get("fieldId") or (run.get("inputDocumentPageRanges") and row.get("factPath")))]
    # Preserve order: the existing correction reader uses the last matching value.
    sources = {"parses": parses, "corrections": corrections}
    if run.get("inputDocumentPageRanges"):
        # Scoped model grounding also reads these independent evidence stores.
        for key in ("extracted_fields", "evidence_links"):
            sources[key] = [row for row in state.get(key, [])
                            if isinstance(row, dict) and row.get("documentVersionId") in allowed]
    return _hash(sources)


def validate_document_sources(run: dict[str, Any], state: dict[str, Any]) -> None:
    validate_document_scope(run)
    snapshot = run.get("documentScopeSnapshot") or {}
    expected = snapshot.get("sourceFingerprint")
    if expected is not None and expected != document_source_fingerprint(run, state):
        raise ValueError("review_document_sources_changed_recreate_run")


def ensure_document_sources(run: dict[str, Any], state: dict[str, Any]) -> None:
    """Expose a stable non-retryable workflow error without document contents."""
    from libs.integrations.errors import IntegrationServiceError

    try:
        validate_document_sources(run, state)
    except ValueError as exc:
        raise IntegrationServiceError("review", "validate_inputs", status_code=409,
                                      reason="REVIEW_INPUT_CHANGED_RECREATE_RUN") from exc
