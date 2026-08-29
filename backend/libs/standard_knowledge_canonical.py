"""Canonical standard-knowledge identity and field selection helpers."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any


CANONICAL_VERSION = "standard-knowledge-canonical@1"
SOURCE_PRIORITY = {
    "new_mineru": 500,
    "visual_extraction": 400,
    "standard_catalog": 300,
    "legacy_ocr": 200,
    "filename_inference": 100,
}


def canonical_item_id(kind: str, identity: list[object]) -> str:
    normalized = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:20].upper()
    return f"SKI-{kind.upper()}-{digest}"


def select_canonical_field(key: str, candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    usable = [item for item in candidates if str(item.get("value") or "").strip()]
    if not usable:
        return None
    ordered = sorted(
        usable,
        key=lambda item: (
            SOURCE_PRIORITY.get(str(item.get("sourceType") or ""), 0),
            str(item.get("createdAt") or ""),
        ),
        reverse=True,
    )
    selected = ordered[0]
    return {
        "id": canonical_item_id("field", [key]),
        "key": key,
        "value": selected["value"],
        "authority": "legacy_only" if selected.get("sourceType") == "legacy_ocr" else "current",
        "selectedSourceId": selected.get("sourceId"),
        "sources": ordered,
    }


def collect_standard_sources(state: dict[str, Any], file_id: str, repo_root: Path) -> dict[str, Any]:
    file = _one(state.get("knowledge_files", []), id=file_id)
    if not file or file.get("sourceId") != "KS-STANDARD-RULES":
        raise ValueError(f"not a standard knowledge file: {file_id}")
    document = _one(state.get("documents", []), id=file.get("documentId"))
    version = _one(state.get("versions", []), id=(document or {}).get("currentVersionId"))
    if (
        not document
        or not version
        or version.get("documentId") != document.get("id")
        or file.get("documentVersionId") != version.get("id")
    ):
        raise ValueError(f"standard document/version relationship invalid: {file_id}")
    parses = [item for item in state.get("ocr_parse_results", []) if item.get("documentVersionId") == version["id"]]
    new_parse = max(
        [item for item in parses if (item.get("metadata") or {}).get("sidecarImported")],
        key=lambda item: str(item.get("finishedAt") or item.get("createdAt") or ""),
        default=None,
    )
    legacy_parses = [item for item in parses if item is not new_parse]
    return {
        "file": copy.deepcopy(file),
        "document": copy.deepcopy(document),
        "version": copy.deepcopy(version),
        "newParse": copy.deepcopy(new_parse),
        "legacyParses": copy.deepcopy(legacy_parses),
        "legacyFields": _by_version(state.get("extracted_fields", []), version["id"]),
        "legacyEvidence": _by_version(state.get("evidence_links", []), version["id"]),
        "visualExtraction": _read_optional_json(repo_root / "backend/data/visual_extractions" / f"{file_id}.json"),
        "legacyRuleSidecar": _read_optional_json(repo_root / "backend/data/rules_ocr_sidecars" / f"{file_id}.json"),
        "chunks": _by_file(state.get("knowledge_chunks", []), file_id),
        "clauses": _by_file(state.get("knowledge_clauses", []), file_id),
        "pageIndexNodes": _page_nodes_for_path(state, file.get("sourceRelativePath")),
        "standardVersions": _by_file(state.get("standard_document_versions", []), file_id),
        "clauseReferences": _by_file(state.get("standard_clause_references", []), file_id),
        "clauseLocators": _by_file(state.get("standard_clause_locators", []), file_id),
        "catalogItems": _catalog_items_for_file(state, file),
        "ruleReferences": _rule_references_for_file(state, file),
    }


def _one(items: list[dict[str, Any]], **match: Any) -> dict[str, Any] | None:
    return next((item for item in items if all(item.get(key) == value for key, value in match.items())), None)


def _by_version(items: list[dict[str, Any]], version_id: str) -> list[dict[str, Any]]:
    return copy.deepcopy([item for item in items if item.get("documentVersionId") == version_id])


def _by_file(items: list[dict[str, Any]], file_id: str) -> list[dict[str, Any]]:
    return copy.deepcopy([
        item for item in items
        if (
            item.get("fileId") == file_id
            or item.get("knowledgeFileId") == file_id
            or (item.get("scope") or {}).get("fileId") == file_id
        )
    ])


def _read_optional_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _page_nodes_for_path(state: dict[str, Any], source_path: str | None) -> list[dict[str, Any]]:
    normalized = str(source_path or "").replace("\\", "/").lstrip("./")
    return copy.deepcopy([
        item for item in state.get("knowledge_page_index_nodes", [])
        if str(item.get("sourceRelativePath") or "").replace("\\", "/").lstrip("./") == normalized
    ])


def _catalog_items_for_file(state: dict[str, Any], file: dict[str, Any]) -> list[dict[str, Any]]:
    file_name = str(file.get("fileName") or "")
    result = []
    for pack in state.get("business_packs", []):
        for item in pack.get("standardCatalog") or []:
            if item.get("knowledgeFileId") == file["id"] or str(item.get("fileName") or "") == file_name:
                result.append({**copy.deepcopy(item), "businessPackId": pack.get("id")})
    return result


def _rule_references_for_file(state: dict[str, Any], file: dict[str, Any]) -> list[dict[str, Any]]:
    file_name = str(file.get("fileName") or "")
    result = []
    for rule in state.get("rule_versions", []):
        for reference in rule.get("referencedStandards") or []:
            if reference.get("knowledgeFileId") == file["id"] or str(reference.get("fileName") or "") == file_name:
                result.append({**copy.deepcopy(reference), "ruleId": rule.get("id"), "nodeIds": list(rule.get("nodeIds") or [])})
    return result
