"""Canonical standard-knowledge identity and field selection helpers."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


CANONICAL_VERSION = "standard-knowledge-canonical@1"
SOURCE_PRIORITY = {
    "new_mineru_semantic": 550,
    "new_mineru": 500,
    "visual_extraction": 400,
    "standard_catalog": 300,
    "legacy_ocr": 200,
    "filename_inference": 100,
}

REQUIRED_CATEGORIES = (
    "identity",
    "version",
    "metadata",
    "fullText",
    "sections",
    "clauses",
    "tables",
    "equations",
    "images",
    "seals",
    "normativeReferences",
    "replacementRelations",
    "businessRelations",
    "evidenceLocation",
    "history",
)

_FIELD_ALIASES = {
    "standardCode": "standardCode",
    "标准编号": "standardCode",
    "标准号": "standardCode",
    "standardNameZh": "standardNameZh",
    "标准名称": "standardNameZh",
    "中文名称": "standardNameZh",
    "standardNameEn": "standardNameEn",
    "英文名称": "standardNameEn",
    "standardType": "standardType",
    "标准类型": "standardType",
    "partNumber": "partNumber",
    "部分编号": "partNumber",
    "icsCode": "icsCode",
    "ICS分类号": "icsCode",
    "ccsCode": "ccsCode",
    "中国标准分类号": "ccsCode",
    "filingNumber": "filingNumber",
    "备案号": "filingNumber",
    "edition": "edition",
    "版本": "edition",
    "publicationDate": "publicationDate",
    "发布日期": "publicationDate",
    "effectiveDate": "effectiveDate",
    "实施日期": "effectiveDate",
    "issuingAuthority": "issuingAuthority",
    "发布机构": "issuingAuthority",
    "proposingOrganization": "proposingOrganization",
    "提出单位": "proposingOrganization",
    "administeringOrganization": "administeringOrganization",
    "归口单位": "administeringOrganization",
    "draftingOrganizations": "draftingOrganizations",
    "起草单位": "draftingOrganizations",
    "draftingPeople": "draftingPeople",
    "起草人": "draftingPeople",
    "status": "status",
    "状态": "status",
    "scope": "scope",
    "范围": "scope",
    "purpose": "purpose",
    "目的": "purpose",
    "applicability": "applicability",
    "适用范围": "applicability",
    "keywords": "keywords",
    "关键词": "keywords",
    "abstract": "abstract",
    "摘要": "abstract",
    "foreword": "foreword",
    "前言": "foreword",
    "introduction": "introduction",
    "引言": "introduction",
    "language": "language",
    "语言": "language",
    "pageCount": "pageCount",
    "页数": "pageCount",
}

_IDENTITY_FIELDS = {
    "standardCode",
    "standardNameZh",
    "standardNameEn",
    "standardType",
    "partNumber",
    "icsCode",
    "ccsCode",
    "filingNumber",
    "sourceFileName",
    "sourceRelativePath",
}
_VERSION_FIELDS = {
    "edition",
    "publicationDate",
    "effectiveDate",
    "issuingAuthority",
    "proposingOrganization",
    "administeringOrganization",
    "draftingOrganizations",
    "draftingPeople",
    "status",
    "replaces",
    "replacedBy",
    "amendments",
    "releaseId",
    "businessPackVersion",
}
_METADATA_FIELDS = {
    "scope",
    "purpose",
    "applicability",
    "keywords",
    "abstract",
    "foreword",
    "introduction",
    "termsAndDefinitionsSummary",
    "requiredCapabilities",
    "language",
    "pageCount",
}
_CLAUSE_NUMBER = re.compile(r"^\s*([A-Z]?\d+(?:\.\d+)*)\s+")
_CONTEXT_ONLY_CATEGORIES = (
    "sections",
    "clauses",
    "tables",
    "equations",
    "images",
    "seals",
    "normativeReferences",
    "replacementRelations",
    "evidenceLocation",
)


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


def normalized_content_hash(item: dict[str, Any]) -> str:
    content = next(
        (item[key] for key in ("normalizedRows", "latex", "text", "caption") if item.get(key)),
        None,
    )
    if content is None and ("value" in item or "quotedText" in item):
        content = {"value": item.get("value"), "quotedText": item.get("quotedText")}
    normalized_content = _normalize_content_whitespace(content if content is not None else "")
    normalized = json.dumps(
        normalized_content,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _normalize_content_whitespace(value: Any) -> Any:
    if isinstance(value, str):
        return re.sub(r"\s+", " ", value).strip()
    if isinstance(value, list):
        return [_normalize_content_whitespace(item) for item in value]
    if isinstance(value, tuple):
        return [_normalize_content_whitespace(item) for item in value]
    if isinstance(value, dict):
        return {key: _normalize_content_whitespace(item) for key, item in value.items()}
    return value


def normalize_bbox(value: Any) -> list[float] | None:
    if not isinstance(value, (list, tuple)) or len(value) < 4:
        return None
    if all(isinstance(part, (list, tuple)) and len(part) >= 2 for part in value):
        try:
            xs = [float(part[0]) for part in value]
            ys = [float(part[1]) for part in value]
        except (TypeError, ValueError):
            return None
        bbox = [min(xs), min(ys), max(xs), max(ys)]
    else:
        try:
            bbox = [float(part) for part in value[:4]]
        except (TypeError, ValueError):
            return None
    return bbox if bbox[2] > bbox[0] and bbox[3] > bbox[1] else None


def canonical_evidence(item: dict[str, Any], *, authority: str) -> dict[str, Any]:
    return {
        "sourceType": str(item.get("sourceType") or ""),
        "sourceId": str(item.get("sourceId") or ""),
        "parseResultId": item.get("parseResultId"),
        "documentVersionId": str(item.get("documentVersionId") or ""),
        "pageNo": item.get("pageNo"),
        "bbox": normalize_bbox(item.get("bbox")),
        "quotedText": str(item.get("quotedText") or item.get("text") or item.get("value") or ""),
        "confidence": item.get("confidence"),
        "needsHumanVerification": bool(item.get("needsHumanVerification")),
        "authority": authority,
        "contentHash": normalized_content_hash(item),
    }


def canonical_public_content(kind: str, item: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "title",
        "text",
        "clauseNo",
        "sectionPath",
        "pageNo",
        "bbox",
        "caption",
        "columnNames",
        "normalizedRows",
        "cells",
        "headerReliable",
        "latex",
        "sourceStandardCode",
        "sourceClauseNo",
        "targetStandardCode",
        "targetClauseNo",
        "nodeIds",
        "materialTypes",
        "purpose",
        "locatorIds",
    }
    result = {key: copy.deepcopy(value) for key, value in item.items() if key in allowed}
    if "bbox" in result:
        result["bbox"] = normalize_bbox(result["bbox"])
    return result


def structured_identity(kind: str, item: dict[str, Any]) -> str:
    if kind == "clause" and item.get("clauseNo"):
        identity = [item.get("standardCode"), item.get("edition"), item.get("clauseNo")]
    elif kind == "reference":
        identity = [
            str(item.get("sourceStandardCode") or ""),
            str(item.get("sourceClauseNo") or ""),
            str(item.get("targetStandardCode") or ""),
            str(item.get("targetClauseNo") or ""),
        ]
    elif kind == "replacement":
        identity = [
            item.get("sourceStandardCode"),
            item.get("targetStandardCode"),
            item.get("purpose"),
        ]
    else:
        identity = [
            kind,
            item.get("pageNo"),
            normalized_content_hash(item),
            normalize_bbox(item.get("bbox")),
            item.get("sectionPath") if kind == "clause" else None,
        ]
    return canonical_item_id(kind, identity)


def select_structured_item(
    kind: str, identity: str, values: list[dict[str, Any]]
) -> dict[str, Any]:
    ordered = sorted(
        values,
        key=lambda item: (
            SOURCE_PRIORITY.get(str(item.get("sourceType") or ""), 0),
            str(item.get("createdAt") or ""),
            str(item.get("sourceId") or ""),
        ),
        reverse=True,
    )
    selected = ordered[0]
    authority = "legacy_only" if selected.get("sourceType") == "legacy_ocr" else "current"
    public_content = canonical_public_content(kind, selected)
    selected_location = _canonical_location(selected)
    if selected_location and selected_location["bbox"]:
        location = selected_location
    else:
        location = next(
            (
                candidate
                for item in ordered
                if (candidate := _canonical_location(item)) and candidate["bbox"]
            ),
            None,
        )
        if location is None:
            location = next(
                (
                    candidate
                    for item in ordered
                    if (candidate := _canonical_location(item)) and candidate["locatorIds"]
                ),
                selected_location,
            )
        if location is None:
            location = next(
                (candidate for item in ordered if (candidate := _canonical_location(item))),
                None,
            )
    if location:
        public_content["pageNo"] = location["pageNo"]
        public_content["bbox"] = location["bbox"]
        if location["locatorIds"]:
            public_content["locatorIds"] = location["locatorIds"]
        else:
            public_content.pop("locatorIds", None)
    return {
        **public_content,
        "id": identity,
        "authority": authority,
        "selectedSourceId": selected.get("sourceId"),
        "sources": [
            canonical_evidence(item, authority="supporting" if item is not selected else authority)
            for item in ordered
        ],
    }


def _canonical_location(item: dict[str, Any]) -> dict[str, Any] | None:
    page_no = item.get("pageNo")
    if not page_no:
        return None
    locator_ids = [str(value) for value in item.get("locatorIds") or [] if str(value or "")]
    return {
        "pageNo": page_no,
        "bbox": normalize_bbox(item.get("bbox")),
        "locatorIds": locator_ids,
        "sourceId": str(item.get("sourceId") or ""),
    }


def merge_structured_items(kind: str, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in candidates:
        identity = structured_identity(kind, item)
        grouped.setdefault(identity, []).append(item)
    return [
        select_structured_item(kind, identity, values)
        for identity, values in sorted(grouped.items())
    ]


def require_keys(values: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    missing = [key for key in keys if not str((values.get(key) or {}).get("value") or "").strip()]
    return {"status": "complete" if not missing else "partial", "missing": missing}


def list_status(values: list[Any]) -> dict[str, Any]:
    return {"status": "complete" if values else "missing", "count": len(values)}


def applicable_list_status(
    values: list[Any], provenance: list[dict[str, Any]], capability: str
) -> dict[str, Any]:
    attempted = any(capability in set(item.get("capabilities") or []) for item in provenance)
    if values:
        return {"status": "complete", "count": len(values)}
    return {"status": "missing" if attempted else "not_applicable", "count": 0}


def evidence_location_status(record: dict[str, Any]) -> dict[str, Any]:
    items = [
        *record.get("clauses", []),
        *record.get("tables", []),
        *record.get("equations", []),
        *record.get("images", []),
        *record.get("seals", []),
    ]
    if not items:
        return {"status": "missing", "located": 0, "total": 0}
    located = len(
        [
            item
            for item in items
            if item.get("pageNo") and (item.get("bbox") or item.get("locatorIds"))
        ]
    )
    return {
        "status": "complete" if located == len(items) else "partial",
        "located": located,
        "total": len(items),
    }


def canonical_completeness(record: dict[str, Any]) -> dict[str, Any]:
    provenance = list(record.get("provenance") or [])
    categories = {
        "identity": require_keys(record.get("identity") or {}, ("standardCode", "standardNameZh")),
        "version": require_keys(record.get("version") or {}, ("status",)),
        "metadata": require_keys(record.get("metadata") or {}, ("scope",)),
        "fullText": list_status(list(record.get("blocks") or [])),
        "sections": list_status(list(record.get("sections") or [])),
        "clauses": list_status(list(record.get("clauses") or [])),
        "tables": applicable_list_status(list(record.get("tables") or []), provenance, "table"),
        "equations": applicable_list_status(
            list(record.get("equations") or []), provenance, "equation"
        ),
        "images": applicable_list_status(list(record.get("images") or []), provenance, "image"),
        "seals": applicable_list_status(list(record.get("seals") or []), provenance, "seal"),
        "normativeReferences": list_status(list(record.get("normativeReferences") or [])),
        "replacementRelations": applicable_list_status(
            list(record.get("replacementRelations") or []), provenance, "replacement"
        ),
        "businessRelations": list_status(list(record.get("businessRelations") or [])),
        "evidenceLocation": evidence_location_status(record),
        "history": list_status(list(record.get("history") or [])),
    }
    if record.get("contextType") == "context_only":
        for key in _CONTEXT_ONLY_CATEGORIES:
            if key == "evidenceLocation":
                categories[key] = {"status": "not_applicable", "located": 0, "total": 0}
            else:
                categories[key] = {
                    "status": "not_applicable",
                    "count": len(record.get(key) or []),
                }
    missing = [key for key, item in categories.items() if item["status"] in {"missing", "partial"}]
    return {
        **categories,
        "overall": "complete" if not missing else "partial",
        "missingCategories": missing,
    }


def collect_standard_sources(
    state: dict[str, Any], file_id: str, repo_root: Path
) -> dict[str, Any]:
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
    parses = [
        item
        for item in state.get("ocr_parse_results", [])
        if item.get("documentVersionId") == version["id"]
    ]
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
        "visualExtraction": _read_optional_json(
            repo_root / "backend/data/visual_extractions" / f"{file_id}.json"
        ),
        "legacyRuleSidecar": _read_optional_json(
            repo_root / "backend/data/rules_ocr_sidecars" / f"{file_id}.json"
        ),
        "chunks": _by_file(state.get("knowledge_chunks", []), file_id),
        "clauses": _by_file(state.get("knowledge_clauses", []), file_id),
        "pageIndexNodes": _page_nodes_for_path(state, file.get("sourceRelativePath")),
        "standardVersions": _by_file(state.get("standard_document_versions", []), file_id),
        "clauseReferences": _by_file(state.get("standard_clause_references", []), file_id),
        "clauseLocators": _by_file(state.get("standard_clause_locators", []), file_id),
        "catalogItems": _catalog_items_for_file(state, file),
        "ruleReferences": _rule_references_for_file(state, file),
    }


def build_standard_knowledge_record(
    state: dict[str, Any], file_id: str, repo_root: Path
) -> dict[str, Any]:
    sources = collect_standard_sources(state, file_id, repo_root)
    field_candidates = _canonical_field_candidates(sources)
    fields = {
        key: selected
        for key, candidates in field_candidates.items()
        if (selected := select_canonical_field(key, candidates)) is not None
    }
    identity = {key: fields[key] for key in _IDENTITY_FIELDS if key in fields}
    version = {key: fields[key] for key in _VERSION_FIELDS if key in fields}
    metadata = {key: fields[key] for key in _METADATA_FIELDS if key in fields}
    standard_code = str((identity.get("standardCode") or {}).get("value") or "")
    edition = str((version.get("edition") or {}).get("value") or "")

    candidates, provenance, history = _canonical_structure_candidates(
        sources,
        standard_code=standard_code,
        edition=edition,
    )
    kb_version = _standard_kb_version(state, sources["file"])
    context_type = (
        "context_only"
        if sources["file"].get("contextType") == "business_rule_context"
        else str(sources["file"].get("contextType") or "standard_reference")
    )
    record: dict[str, Any] = {
        "id": f"SKR-{file_id}",
        "knowledgeFileId": file_id,
        "documentId": sources["document"]["id"],
        "documentVersionId": sources["version"]["id"],
        "canonicalVersion": CANONICAL_VERSION,
        "kbVersion": kb_version,
        "activeParseResultId": (sources.get("newParse") or {}).get("parseResultId")
        or (sources.get("newParse") or {}).get("id"),
        "contextType": context_type,
        "identity": identity,
        "version": version,
        "metadata": metadata,
        "sections": merge_structured_items("section", candidates["sections"]),
        "clauses": merge_structured_items("clause", candidates["clauses"]),
        "blocks": merge_structured_items("block", candidates["blocks"]),
        "tables": merge_structured_items("table", candidates["tables"]),
        "equations": merge_structured_items("equation", candidates["equations"]),
        "images": merge_structured_items("image", candidates["images"]),
        "seals": merge_structured_items("seal", candidates["seals"]),
        "normativeReferences": merge_structured_items(
            "reference", candidates["normativeReferences"]
        ),
        "replacementRelations": merge_structured_items(
            "replacement", candidates["replacementRelations"]
        ),
        "businessRelations": merge_structured_items("business", candidates["businessRelations"]),
        "evidence": [],
        "provenance": provenance,
        "history": history,
        "sourceFingerprint": _source_fingerprint({**sources, "kbVersion": kb_version}),
        "generatedAt": datetime.now(UTC).isoformat(),
    }
    record["evidence"] = _record_evidence(record)
    record["completeness"] = canonical_completeness(record)
    return record


def _existing_structured_candidates(
    kind: str, values: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for value in values:
        if not isinstance(value, dict):
            continue
        public_content = canonical_public_content(kind, value)
        for source in value.get("sources") or []:
            if not isinstance(source, dict):
                continue
            candidate = {**copy.deepcopy(public_content), **copy.deepcopy(source)}
            candidate.setdefault("text", str(source.get("quotedText") or ""))
            candidates.append(candidate)
    return candidates


def _semantic_capabilities(semantics: dict[str, Any]) -> list[str]:
    capabilities: set[str] = set()
    if any(key in semantics for key in _IDENTITY_FIELDS):
        capabilities.add("identity")
    if any(key in semantics for key in _VERSION_FIELDS):
        capabilities.add("version")
    if any(key in semantics for key in _METADATA_FIELDS):
        capabilities.add("metadata")
    if "normativeReferences" in semantics:
        capabilities.add("reference")
    if "replacementRelations" in semantics:
        capabilities.add("replacement")
    return sorted(capabilities)


def merge_canonical_semantic_candidates(
    record: dict[str, Any],
    semantics: dict[str, Any],
    *,
    extracted_at: str,
) -> dict[str, Any]:
    """Merge grounded semantic candidates through the canonical selectors."""
    enriched = copy.deepcopy(record)
    for group_name, keys in (
        ("identity", _IDENTITY_FIELDS),
        ("version", _VERSION_FIELDS),
        ("metadata", _METADATA_FIELDS),
    ):
        group = enriched.setdefault(group_name, {})
        for key in keys:
            semantic_value = semantics.get(key)
            if not isinstance(semantic_value, dict):
                continue
            existing = group.get(key) if isinstance(group.get(key), dict) else {}
            candidates = [
                *[
                    copy.deepcopy(item)
                    for item in existing.get("sources") or []
                    if isinstance(item, dict)
                ],
                {"key": key, **copy.deepcopy(semantic_value)},
            ]
            selected = select_canonical_field(key, candidates)
            if selected is not None:
                group[key] = selected

    for group_name, kind in (
        ("normativeReferences", "reference"),
        ("replacementRelations", "replacement"),
    ):
        semantic_values = semantics.get(group_name)
        if semantic_values is None:
            continue
        candidates = [
            *_existing_structured_candidates(kind, list(enriched.get(group_name) or [])),
            *[copy.deepcopy(item) for item in semantic_values if isinstance(item, dict)],
        ]
        enriched[group_name] = merge_structured_items(kind, candidates)

    semantic_source_id = next(
        (
            str(value.get("sourceId") or "")
            for key, value in semantics.items()
            if key not in {"normativeReferences", "replacementRelations"}
            and isinstance(value, dict)
            and str(value.get("sourceId") or "")
        ),
        str(record.get("activeParseResultId") or ""),
    )
    semantic_summary = {
        "sourceType": "new_mineru_semantic",
        "sourceId": semantic_source_id,
        "parseResultId": semantic_source_id,
        "documentVersionId": str(record.get("documentVersionId") or ""),
        "createdAt": extracted_at,
        "capabilities": _semantic_capabilities(semantics),
        "semanticExtractionVersion": str(semantics.get("promptVersion") or ""),
        "modelRoute": str(semantics.get("modelRoute") or ""),
        "promptHash": str(semantics.get("promptHash") or ""),
        "contentHash": str(semantics.get("contentHash") or ""),
    }
    enriched["provenance"] = [
        *[
            copy.deepcopy(item)
            for item in record.get("provenance") or []
            if isinstance(item, dict) and item.get("sourceType") != "new_mineru_semantic"
        ],
        semantic_summary,
    ]
    enriched["history"] = [
        *[copy.deepcopy(item) for item in record.get("history") or []],
        {
            **semantic_summary,
            "fieldCount": sum(
                1
                for key, value in semantics.items()
                if key not in {"normativeReferences", "replacementRelations"}
                and isinstance(value, dict)
            ),
            "referenceCount": len(semantics.get("normativeReferences") or []),
            "replacementCount": len(semantics.get("replacementRelations") or []),
        },
    ]
    enriched["semanticExtractionVersion"] = str(semantics.get("promptVersion") or "")
    enriched["semanticExtractedAt"] = extracted_at
    enriched["semanticModelRoute"] = str(semantics.get("modelRoute") or "")
    enriched["semanticPromptHash"] = str(semantics.get("promptHash") or "")
    enriched["semanticContentHash"] = str(semantics.get("contentHash") or "")
    enriched["evidence"] = _record_evidence(enriched)
    enriched["completeness"] = canonical_completeness(enriched)
    return enriched


def _canonical_field_candidates(sources: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}

    def add(
        key: str,
        value: Any,
        *,
        source_type: str,
        source_id: Any,
        document_version_id: Any,
        **extra: Any,
    ) -> None:
        if value is None or (isinstance(value, str) and not value.strip()):
            return
        grouped.setdefault(key, []).append(
            {
                "key": key,
                "value": copy.deepcopy(value),
                "sourceType": source_type,
                "sourceId": str(source_id or ""),
                "documentVersionId": str(document_version_id or ""),
                "quotedText": str(value),
                **copy.deepcopy(extra),
            }
        )

    document_version_id = sources["version"]["id"]
    for parse, source_type in [
        (sources.get("newParse"), "new_mineru"),
        *[(item, "legacy_ocr") for item in sources.get("legacyParses") or []],
    ]:
        if not parse:
            continue
        parse_id = parse.get("parseResultId") or parse.get("id")
        for item in parse.get("fields") or []:
            raw_key = str(item.get("fieldName") or item.get("key") or "").strip()
            key = _FIELD_ALIASES.get(raw_key)
            if not key:
                continue
            add(
                key,
                item.get("fieldValue", item.get("value")),
                source_type=source_type,
                source_id=parse_id,
                document_version_id=document_version_id,
                parseResultId=parse_id,
                pageNo=item.get("pageNo"),
                bbox=item.get("bbox"),
                confidence=item.get("confidence"),
                createdAt=parse.get("finishedAt") or parse.get("createdAt"),
            )

    for item in sources.get("legacyFields") or []:
        raw_key = str(item.get("fieldName") or item.get("key") or "").strip()
        key = _FIELD_ALIASES.get(raw_key)
        if key:
            add(
                key,
                item.get("fieldValue", item.get("value")),
                source_type="legacy_ocr",
                source_id=item.get("id"),
                document_version_id=document_version_id,
                pageNo=item.get("pageNo"),
                bbox=item.get("bbox"),
                confidence=item.get("confidence"),
                createdAt=item.get("createdAt"),
            )

    for item in [*(sources.get("standardVersions") or []), *(sources.get("catalogItems") or [])]:
        source_id = item.get("id") or item.get("standardRef")
        for key, source_key in (
            ("standardCode", "code"),
            ("standardNameZh", "name"),
            ("edition", "edition"),
            ("publicationDate", "publicationDate"),
            ("effectiveDate", "effectiveDate"),
            ("status", "lifecycleStatus"),
            ("replaces", "replaces"),
            ("replacedBy", "replacedBy"),
            ("amendments", "amendments"),
            ("releaseId", "releaseId"),
            ("businessPackVersion", "businessPackVersion"),
            ("scope", "scope"),
            ("purpose", "purpose"),
        ):
            add(
                key,
                item.get(source_key),
                source_type="standard_catalog",
                source_id=source_id,
                document_version_id=document_version_id,
            )

    file = sources["file"]
    add(
        "sourceFileName",
        file.get("fileName"),
        source_type="filename_inference",
        source_id=file.get("id"),
        document_version_id=document_version_id,
    )
    add(
        "sourceRelativePath",
        file.get("sourceRelativePath"),
        source_type="filename_inference",
        source_id=file.get("id"),
        document_version_id=document_version_id,
    )
    inferred_code, inferred_name = _identity_from_filename(file.get("fileName"))
    add(
        "standardCode",
        inferred_code,
        source_type="filename_inference",
        source_id=file.get("id"),
        document_version_id=document_version_id,
    )
    add(
        "standardNameZh",
        inferred_name,
        source_type="filename_inference",
        source_id=file.get("id"),
        document_version_id=document_version_id,
    )
    status = sources["version"].get("status") or (
        "current" if sources["version"].get("isCurrent") else None
    )
    add(
        "status",
        status,
        source_type="standard_catalog",
        source_id=sources["version"].get("id"),
        document_version_id=document_version_id,
    )
    new_parse = sources.get("newParse") or {}
    add(
        "pageCount",
        len(new_parse.get("pages") or []),
        source_type="new_mineru",
        source_id=new_parse.get("parseResultId") or new_parse.get("id"),
        document_version_id=document_version_id,
        parseResultId=new_parse.get("parseResultId") or new_parse.get("id"),
    )

    code_candidates = grouped.get("standardCode") or []
    for item in code_candidates:
        match = re.search(r"(?:-|—)(\d{4})(?:\D|$)", str(item.get("value") or ""))
        if match:
            add(
                "edition",
                match.group(1),
                source_type=str(item.get("sourceType") or "filename_inference"),
                source_id=item.get("sourceId"),
                document_version_id=document_version_id,
            )
    return grouped


def _canonical_structure_candidates(
    sources: dict[str, Any], *, standard_code: str, edition: str
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]], list[dict[str, Any]]]:
    result = {
        "sections": [],
        "clauses": [],
        "blocks": [],
        "tables": [],
        "equations": [],
        "images": [],
        "seals": [],
        "normativeReferences": [],
        "replacementRelations": [],
        "businessRelations": [],
    }
    provenance: list[dict[str, Any]] = []
    history: list[dict[str, Any]] = []
    version_id = str(sources["version"]["id"])

    for parse, source_type in [
        (sources.get("newParse"), "new_mineru"),
        *[(item, "legacy_ocr") for item in sources.get("legacyParses") or []],
    ]:
        if not parse:
            continue
        parse_id = str(parse.get("parseResultId") or parse.get("id") or "")
        base = {
            "sourceType": source_type,
            "sourceId": parse_id,
            "parseResultId": parse_id,
            "documentVersionId": version_id,
            "createdAt": parse.get("finishedAt") or parse.get("createdAt"),
        }
        for block in parse.get("layoutBlocks") or []:
            candidate = _structured_candidate(
                block, base, standard_code=standard_code, edition=edition
            )
            if (
                not candidate.get("text")
                and not candidate.get("latex")
                and not candidate.get("caption")
            ):
                continue
            result["blocks"].append(candidate)
            block_type = str(block.get("blockType") or block.get("type") or "text").lower()
            if block_type in {"equation", "interline_equation", "formula"}:
                result["equations"].append(candidate)
            elif block_type in {"image", "figure"}:
                result["images"].append(candidate)
            else:
                _append_clause_candidate(result["clauses"], candidate)
        for table in parse.get("tables") or []:
            candidate = _structured_candidate(
                table, base, standard_code=standard_code, edition=edition
            )
            candidate["text"] = str(
                table.get("text")
                or table.get("caption")
                or _table_text(table.get("normalizedRows") or table.get("rows"))
            )
            candidate["normalizedRows"] = copy.deepcopy(
                table.get("normalizedRows") or table.get("rows") or []
            )
            candidate["cells"] = copy.deepcopy(table.get("cells") or [])
            candidate["columnNames"] = copy.deepcopy(
                table.get("columnNames") or _column_names(candidate["normalizedRows"])
            )
            candidate["headerReliable"] = bool(table.get("headerReliable"))
            result["tables"].append(candidate)
        for seal in parse.get("seals") or []:
            candidate = _structured_candidate(
                seal, base, standard_code=standard_code, edition=edition
            )
            candidate["text"] = str(
                seal.get("text") or seal.get("sealName") or seal.get("name") or ""
            )
            result["seals"].append(candidate)
        capabilities = ["fullText", "clause", "table", "equation", "image", "seal"]
        provenance.append(
            {
                **base,
                "capabilities": capabilities,
                "fieldCount": len(parse.get("fields") or []),
                "blockCount": len(parse.get("layoutBlocks") or []),
                "tableCount": len(parse.get("tables") or []),
                "sealCount": len(parse.get("seals") or []),
                "rawTables": copy.deepcopy(parse.get("tables") or []),
            }
        )
        history.append(
            {
                "sourceId": parse_id,
                "sourceType": source_type,
                "createdAt": parse.get("finishedAt") or parse.get("createdAt"),
                "fieldCount": len(parse.get("fields") or []),
                "blockCount": len(parse.get("layoutBlocks") or []),
                "tableCount": len(parse.get("tables") or []),
                "sealCount": len(parse.get("seals") or []),
            }
        )

    for item in sources.get("chunks") or []:
        result["blocks"].append(
            _structured_candidate(
                item,
                _source_base("knowledge_chunk", item, version_id),
                standard_code=standard_code,
                edition=edition,
            )
        )
    if sources.get("chunks"):
        provenance.append(
            _provenance_summary("knowledge_chunk", sources["chunks"], version_id, ["fullText"])
        )

    locators_by_clause: dict[str, list[dict[str, Any]]] = {}
    for locator in sources.get("clauseLocators") or []:
        locators_by_clause.setdefault(str(locator.get("clauseNo") or ""), []).append(locator)
    for item in sources.get("clauses") or []:
        candidate = _structured_candidate(
            item,
            _source_base("knowledge_clause", item, version_id),
            standard_code=standard_code,
            edition=edition,
        )
        clause_no = str(candidate.get("clauseNo") or "")
        locators = locators_by_clause.get(clause_no) or []
        if locators and not (candidate.get("pageNo") and normalize_bbox(candidate.get("bbox"))):
            locator = next(
                (
                    item
                    for item in locators
                    if (item.get("sourcePage") or item.get("startPage"))
                    and normalize_bbox(item.get("bbox"))
                ),
                None,
            )
            if locator is None:
                locator = next(
                    (item for item in locators if item.get("sourcePage") or item.get("startPage")),
                    None,
                )
            if locator:
                candidate["pageNo"] = locator.get("sourcePage") or locator.get("startPage")
                candidate["bbox"] = normalize_bbox(locator.get("bbox"))
                candidate["locatorIds"] = [str(locator.get("id") or "")]
        result["clauses"].append(candidate)
    if sources.get("clauses"):
        provenance.append(
            _provenance_summary("knowledge_clause", sources["clauses"], version_id, ["clause"])
        )
    for locator in sources.get("clauseLocators") or []:
        provenance.append(
            {
                **_source_base("clause_locator", locator, version_id),
                "capabilities": ["evidenceLocation"],
                "clauseNo": locator.get("clauseNo"),
                "pageNo": locator.get("sourcePage") or locator.get("startPage"),
                "bbox": normalize_bbox(locator.get("bbox")),
                "rawLocator": copy.deepcopy(locator),
            }
        )

    for item in sources.get("pageIndexNodes") or []:
        candidate = _structured_candidate(
            {
                **item,
                "text": item.get("text") or item.get("title"),
                "pageNo": item.get("pageNo") or item.get("startPage"),
            },
            _source_base("page_index", item, version_id),
            standard_code=standard_code,
            edition=edition,
        )
        result["sections"].append(candidate)
    if sources.get("pageIndexNodes"):
        provenance.append(
            _provenance_summary("page_index", sources["pageIndexNodes"], version_id, ["section"])
        )

    visual = sources.get("visualExtraction") or {}
    if visual:
        visual_source_id = str(visual.get("id") or f"VISUAL-{sources['file']['id']}")
        base = {
            "sourceType": "visual_extraction",
            "sourceId": visual_source_id,
            "parseResultId": None,
            "documentVersionId": version_id,
            "confidence": visual.get("confidence"),
            "needsHumanVerification": visual.get("needsHumanVerification"),
        }
        for page in visual.get("pages") or []:
            text = page.get("text") or page.get("extractedText") or ""
            candidate = _structured_candidate(
                {**page, "text": text}, base, standard_code=standard_code, edition=edition
            )
            if not candidate.get("text"):
                continue
            result["blocks"].append(candidate)
            _append_clause_candidate(result["clauses"], candidate)
        provenance.append(
            {
                **base,
                "capabilities": ["fullText", "clause", "image", "seal"],
                "pageCount": len(visual.get("pages") or []),
            }
        )
        history.append(
            {
                "sourceId": visual_source_id,
                "sourceType": "visual_extraction",
                "createdAt": visual.get("createdAt"),
                "fieldCount": len(visual.get("fields") or []),
                "blockCount": len(visual.get("pages") or []),
                "tableCount": len(visual.get("tables") or []),
                "sealCount": len(visual.get("seals") or []),
            }
        )

    sidecar = sources.get("legacyRuleSidecar") or {}
    if sidecar:
        sidecar_source_id = str(sidecar.get("id") or f"RULE-OCR-{sources['file']['id']}")
        base = {
            "sourceType": "legacy_ocr",
            "sourceId": sidecar_source_id,
            "parseResultId": None,
            "documentVersionId": version_id,
            "createdAt": sidecar.get("createdAt"),
        }
        for fragment in sidecar.get("fragments") or []:
            candidate = _structured_candidate(
                fragment, base, standard_code=standard_code, edition=edition
            )
            if not candidate.get("text"):
                continue
            result["blocks"].append(candidate)
            _append_clause_candidate(result["clauses"], candidate)
        provenance.append(
            {
                **base,
                "capabilities": ["fullText", "clause"],
                "fragmentCount": len(sidecar.get("fragments") or []),
            }
        )
        history.append(
            {
                "sourceId": sidecar_source_id,
                "sourceType": "legacy_ocr",
                "createdAt": sidecar.get("createdAt"),
                "fieldCount": 0,
                "blockCount": len(sidecar.get("fragments") or []),
                "tableCount": 0,
                "sealCount": 0,
            }
        )

    _append_legacy_field_blocks(result["blocks"], sources, version_id, standard_code, edition)
    _append_relation_candidates(result, sources, standard_code, version_id)
    if sources.get("standardVersions"):
        provenance.append(
            _provenance_summary(
                "standard_catalog", sources["standardVersions"], version_id, ["replacement"]
            )
        )
    if sources.get("clauseReferences"):
        provenance.append(
            _provenance_summary(
                "standard_reference", sources["clauseReferences"], version_id, ["reference"]
            )
        )
    if sources.get("ruleReferences"):
        provenance.append(
            _provenance_summary(
                "business_rule", sources["ruleReferences"], version_id, ["business"]
            )
        )
    return result, provenance, history


def _structured_candidate(
    item: dict[str, Any],
    base: dict[str, Any],
    *,
    standard_code: str,
    edition: str,
) -> dict[str, Any]:
    result = {**copy.deepcopy(item), **copy.deepcopy(base)}
    result["standardCode"] = standard_code
    result["edition"] = edition
    result["text"] = str(item.get("text") or item.get("quotedText") or "")
    result["pageNo"] = item.get("pageNo", item.get("sourcePage"))
    result["bbox"] = normalize_bbox(item.get("bbox"))
    if item.get("confidence") is not None:
        result["confidence"] = item.get("confidence")
    if item.get("needsHumanVerification") is not None:
        result["needsHumanVerification"] = bool(item.get("needsHumanVerification"))
    return result


def _append_clause_candidate(clauses: list[dict[str, Any]], candidate: dict[str, Any]) -> None:
    clause_no = str(candidate.get("clauseNo") or "").strip()
    if not clause_no:
        match = _CLAUSE_NUMBER.match(str(candidate.get("text") or ""))
        clause_no = match.group(1) if match else ""
    if clause_no:
        clauses.append({**copy.deepcopy(candidate), "clauseNo": clause_no})


def _source_base(
    source_type: str, item: dict[str, Any], document_version_id: str
) -> dict[str, Any]:
    return {
        "sourceType": source_type,
        "sourceId": str(item.get("id") or item.get("sourceId") or ""),
        "parseResultId": item.get("parseResultId"),
        "documentVersionId": document_version_id,
        "createdAt": item.get("createdAt"),
        "confidence": item.get("confidence"),
        "needsHumanVerification": item.get("needsHumanVerification"),
    }


def _provenance_summary(
    source_type: str,
    items: list[dict[str, Any]],
    document_version_id: str,
    capabilities: list[str],
) -> dict[str, Any]:
    source_ids = [str(item.get("id") or item.get("sourceId") or "") for item in items]
    return {
        "sourceType": source_type,
        "sourceId": source_ids[0] if len(source_ids) == 1 else f"{source_type}:{len(items)}",
        "sourceIds": source_ids,
        "parseResultId": None,
        "documentVersionId": document_version_id,
        "capabilities": capabilities,
        "count": len(items),
    }


def _append_legacy_field_blocks(
    blocks: list[dict[str, Any]],
    sources: dict[str, Any],
    version_id: str,
    standard_code: str,
    edition: str,
) -> None:
    evidence_items = sources.get("legacyEvidence") or []
    for field in sources.get("legacyFields") or []:
        field_name = str(field.get("fieldName") or "")
        if not field_name.startswith("OCR文本"):
            continue
        text = str(field.get("fieldValue") or field.get("value") or "").strip()
        if not text:
            continue
        evidence = next(
            (
                item
                for item in evidence_items
                if item.get("fieldId") == field.get("id")
                or (
                    item.get("fieldName") == field.get("fieldName")
                    and str(item.get("quotedText") or "").strip() == text
                )
            ),
            {},
        )
        candidate = _structured_candidate(
            {
                **field,
                "text": text,
                "pageNo": evidence.get("pageNo", field.get("pageNo")),
                "bbox": evidence.get("bbox", field.get("bbox")),
                "quotedText": evidence.get("quotedText") or text,
            },
            _source_base("legacy_ocr", field, version_id),
            standard_code=standard_code,
            edition=edition,
        )
        blocks.append(candidate)


def _append_relation_candidates(
    result: dict[str, list[dict[str, Any]]],
    sources: dict[str, Any],
    standard_code: str,
    version_id: str,
) -> None:
    catalog_by_ref: dict[str, dict[str, Any]] = {}
    for item in [*(sources.get("standardVersions") or []), *(sources.get("catalogItems") or [])]:
        if item.get("standardRef") or item.get("id"):
            catalog_by_ref[str(item.get("standardRef") or item.get("id"))] = item

    for item in sources.get("clauseReferences") or []:
        target = catalog_by_ref.get(str(item.get("standardRef") or ""), {})
        target_code = str(
            item.get("targetStandardCode")
            or item.get("standardCode")
            or target.get("code")
            or item.get("standardRef")
            or ""
        )
        candidate = {
            **_source_base("standard_reference", item, version_id),
            "sourceStandardCode": str(item.get("sourceStandardCode") or standard_code),
            "sourceClauseNo": item.get("sourceClauseNo"),
            "targetStandardCode": target_code,
            "targetClauseNo": item.get("targetClauseNo") or item.get("clauseNo"),
            "pageNo": item.get("sourcePage") or item.get("pageNo"),
            "bbox": item.get("bbox"),
            "text": " ".join(
                part for part in [target_code, str(item.get("clauseNo") or "")] if part
            ),
        }
        result["normativeReferences"].append(candidate)

    for item in sources.get("standardVersions") or []:
        for relation_name in ("replaces", "replacedBy", "amendments"):
            values = item.get(relation_name)
            if values is None or values == "" or values == []:
                continue
            if not isinstance(values, list):
                values = [values]
            for value in values:
                target_code = str(value.get("code") if isinstance(value, dict) else value).strip()
                if not target_code:
                    continue
                result["replacementRelations"].append(
                    {
                        **_source_base("standard_catalog", item, version_id),
                        "sourceStandardCode": standard_code,
                        "targetStandardCode": target_code,
                        "purpose": relation_name,
                        "text": f"{relation_name}:{target_code}",
                    }
                )

    for item in sources.get("ruleReferences") or []:
        target = catalog_by_ref.get(str(item.get("standardRef") or ""), {})
        target_code = str(target.get("code") or item.get("standardRef") or standard_code)
        result["businessRelations"].append(
            {
                **_source_base("business_rule", item, version_id),
                "sourceStandardCode": standard_code,
                "targetStandardCode": target_code,
                "targetClauseNo": item.get("clauseNo"),
                "nodeIds": copy.deepcopy(item.get("nodeIds") or []),
                "materialTypes": copy.deepcopy(item.get("materialTypes") or []),
                "purpose": item.get("purpose") or item.get("ruleId"),
                "text": "|".join(
                    [
                        str(item.get("ruleId") or ""),
                        target_code,
                        str(item.get("clauseNo") or ""),
                    ]
                ),
            }
        )


def _table_text(rows: Any) -> str:
    if not rows:
        return ""
    return json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _column_names(rows: Any) -> list[str]:
    if not isinstance(rows, list):
        return []
    first = next((item for item in rows if isinstance(item, dict)), None)
    return [str(key) for key in first] if first else []


def _identity_from_filename(value: Any) -> tuple[str | None, str | None]:
    stem = Path(str(value or "")).stem.replace("∕", "/").replace("／", "/")
    match = re.match(
        r"^\s*([A-Z]{1,5})(?:[_/]?(T))?[\s_]+([0-9.]+)[-—](\d{4})(?:[\s_]+(.*))?$",
        stem,
    )
    if not match:
        return None, stem.strip() or None
    prefix = match.group(1) + ("/T" if match.group(2) else "")
    code = f"{prefix} {match.group(3)}-{match.group(4)}"
    name = str(match.group(5) or "").strip() or None
    return code, name


def _standard_kb_version(state: dict[str, Any], file: dict[str, Any]) -> Any:
    source = _one(state.get("knowledge_sources", []), id=file.get("sourceId"))
    return (source or {}).get("version")


def _source_fingerprint(sources: dict[str, Any]) -> str:
    normalized = json.dumps(
        sources,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return "sha256:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _record_evidence(record: dict[str, Any]) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for group_name in ("identity", "version", "metadata"):
        for field in (record.get(group_name) or {}).values():
            for source in field.get("sources") or []:
                authority = (
                    field.get("authority")
                    if source.get("sourceId") == field.get("selectedSourceId")
                    else "supporting"
                )
                evidence.append(canonical_evidence(source, authority=str(authority)))
    for group_name in (
        "sections",
        "clauses",
        "blocks",
        "tables",
        "equations",
        "images",
        "seals",
        "normativeReferences",
        "replacementRelations",
        "businessRelations",
    ):
        for item in record.get(group_name) or []:
            evidence.extend(copy.deepcopy(item.get("sources") or []))
    unique: dict[str, dict[str, Any]] = {}
    for item in evidence:
        key = json.dumps(
            [
                item.get("sourceType"),
                item.get("sourceId"),
                item.get("pageNo"),
                item.get("bbox"),
                item.get("contentHash"),
            ],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        unique.setdefault(key, item)
    return [unique[key] for key in sorted(unique)]


def _one(items: list[dict[str, Any]], **match: Any) -> dict[str, Any] | None:
    return next(
        (item for item in items if all(item.get(key) == value for key, value in match.items())),
        None,
    )


def _by_version(items: list[dict[str, Any]], version_id: str) -> list[dict[str, Any]]:
    return copy.deepcopy([item for item in items if item.get("documentVersionId") == version_id])


def _by_file(items: list[dict[str, Any]], file_id: str) -> list[dict[str, Any]]:
    return copy.deepcopy(
        [
            item
            for item in items
            if (
                item.get("fileId") == file_id
                or item.get("knowledgeFileId") == file_id
                or (item.get("scope") or {}).get("fileId") == file_id
            )
        ]
    )


def _read_optional_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _page_nodes_for_path(state: dict[str, Any], source_path: str | None) -> list[dict[str, Any]]:
    normalized = str(source_path or "").replace("\\", "/").lstrip("./")
    return copy.deepcopy(
        [
            item
            for item in state.get("knowledge_page_index_nodes", [])
            if str(item.get("sourceRelativePath") or "").replace("\\", "/").lstrip("./")
            == normalized
        ]
    )


def _catalog_items_for_file(state: dict[str, Any], file: dict[str, Any]) -> list[dict[str, Any]]:
    file_name = str(file.get("fileName") or "")
    result = []
    for pack in state.get("business_packs", []):
        for item in pack.get("standardCatalog") or []:
            if (
                item.get("knowledgeFileId") == file["id"]
                or str(item.get("fileName") or "") == file_name
            ):
                result.append({**copy.deepcopy(item), "businessPackId": pack.get("id")})
    return result


def _rule_references_for_file(state: dict[str, Any], file: dict[str, Any]) -> list[dict[str, Any]]:
    file_name = str(file.get("fileName") or "")
    result = []
    for rule in state.get("rule_versions", []):
        for reference in rule.get("referencedStandards") or []:
            if (
                reference.get("knowledgeFileId") == file["id"]
                or str(reference.get("fileName") or "") == file_name
            ):
                result.append(
                    {
                        **copy.deepcopy(reference),
                        "ruleId": rule.get("id"),
                        "nodeIds": list(rule.get("nodeIds") or []),
                    }
                )
    return result
