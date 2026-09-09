"""Freeze the input version IDs; shard selections may narrow context, never the run."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from libs.review_rule_snapshot import _hash


def freeze_document_scope(run: dict[str, Any]) -> dict[str, Any]:
    versions = run.get("inputDocumentVersionIds", [])
    if not isinstance(versions, list) or any(not isinstance(item, str) or not item for item in versions):
        raise ValueError("invalid_document_scope_versions")
    snapshot = {
        "schemaVersion": "review-document-scope-v1",
        "projectId": run.get("projectId"), "nodeId": run.get("nodeId"),
        "businessPackId": run.get("businessPackId"),
        "documentVersionIds": deepcopy(versions),
    }
    snapshot["snapshotHash"] = _hash(snapshot)
    return snapshot


def validate_document_scope(run: dict[str, Any]) -> None:
    snapshot = run.get("documentScopeSnapshot")
    if snapshot is None:
        return  # Historical runs retain their original contract.
    if not isinstance(snapshot, dict) or snapshot.get("schemaVersion") != "review-document-scope-v1":
        raise ValueError("invalid_document_scope_snapshot")
    if snapshot.get("snapshotHash") != _hash({key: value for key, value in snapshot.items() if key != "snapshotHash"}):
        raise ValueError("document_scope_hash_mismatch")
    if any(snapshot.get(key) != run.get(key) for key in ("projectId", "nodeId", "businessPackId")):
        raise ValueError("document_scope_identity_mismatch")
    if snapshot.get("documentVersionIds") != (run.get("inputDocumentVersionIds") or []):
        raise ValueError("document_scope_versions_mismatch")
