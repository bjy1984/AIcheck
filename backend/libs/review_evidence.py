from __future__ import annotations

import hashlib
import json
from typing import Any

from libs.contracts.responses import server_time


def _stable_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _records(state: dict[str, Any], primary: str, fallback: str | None = None) -> list[dict[str, Any]]:
    rows = state.get(primary)
    if not isinstance(rows, list) and fallback:
        rows = state.get(fallback)
    return [row for row in rows or [] if isinstance(row, dict)]


def _latest_parse_result(
    state: dict[str, Any], document_version_id: str
) -> dict[str, Any] | None:
    rows = [
        row
        for row in _records(state, "ocr_parse_results")
        if str(row.get("documentVersionId") or "") == str(document_version_id)
    ]
    if not rows:
        return None
    rows.sort(
        key=lambda row: str(
            row.get("finishedAt")
            or row.get("updatedAt")
            or row.get("createdAt")
            or row.get("parseResultId")
            or row.get("id")
            or ""
        ),
        reverse=True,
    )
    return rows[0]


def active_node_document_versions(
    state: dict[str, Any], project_id: str, node_id: int
) -> list[dict[str, Any]]:
    documents = {
        str(row.get("id")): row
        for row in _records(state, "documents")
        if row.get("id") and str(row.get("projectId") or "") == str(project_id)
    }
    links = [
        row
        for row in _records(state, "node_evidence_links")
        if str(row.get("projectId") or "") == str(project_id)
        and int(row.get("nodeId") or 0) == int(node_id)
        and str(row.get("manualStatus") or "").strip().lower() != "rejected"
        and row.get("documentVersionId")
    ]

    active: dict[str, dict[str, Any]] = {}
    for link in links:
        document_id = str(link.get("documentId") or "")
        document = documents.get(document_id)
        if not document:
            continue
        linked_version_id = str(link.get("documentVersionId") or "")
        current_version_id = str(document.get("currentVersionId") or linked_version_id)
        if linked_version_id != current_version_id:
            continue
        entry = active.setdefault(
            current_version_id,
            {
                "documentId": document_id,
                "documentVersionId": current_version_id,
                "mountLinkIds": [],
                "mountRevision": 0,
            },
        )
        link_id = str(link.get("id") or "")
        if link_id and link_id not in entry["mountLinkIds"]:
            entry["mountLinkIds"].append(link_id)
        entry["mountRevision"] = max(
            int(entry.get("mountRevision") or 0),
            int(link.get("revision") or 0),
        )

    for entry in active.values():
        entry["mountLinkIds"].sort()
    return sorted(active.values(), key=lambda row: row["documentVersionId"])


def _enrich_document_versions(
    state: dict[str, Any], active_versions: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    versions = {
        str(row.get("id")): row
        for row in _records(state, "document_versions", "versions")
        if row.get("id")
    }
    enriched: list[dict[str, Any]] = []
    for active in active_versions:
        version_id = str(active["documentVersionId"])
        version = versions.get(version_id) or {}
        parse_result = _latest_parse_result(state, version_id)
        ocr_hash = None
        parse_result_id = None
        if parse_result:
            parse_result_id = parse_result.get("parseResultId") or parse_result.get("id")
            ocr_hash = (
                parse_result.get("artifactHash")
                or parse_result.get("contentHash")
                or parse_result.get("outputHash")
                or _stable_hash(parse_result)
            )
        enriched.append(
            {
                **active,
                "documentContentHash": (
                    version.get("contentHash")
                    or version.get("sha256")
                    or version.get("checksum")
                    or _stable_hash(version)
                ),
                "ocrParseResultId": parse_result_id,
                "ocrContentHash": ocr_hash,
            }
        )
    return enriched


def build_evidence_snapshot(
    state: dict[str, Any],
    project_id: str,
    node_id: int,
    *,
    rule_version: str,
    clause_package_version: str,
    prompt_version: str,
    strategy_version: str,
) -> dict[str, Any]:
    document_versions = _enrich_document_versions(
        state,
        active_node_document_versions(state, project_id, node_id),
    )
    hash_payload = {
        "projectId": str(project_id),
        "nodeId": int(node_id),
        "documentVersions": document_versions,
        "ruleVersion": str(rule_version),
        "clausePackageVersion": str(clause_package_version),
        "promptVersion": str(prompt_version),
        "strategyVersion": str(strategy_version),
    }
    snapshot_hash = _stable_hash(hash_payload)
    return {
        "evidenceSnapshotId": f"ESNAP-{snapshot_hash.removeprefix('sha256:')[:16].upper()}",
        **hash_payload,
        "documentVersionCount": len(document_versions),
        "snapshotHash": snapshot_hash,
        "createdAt": server_time(),
    }
