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


def _append_missing_source_paths(
    missing: list[str],
    path: str,
    item: dict[str, Any],
) -> None:
    sources = list(item.get("sources") or [])
    if not sources:
        missing.append(path)
        return
    for index, source in enumerate(sources):
        if not str((source or {}).get("sourceType") or "") or not str(
            (source or {}).get("sourceId") or ""
        ):
            missing.append(f"{path}.sources[{index}]")


def _rows(
    connection: psycopg.Connection[Any], tenant_id: str
) -> list[tuple[str, str, dict[str, Any]]]:
    collections = [*SOURCE_COLLECTIONS, CANONICAL_COLLECTION]
    return [
        (str(collection), str(object_id), dict(payload))
        for collection, object_id, payload in connection.execute(
            """
            SELECT collection, object_id, payload FROM aicheck_state
            WHERE tenant_id=%s AND collection=ANY(%s)
            ORDER BY collection, object_id
            """,
            (tenant_id, collections),
        ).fetchall()
    ]


def _missing_provenance_paths(record: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    if not str(record.get("sourceFingerprint") or ""):
        missing.append("sourceFingerprint")
    provenance = list(record.get("provenance") or [])
    if not provenance:
        missing.append("provenance")
    for index, item in enumerate(provenance):
        if not str((item or {}).get("sourceType") or "") or not str(
            (item or {}).get("sourceId") or ""
        ):
            missing.append(f"provenance[{index}]")
    for group_name in ("identity", "version", "metadata"):
        for key, item in (record.get(group_name) or {}).items():
            _append_missing_source_paths(missing, f"{group_name}.{key}", item or {})
    for group_name in _STRUCTURED_GROUPS:
        for index, item in enumerate(record.get(group_name) or []):
            _append_missing_source_paths(missing, f"{group_name}[{index}]", item or {})
    for index, item in enumerate(record.get("evidence") or []):
        if not str((item or {}).get("sourceType") or "") or not str(
            (item or {}).get("sourceId") or ""
        ):
            missing.append(f"evidence[{index}]")
    return missing


def _duplicate_identifiers(
    canonical_rows: list[tuple[str, dict[str, Any]]],
) -> list[dict[str, Any]]:
    occurrences: dict[tuple[str, str], list[str]] = defaultdict(list)
    for object_id, record in canonical_rows:
        for field in ("id", "knowledgeFileId"):
            value = str(record.get(field) or "")
            if value:
                occurrences[(field, value)].append(object_id)
    return [
        {"field": field, "value": value, "objectIds": object_ids}
        for (field, value), object_ids in sorted(occurrences.items())
        if len(object_ids) > 1
    ]


def _source_mapping(
    source_rows: list[tuple[str, str, dict[str, Any]]],
    canonical_file_ids: set[str],
) -> list[dict[str, Any]]:
    files = {
        object_id: payload
        for collection, object_id, payload in source_rows
        if collection == "knowledge_files" and payload.get("sourceId") == STANDARD_SOURCE_ID
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
        elif collection == "rule_versions":
            for reference in payload.get("referencedStandards") or []:
                direct = str(reference.get("knowledgeFileId") or "")
                file_name = str(reference.get("fileName") or "")
                if direct in file_ids:
                    mapped.add(direct)
                elif file_name in name_to_file:
                    mapped.add(name_to_file[file_name])
            if not mapped:
                continue
        else:
            direct_values = {
                str(payload.get("fileId") or ""),
                str(payload.get("knowledgeFileId") or ""),
                str((payload.get("scope") or {}).get("fileId") or ""),
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
        counts = Counter(
            str(((record.get("completeness") or {}).get(category) or {}).get("status") or "missing")
            for record in records
        )
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
    standard_files = {
        object_id: payload
        for collection, object_id, payload in source_rows
        if collection == "knowledge_files" and payload.get("sourceId") == STANDARD_SOURCE_ID
    }
    canonical_rows = [
        (object_id, payload)
        for collection, object_id, payload in rows
        if collection == CANONICAL_COLLECTION
    ]
    canonical_by_file = {
        str(record.get("knowledgeFileId") or object_id): record
        for object_id, record in canonical_rows
    }
    canonical_file_ids = set(canonical_by_file)
    records = [record for _, record in canonical_rows]

    duplicate_details = _duplicate_identifiers(canonical_rows)
    duplicate_ids = sum(len(item["objectIds"]) - 1 for item in duplicate_details)
    provenance_details = [
        {"knowledgeFileId": file_id, "paths": paths}
        for file_id, record in sorted(canonical_by_file.items())
        if (paths := _missing_provenance_paths(record))
    ]
    missing_provenance = sum(len(item["paths"]) for item in provenance_details)
    unmapped_details = _source_mapping(source_rows, canonical_file_ids)
    unmapped_sources = len(unmapped_details)

    mineru_covered = sum(
        any(item.get("sourceType") == "new_mineru" for item in record.get("provenance") or [])
        for record in records
        if record.get("contextType") != "context_only"
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
                    record
                    and record.get("contextType") != "context_only"
                    and any(
                        item.get("sourceType") == "new_mineru"
                        for item in record.get("provenance") or []
                    )
                ),
                "missingCategories": list(
                    ((record or {}).get("completeness") or {}).get("missingCategories") or []
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
        "expectedMineruCoverage": expected_mineru,
        "mineruCovered": mineru_covered,
        "expectedContextOnlyCount": expected_context_only,
        "contextOnlyCount": context_only_count,
        "duplicateIds": duplicate_ids,
        "duplicateDetails": duplicate_details,
        "missingProvenance": missing_provenance,
        "missingProvenanceDetails": provenance_details,
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
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
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
