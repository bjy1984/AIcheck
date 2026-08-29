#!/usr/bin/env python3
"""Ground missing canonical standard semantics without mutating source collections."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import psycopg
from psycopg.types.json import Jsonb


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from libs.integrations.litellm_client import LiteLLMClient  # noqa: E402
from libs.security.tenant import configured_tenant_id  # noqa: E402
from libs.standard_knowledge_canonical import (  # noqa: E402
    canonical_semantic_selected_values_hash,
    merge_canonical_semantic_candidates,
)
from libs.standard_semantic_extraction import (  # noqa: E402
    MODEL_ROUTE,
    PROMPT_VERSION,
    extract_standard_semantics,
    semantic_extraction_hashes,
    semantic_field_names,
)


CANONICAL_COLLECTION = "standard_knowledge_records"
_SEMANTIC_CATEGORY_FIELDS = {
    "identity": {
        "standardCode",
        "standardNameZh",
        "standardNameEn",
    },
    "version": {
        "publicationDate",
        "effectiveDate",
        "issuingAuthority",
        "proposingOrganization",
        "administeringOrganization",
        "draftingOrganizations",
        "draftingPeople",
    },
    "metadata": {
        "scope",
        "purpose",
        "applicability",
        "keywords",
        "abstract",
        "foreword",
        "introduction",
        "termsAndDefinitionsSummary",
    },
    "normativeReferences": {"normativeReferences"},
    "replacementRelations": {"replacementRelations"},
}


def _load_canonical_records(
    connection: psycopg.Connection[Any],
    tenant_id: str,
    *,
    file_id: str | None,
) -> list[dict[str, Any]]:
    params: list[Any] = [tenant_id]
    file_filter = ""
    if file_id:
        file_filter = " AND object_id=%s"
        params.append(file_id)
    rows = connection.execute(
        f"""
        SELECT object_id, payload FROM aicheck_state
        WHERE tenant_id=%s
          AND collection='standard_knowledge_records'
          {file_filter}
        ORDER BY object_id
        """,  # noqa: S608 - only a fixed optional SQL fragment is interpolated
        params,
    ).fetchall()
    return [
        {"objectId": str(object_id), "record": dict(payload)}
        for object_id, payload in rows
        if isinstance(payload, dict)
    ]


def semantic_fields_for_record(record: dict[str, Any], *, only_missing: bool) -> set[str]:
    if not only_missing:
        return set(semantic_field_names())
    completeness = record.get("completeness")
    if not isinstance(completeness, dict):
        return set(semantic_field_names())
    named_missing = {str(value) for value in completeness.get("missingCategories") or []}
    requested: set[str] = set()
    for category, fields in _SEMANTIC_CATEGORY_FIELDS.items():
        detail = completeness.get(category)
        status = str(detail.get("status") or "") if isinstance(detail, dict) else ""
        if status in {"partial", "missing"} or category in named_missing:
            requested.update(fields)
    return requested


def _matching_extraction_hashes(record: dict[str, Any], hashes: dict[str, str]) -> bool:
    selected_values_hash = str(record.get("semanticSelectedValuesHash") or "")
    return (
        record.get("semanticExtractionVersion") == PROMPT_VERSION
        and record.get("semanticModelRoute") == MODEL_ROUTE
        and record.get("semanticPromptHash") == hashes["promptHash"]
        and record.get("semanticContentHash") == hashes["contentHash"]
        and bool(selected_values_hash)
        and selected_values_hash == canonical_semantic_selected_values_hash(record)
    )


def _persist_semantics(
    connection: psycopg.Connection[Any],
    tenant_id: str,
    *,
    object_id: str,
    expected_source_fingerprint: str,
    semantics: dict[str, Any],
    extracted_at: str,
) -> tuple[Literal["updated", "unchanged", "stale", "missing"], dict[str, Any] | None]:
    with connection.transaction():
        row = connection.execute(
            """
            SELECT payload FROM aicheck_state
            WHERE tenant_id=%s
              AND collection='standard_knowledge_records'
              AND object_id=%s
            FOR UPDATE
            """,
            (tenant_id, object_id),
        ).fetchone()
        if not row or not isinstance(row[0], dict):
            return "missing", None
        current = dict(row[0])
        if str(current.get("sourceFingerprint") or "") != expected_source_fingerprint:
            return "stale", current
        hashes = {
            "promptHash": str(semantics.get("promptHash") or ""),
            "contentHash": str(semantics.get("contentHash") or ""),
        }
        if _matching_extraction_hashes(current, hashes):
            return "unchanged", current
        enriched = merge_canonical_semantic_candidates(
            current,
            semantics,
            extracted_at=extracted_at,
        )
        connection.execute(
            """
            UPDATE aicheck_state
            SET payload=%s, updated_at=now()
            WHERE tenant_id=%s
              AND collection='standard_knowledge_records'
              AND object_id=%s
            """,
            (Jsonb(enriched), tenant_id, object_id),
        )
        return "updated", enriched


def enrich(
    database_url: str,
    *,
    apply: bool,
    file_id: str | None = None,
    only_missing: bool = False,
    client: LiteLLMClient | None = None,
) -> dict[str, Any]:
    tenant_id = configured_tenant_id()
    model_client = client
    counts = {
        "planned": 0,
        "updated": 0,
        "unchanged": 0,
        "notMissing": 0,
        "contextOnlySkipped": 0,
        "stale": 0,
        "missing": 0,
        "failed": 0,
        "modelCalls": 0,
    }
    summaries: list[dict[str, Any]] = []
    with psycopg.connect(database_url, autocommit=True) as connection:
        selected = _load_canonical_records(
            connection,
            tenant_id,
            file_id=file_id,
        )
        processed = 0
        if file_id and not selected:
            counts["missing"] = 1
            summaries.append(
                {
                    "knowledgeFileId": file_id,
                    "action": "missing",
                    "errorCode": "CANONICAL_TARGET_NOT_FOUND",
                }
            )
        for entry in selected:
            object_id = entry["objectId"]
            record = entry["record"]
            if record.get("contextType") == "context_only":
                counts["contextOnlySkipped"] += 1
                summaries.append({"knowledgeFileId": object_id, "action": "context_only"})
                continue
            processed += 1
            requested_fields = semantic_fields_for_record(
                record,
                only_missing=only_missing,
            )
            if not requested_fields:
                counts["notMissing"] += 1
                summaries.append({"knowledgeFileId": object_id, "action": "not_missing"})
                continue
            try:
                hashes = semantic_extraction_hashes(
                    record,
                    requested_fields=requested_fields,
                )
                if _matching_extraction_hashes(record, hashes):
                    counts["unchanged"] += 1
                    summaries.append(
                        {
                            "knowledgeFileId": object_id,
                            "action": "unchanged",
                            **hashes,
                        }
                    )
                    continue
                counts["modelCalls"] += 1
                if model_client is None:
                    model_client = LiteLLMClient()
                semantics = extract_standard_semantics(
                    record,
                    model_client,
                    requested_fields=requested_fields,
                )
                extracted_at = datetime.now(UTC).isoformat()
                if not apply:
                    enriched = merge_canonical_semantic_candidates(
                        record,
                        semantics,
                        extracted_at=extracted_at,
                    )
                    counts["planned"] += 1
                    summaries.append(
                        {
                            "knowledgeFileId": object_id,
                            "action": "planned",
                            "sourceFingerprint": record.get("sourceFingerprint"),
                            "promptHash": semantics.get("promptHash"),
                            "contentHash": semantics.get("contentHash"),
                            "missingCategories": list(
                                (enriched.get("completeness") or {}).get("missingCategories") or []
                            ),
                        }
                    )
                    continue
                action, enriched = _persist_semantics(
                    connection,
                    tenant_id,
                    object_id=object_id,
                    expected_source_fingerprint=str(record.get("sourceFingerprint") or ""),
                    semantics=semantics,
                    extracted_at=extracted_at,
                )
                counts[action] += 1
                summaries.append(
                    {
                        "knowledgeFileId": object_id,
                        "action": action,
                        "sourceFingerprint": (enriched or record).get("sourceFingerprint"),
                        "promptHash": semantics.get("promptHash"),
                        "contentHash": semantics.get("contentHash"),
                    }
                )
            except Exception as exc:  # noqa: BLE001 - standards commit independently
                counts["failed"] += 1
                summaries.append(
                    {
                        "knowledgeFileId": object_id,
                        "action": "failed",
                        "errorCode": "SEMANTIC_ENRICHMENT_FAILED",
                        "errorType": type(exc).__name__,
                    }
                )
    return {
        "schemaVersion": "standard-canonical-semantic-enrichment-report@1",
        "generatedAt": datetime.now(UTC).isoformat(),
        "mode": "apply" if apply else "dry-run",
        "tenantId": tenant_id,
        "onlyMissing": only_missing,
        "selected": len(selected),
        "processed": processed,
        **counts,
        "records": summaries,
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default=os.getenv("AICHECK_DATABASE_URL") or os.getenv("DATABASE_URL") or "",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--file-id")
    parser.add_argument("--only-missing", action="store_true")
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.database_url:
        raise SystemExit("AICHECK_DATABASE_URL or --database-url is required")
    report = enrich(
        args.database_url,
        apply=bool(args.apply),
        file_id=args.file_id,
        only_missing=bool(args.only_missing),
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 1 if report["failed"] or report["stale"] or report["missing"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
