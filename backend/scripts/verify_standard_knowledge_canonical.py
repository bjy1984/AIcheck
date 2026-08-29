#!/usr/bin/env python3
"""Verify canonical standard coverage, provenance, mapping, and source immutability."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from libs.security.tenant import configured_tenant_id  # noqa: E402
from libs.standard_knowledge_canonical import REQUIRED_CATEGORIES  # noqa: E402
from scripts.rebuild_standard_knowledge_canonical import (  # noqa: E402
    CANONICAL_COLLECTION,
    SOURCE_COLLECTIONS,
    STANDARD_SOURCE_ID,
    source_collection_digests,
)


_STRUCTURED_GROUPS = (
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
)
_FIELD_GROUPS = ("identity", "version", "metadata")
SourceRow = tuple[str, str, Any]


def _issue(
    path: str,
    reason: str,
    **details: Any,
) -> dict[str, Any]:
    return {"path": path, "reason": reason, **details}


def _source_registry(source_rows: list[SourceRow]) -> dict[str, set[str]]:
    registry: dict[str, set[str]] = defaultdict(set)

    def add(source_type: str, *values: Any) -> None:
        registry[source_type].update(str(value) for value in values if str(value or ""))

    for collection, object_id, payload in source_rows:
        if not isinstance(payload, dict):
            continue
        if collection == "knowledge_files":
            add("filename_inference", object_id, payload.get("id"))
        elif collection == "document_versions":
            add("standard_catalog", object_id, payload.get("id"))
        elif collection == "ocr_parse_results":
            source_type = (
                "new_mineru"
                if isinstance(payload.get("metadata"), dict)
                and payload["metadata"].get("sidecarImported")
                else "legacy_ocr"
            )
            add(source_type, object_id, payload.get("id"), payload.get("parseResultId"))
        elif collection == "extracted_fields":
            add("legacy_ocr", object_id, payload.get("id"))
        elif collection == "knowledge_chunks":
            add("knowledge_chunk", object_id, payload.get("id"))
        elif collection == "knowledge_clauses":
            add("knowledge_clause", object_id, payload.get("id"))
        elif collection == "knowledge_page_index_nodes":
            add("page_index", object_id, payload.get("id"))
        elif collection == "standard_document_versions":
            add("standard_catalog", object_id, payload.get("id"), payload.get("standardRef"))
        elif collection == "standard_clause_references":
            add("standard_reference", object_id, payload.get("id"))
        elif collection == "standard_clause_locators":
            add("clause_locator", object_id, payload.get("id"))
        elif collection == "rule_versions":
            for reference in payload.get("referencedStandards") or []:
                if isinstance(reference, dict):
                    add("business_rule", reference.get("id"), reference.get("sourceId"))
        elif collection == "business_packs":
            for item in payload.get("standardCatalog") or []:
                if isinstance(item, dict):
                    add("standard_catalog", item.get("id"), item.get("standardRef"))

    for directory, source_type, prefix in (
        (REPO_ROOT / "backend/data/visual_extractions", "visual_extraction", "VISUAL-"),
        (REPO_ROOT / "backend/data/rules_ocr_sidecars", "legacy_ocr", "RULE-OCR-"),
    ):
        for path in directory.glob("*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict):
                add(source_type, payload.get("id") or f"{prefix}{path.stem}")
    return registry


def _validate_source_entry(
    issues: list[dict[str, Any]],
    path: str,
    value: Any,
    registry: dict[str, set[str]],
) -> None:
    if not isinstance(value, dict):
        issues.append(_issue(path, "expected_object", actualType=type(value).__name__))
        return
    source_type = str(value.get("sourceType") or "")
    source_id = str(value.get("sourceId") or "")
    if not source_type:
        issues.append(
            _issue(
                f"{path}.sourceType",
                "missing_source_identity",
                sourceType="",
                sourceId=source_id,
            )
        )
        return
    if not source_id:
        issues.append(
            _issue(
                f"{path}.sourceId",
                "missing_source_identity",
                sourceType=source_type,
                sourceId="",
            )
        )
        return

    source_ids_value = value.get("sourceIds")
    if source_ids_value is not None:
        if not isinstance(source_ids_value, list):
            issues.append(
                _issue(
                    f"{path}.sourceIds",
                    "expected_list",
                    actualType=type(source_ids_value).__name__,
                )
            )
            return
        effective_ids = [str(item or "") for item in source_ids_value]
        id_path = f"{path}.sourceIds"
    else:
        effective_ids = [source_id]
        id_path = f"{path}.sourceId"
    for source_index, effective_id in enumerate(effective_ids):
        current_path = f"{id_path}[{source_index}]" if len(effective_ids) > 1 else id_path
        if not effective_id:
            issues.append(
                _issue(
                    current_path,
                    "missing_source_identity",
                    sourceType=source_type,
                    sourceId=effective_id,
                )
            )
        elif effective_id not in registry.get(source_type, set()):
            issues.append(
                _issue(
                    current_path,
                    "unresolved_source_id",
                    sourceType=source_type,
                    sourceId=effective_id,
                )
            )


def _validate_sources_array(
    issues: list[dict[str, Any]],
    path: str,
    item: Any,
    registry: dict[str, set[str]],
) -> None:
    if not isinstance(item, dict):
        issues.append(_issue(path, "expected_object", actualType=type(item).__name__))
        return
    sources = item.get("sources")
    if not isinstance(sources, list):
        issues.append(_issue(f"{path}.sources", "expected_list", actualType=type(sources).__name__))
        return
    if not sources:
        issues.append(_issue(f"{path}.sources", "missing_sources"))
    for index, source in enumerate(sources):
        _validate_source_entry(issues, f"{path}.sources[{index}]", source, registry)


def _rows(connection: psycopg.Connection[Any], tenant_id: str) -> list[SourceRow]:
    collections = [*SOURCE_COLLECTIONS, CANONICAL_COLLECTION]
    return [
        (str(collection), str(object_id), payload)
        for collection, object_id, payload in connection.execute(
            """
            SELECT collection, object_id, payload FROM aicheck_state
            WHERE tenant_id=%s AND collection=ANY(%s)
            ORDER BY collection, object_id
            """,
            (tenant_id, collections),
        ).fetchall()
    ]


def _provenance_issues(
    record: dict[str, Any], registry: dict[str, set[str]]
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    if not str(record.get("sourceFingerprint") or ""):
        issues.append(_issue("sourceFingerprint", "missing_value"))
    for list_name in ("provenance", "history"):
        values = record.get(list_name)
        if not isinstance(values, list):
            issues.append(_issue(list_name, "expected_list"))
            continue
        if list_name == "provenance" and not values:
            issues.append(_issue(list_name, "missing_sources"))
        for index, item in enumerate(values):
            _validate_source_entry(issues, f"{list_name}[{index}]", item, registry)

    for group_name in _FIELD_GROUPS:
        group = record.get(group_name)
        if not isinstance(group, dict):
            issues.append(_issue(group_name, "expected_object", actualType=type(group).__name__))
            continue
        for key, item in group.items():
            _validate_sources_array(issues, f"{group_name}.{key}", item, registry)
    for group_name in _STRUCTURED_GROUPS:
        values = record.get(group_name)
        if not isinstance(values, list):
            issues.append(_issue(group_name, "expected_list", actualType=type(values).__name__))
            continue
        for index, item in enumerate(values):
            _validate_sources_array(issues, f"{group_name}[{index}]", item, registry)
    evidence = record.get("evidence")
    if not isinstance(evidence, list):
        issues.append(_issue("evidence", "expected_list", actualType=type(evidence).__name__))
    else:
        for index, item in enumerate(evidence):
            _validate_source_entry(issues, f"evidence[{index}]", item, registry)
    return issues


def _duplicate_identifiers(
    canonical_rows: list[tuple[str, Any]],
) -> list[dict[str, Any]]:
    occurrences: dict[tuple[str, str], list[str]] = defaultdict(list)
    for object_id, record in canonical_rows:
        if not isinstance(record, dict):
            continue
        for field in ("id", "knowledgeFileId"):
            value = str(record.get(field) or "")
            if value:
                occurrences[(field, value)].append(object_id)
    return [
        {"field": field, "value": value, "objectIds": object_ids}
        for (field, value), object_ids in sorted(occurrences.items())
        if len(object_ids) > 1
    ]


def _canonical_identity(
    standard_file_ids: set[str],
    canonical_rows: list[tuple[str, Any]],
) -> dict[str, Any]:
    object_ids = {object_id for object_id, _ in canonical_rows}
    payload_ids = [
        str(record.get("knowledgeFileId") or "")
        for _, record in canonical_rows
        if isinstance(record, dict) and str(record.get("knowledgeFileId") or "")
    ]
    payload_id_set = set(payload_ids)
    payload_counts = Counter(payload_ids)
    return {
        "missingObjectIds": sorted(standard_file_ids - object_ids),
        "extraObjectIds": sorted(object_ids - standard_file_ids),
        "missingPayloadIds": sorted(standard_file_ids - payload_id_set),
        "extraPayloadIds": sorted(payload_id_set - standard_file_ids),
        "duplicatePayloadIds": sorted(
            value for value, count in payload_counts.items() if count > 1
        ),
        "missingPayloadIdObjectIds": sorted(
            object_id
            for object_id, record in canonical_rows
            if not isinstance(record, dict) or not str(record.get("knowledgeFileId") or "")
        ),
        "objectPayloadMismatches": [
            {
                "objectId": object_id,
                "knowledgeFileId": (
                    str(record.get("knowledgeFileId") or "") if isinstance(record, dict) else ""
                ),
            }
            for object_id, record in canonical_rows
            if not isinstance(record, dict) or object_id != str(record.get("knowledgeFileId") or "")
        ],
    }


def _source_mapping(
    source_rows: list[SourceRow],
    canonical_file_ids: set[str],
) -> list[dict[str, Any]]:
    files = {
        object_id: payload
        for collection, object_id, payload in source_rows
        if collection == "knowledge_files"
        and isinstance(payload, dict)
        and payload.get("sourceId") == STANDARD_SOURCE_ID
    }
    file_ids = set(files)
    document_to_file = {
        str(payload.get("documentId")): file_id
        for file_id, payload in files.items()
        if payload.get("documentId")
    }
    version_to_file = {
        str(payload.get("documentVersionId")): file_id
        for file_id, payload in files.items()
        if payload.get("documentVersionId")
    }
    path_to_file = {
        str(payload.get("sourceRelativePath") or "").replace("\\", "/").lstrip("./"): file_id
        for file_id, payload in files.items()
        if payload.get("sourceRelativePath")
    }
    name_to_file = {
        str(payload.get("fileName")): file_id
        for file_id, payload in files.items()
        if payload.get("fileName")
    }
    unresolved: list[dict[str, Any]] = []

    for collection, object_id, payload in source_rows:
        if not isinstance(payload, dict):
            unresolved.append(
                {
                    "collection": collection,
                    "objectId": object_id,
                    "reason": "source payload is not an object",
                    "actualType": type(payload).__name__,
                }
            )
            continue
        mapped: set[str] = set()
        if collection == "knowledge_files":
            if object_id in file_ids:
                mapped.add(object_id)
            else:
                continue
        elif collection == "documents":
            if object_id in document_to_file:
                mapped.add(document_to_file[object_id])
            else:
                continue
        elif collection == "document_versions":
            if object_id in version_to_file:
                mapped.add(version_to_file[object_id])
            elif str(payload.get("documentId") or "") in document_to_file:
                mapped.add(document_to_file[str(payload["documentId"])])
            else:
                continue
        elif collection == "knowledge_sources":
            if object_id != STANDARD_SOURCE_ID and payload.get("id") != STANDARD_SOURCE_ID:
                continue
            mapped.update(file_ids)
            if not mapped:
                unresolved.append(
                    {
                        "collection": collection,
                        "objectId": object_id,
                        "reason": "standard knowledge source has no standard files",
                    }
                )
                continue
        elif collection == "business_packs":
            catalog = payload.get("standardCatalog")
            if not isinstance(catalog, list):
                unresolved.append(
                    {
                        "collection": collection,
                        "objectId": object_id,
                        "reason": "standardCatalog is not a list",
                        "actualType": type(catalog).__name__,
                    }
                )
                continue
            for item in catalog:
                if not isinstance(item, dict):
                    unresolved.append(
                        {
                            "collection": collection,
                            "objectId": object_id,
                            "reason": "standard catalog entry is not an object",
                            "actualType": type(item).__name__,
                        }
                    )
                    continue
                direct = str(item.get("knowledgeFileId") or "")
                file_name = str(item.get("fileName") or "")
                if direct in file_ids:
                    mapped.add(direct)
                elif file_name in name_to_file:
                    mapped.add(name_to_file[file_name])
                else:
                    unresolved.append(
                        {
                            "collection": collection,
                            "objectId": object_id,
                            "knowledgeFileIds": [direct] if direct else [],
                            "reason": "standard catalog entry has no standard file mapping",
                        }
                    )
            if not mapped:
                continue
        elif collection == "rule_versions":
            references = payload.get("referencedStandards")
            if references is not None and not isinstance(references, list):
                unresolved.append(
                    {
                        "collection": collection,
                        "objectId": object_id,
                        "reason": "referencedStandards is not a list",
                        "actualType": type(references).__name__,
                    }
                )
                continue
            for reference in references or []:
                if not isinstance(reference, dict):
                    unresolved.append(
                        {
                            "collection": collection,
                            "objectId": object_id,
                            "reason": "referenced standard is not an object",
                            "actualType": type(reference).__name__,
                        }
                    )
                    continue
                direct = str(reference.get("knowledgeFileId") or "")
                file_name = str(reference.get("fileName") or "")
                if direct in file_ids:
                    mapped.add(direct)
                elif file_name in name_to_file:
                    mapped.add(name_to_file[file_name])
            if not mapped:
                continue
        else:
            scope = payload.get("scope") if isinstance(payload.get("scope"), dict) else {}
            direct_values = {
                str(payload.get("fileId") or ""),
                str(payload.get("knowledgeFileId") or ""),
                str(scope.get("fileId") or ""),
            }
            mapped.update(direct_values & file_ids)
            document_id = str(payload.get("documentId") or "")
            version_id = str(payload.get("documentVersionId") or "")
            source_path = (
                str(payload.get("sourceRelativePath") or "").replace("\\", "/").lstrip("./")
            )
            if document_id in document_to_file:
                mapped.add(document_to_file[document_id])
            if version_id in version_to_file:
                mapped.add(version_to_file[version_id])
            if source_path in path_to_file:
                mapped.add(path_to_file[source_path])
            if not mapped:
                if payload.get("sourceId") == STANDARD_SOURCE_ID:
                    unresolved.append(
                        {
                            "collection": collection,
                            "objectId": object_id,
                            "reason": "standard source has no knowledge-file mapping",
                        }
                    )
                continue

        missing_targets = sorted(mapped - canonical_file_ids)
        if missing_targets:
            unresolved.append(
                {
                    "collection": collection,
                    "objectId": object_id,
                    "knowledgeFileIds": missing_targets,
                    "reason": "canonical record missing",
                }
            )
    return unresolved


def _coverage_matrix(records: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    matrix: dict[str, dict[str, int]] = {}
    for category in REQUIRED_CATEGORIES:
        statuses = []
        for record in records:
            completeness = record.get("completeness")
            category_value = completeness.get(category) if isinstance(completeness, dict) else None
            statuses.append(
                str(category_value.get("status") or "missing")
                if isinstance(category_value, dict)
                else "missing"
            )
        counts = Counter(statuses)
        matrix[category] = {
            status: int(counts.get(status, 0))
            for status in ("complete", "partial", "missing", "not_applicable")
        }
    return matrix


def verify(database_url: str, *, require_count: int) -> dict[str, Any]:
    if require_count < 0:
        raise ValueError("require_count must be non-negative")
    tenant_id = configured_tenant_id()
    with psycopg.connect(database_url, autocommit=True) as connection:
        before_digests = source_collection_digests(connection, tenant_id)
        rows = _rows(connection, tenant_id)
        after_digests = source_collection_digests(connection, tenant_id)

    source_rows = [row for row in rows if row[0] in SOURCE_COLLECTIONS]
    standard_files: dict[str, dict[str, Any]] = {
        object_id: payload
        for collection, object_id, payload in source_rows
        if collection == "knowledge_files"
        and isinstance(payload, dict)
        and payload.get("sourceId") == STANDARD_SOURCE_ID
    }
    canonical_rows = [
        (object_id, payload)
        for collection, object_id, payload in rows
        if collection == CANONICAL_COLLECTION
    ]
    canonical_shape_issues = [
        {
            "objectId": object_id,
            "path": "$",
            "reason": "expected_object",
            "actualType": type(payload).__name__,
        }
        for object_id, payload in canonical_rows
        if not isinstance(payload, dict)
    ]
    valid_canonical_rows = [
        (object_id, payload) for object_id, payload in canonical_rows if isinstance(payload, dict)
    ]
    canonical_identity = _canonical_identity(set(standard_files), canonical_rows)
    canonical_identity_valid = not any(canonical_identity.values())
    canonical_by_file = {
        str(record.get("knowledgeFileId")): record
        for object_id, record in valid_canonical_rows
        if str(record.get("knowledgeFileId") or "")
    }
    canonical_file_ids = set(canonical_by_file)
    records = [record for _, record in valid_canonical_rows]

    duplicate_details = _duplicate_identifiers(canonical_rows)
    duplicate_ids = sum(len(item["objectIds"]) - 1 for item in duplicate_details)
    registry = _source_registry(source_rows)
    provenance_issues = []
    for file_id, record in sorted(canonical_by_file.items()):
        provenance_issues.extend(
            {"knowledgeFileId": file_id, **item} for item in _provenance_issues(record, registry)
        )
    provenance_details = []
    for file_id in sorted(canonical_by_file):
        paths = [
            str(item["path"]).removesuffix(".sourceId")
            for item in provenance_issues
            if item["knowledgeFileId"] == file_id
        ]
        if paths:
            provenance_details.append(
                {"knowledgeFileId": file_id, "paths": list(dict.fromkeys(paths))}
            )
    missing_provenance = len(provenance_issues)
    unmapped_details = _source_mapping(source_rows, canonical_file_ids)
    unmapped_sources = len(unmapped_details)

    def has_mineru(record: dict[str, Any]) -> bool:
        provenance = record.get("provenance")
        return isinstance(provenance, list) and any(
            isinstance(item, dict) and item.get("sourceType") == "new_mineru" for item in provenance
        )

    mineru_covered = sum(
        has_mineru(record) for record in records if record.get("contextType") != "context_only"
    )
    context_only_count = sum(record.get("contextType") == "context_only" for record in records)
    expected_mineru = 58 if require_count == 59 else require_count
    expected_context_only = 1 if require_count == 59 else 0

    standards = []
    for file_id in sorted(standard_files):
        record = canonical_by_file.get(file_id)
        standards.append(
            {
                "knowledgeFileId": file_id,
                "canonicalPresent": record is not None,
                "contextType": (record or {}).get("contextType"),
                "mineruCovered": bool(
                    record and record.get("contextType") != "context_only" and has_mineru(record)
                ),
                "missingCategories": list(
                    (
                        (record.get("completeness") or {}).get("missingCategories") or []
                        if record and isinstance(record.get("completeness"), dict)
                        else []
                    )
                ),
                "missingProvenance": next(
                    (
                        item["paths"]
                        for item in provenance_details
                        if item["knowledgeFileId"] == file_id
                    ),
                    [],
                ),
            }
        )

    assertions = {
        "canonical_count": len(canonical_rows) == require_count,
        "canonical_identity": canonical_identity_valid,
        "canonical_shape": not canonical_shape_issues,
        "mineru_coverage": mineru_covered == expected_mineru,
        "context_only_count": context_only_count == expected_context_only,
        "duplicate_ids": duplicate_ids == 0,
        "missing_provenance": missing_provenance == 0,
        "unmapped_sources": unmapped_sources == 0,
        "source_digest_unchanged": before_digests == after_digests,
    }
    return {
        "schemaVersion": "standard-knowledge-canonical-verification@1",
        "generatedAt": datetime.now(UTC).isoformat(),
        "tenantId": tenant_id,
        "requiredCount": require_count,
        "actualCount": len(canonical_rows),
        "canonicalIdentity": canonical_identity,
        "canonicalShapeIssues": canonical_shape_issues,
        "expectedMineruCoverage": expected_mineru,
        "mineruCovered": mineru_covered,
        "expectedContextOnlyCount": expected_context_only,
        "contextOnlyCount": context_only_count,
        "duplicateIds": duplicate_ids,
        "duplicateDetails": duplicate_details,
        "missingProvenance": missing_provenance,
        "missingProvenanceDetails": provenance_details,
        "provenanceIssues": provenance_issues,
        "unmappedSources": unmapped_sources,
        "unmappedSourceDetails": unmapped_details,
        "sourceDigestsBefore": before_digests,
        "sourceDigestsAfter": after_digests,
        "coverageMatrix": _coverage_matrix(records),
        "standards": standards,
        "assertions": assertions,
        "passed": all(assertions.values()),
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default=os.getenv("AICHECK_DATABASE_URL") or os.getenv("DATABASE_URL") or "",
    )
    parser.add_argument("--require-count", type=int, default=59)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.database_url:
        raise SystemExit("AICHECK_DATABASE_URL or --database-url is required")
    try:
        report = verify(args.database_url, require_count=args.require_count)
    except Exception as exc:  # noqa: BLE001 - JSON mode must never leak a traceback
        report = {
            "schemaVersion": "standard-knowledge-canonical-verification@1",
            "generatedAt": datetime.now(UTC).isoformat(),
            "tenantId": configured_tenant_id(),
            "requiredCount": args.require_count,
            "assertions": {"verifier_runtime": False},
            "errors": [
                {
                    "reason": "verification_error",
                    "errorType": type(exc).__name__,
                    "message": str(exc),
                }
            ],
            "passed": False,
        }
    print(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2 if args.json else None,
            sort_keys=True,
        )
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
