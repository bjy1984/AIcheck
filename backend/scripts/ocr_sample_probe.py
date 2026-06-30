from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ocr_service = None


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a local OCR sample through Document Intelligence.")
    parser.add_argument("source", help="Local image/PDF path or a directory. Paths must be allowed by AICHECK_OCR_ALLOWED_LOCAL_DIRS.")
    parser.add_argument("--profile-id", default="piping_characteristic_list_v1")
    parser.add_argument("--document-type", default="engineering_table_photo")
    parser.add_argument("--min-fragments", type=int, default=1)
    parser.add_argument("--min-fields", type=int, default=0)
    parser.add_argument(
        "--require-field-code",
        action="append",
        default=[],
        help="Require an extracted fieldCode. Repeat this flag for multiple required fields.",
    )
    parser.add_argument(
        "--max-field-conflicts",
        type=int,
        help="Fail when fields with conflict quality flags exceed this value.",
    )
    parser.add_argument(
        "--max-missing-required-fields",
        type=int,
        help="Fail when quality.missingFields has more entries than this value.",
    )
    parser.add_argument("--min-tables", type=int, default=0)
    parser.add_argument(
        "--min-formal-tables",
        type=int,
        help="Fail when formal table-engine/aligned-grid table count is below this value.",
    )
    parser.add_argument(
        "--min-business-rows",
        type=int,
        help="Fail when extracted business row count is below this value.",
    )
    parser.add_argument(
        "--max-heuristic-tables",
        type=int,
        help="Fail when heuristic table fallback count exceeds this value.",
    )
    parser.add_argument(
        "--max-table-review-required",
        type=int,
        help="Fail when tables requiring manual review exceed this value.",
    )
    parser.add_argument(
        "--max-missing-required-tables",
        type=int,
        help="Fail when quality.missingTables has more entries than this value.",
    )
    parser.add_argument("--min-seals", type=int, default=0)
    parser.add_argument(
        "--min-readable-seals",
        type=int,
        help="Fail when readable OCR/formal/fragment seal text count is below this value.",
    )
    parser.add_argument(
        "--min-fragment-seals",
        type=int,
        help="Fail when visual-seal-plus-OCR-fragment fusion count is below this value.",
    )
    parser.add_argument(
        "--require-seal-type",
        action="append",
        default=[],
        help="Require a readable extracted sealType. Repeat this flag for multiple required seal types.",
    )
    parser.add_argument(
        "--max-missing-expected-seal-types",
        type=int,
        help="Fail when quality.missingExpectedSealTypes has more entries than this value.",
    )
    parser.add_argument(
        "--max-seal-review-required",
        type=int,
        help="Fail when seals requiring manual review exceed this value.",
    )
    parser.add_argument(
        "--min-engine-cache-hit-rate",
        type=float,
        help="Fail when cached eligible engine run ratio is below this value, e.g. 0.75.",
    )
    parser.add_argument(
        "--max-engine-duration-ms",
        type=int,
        help="Fail when total engine duration for a file exceeds this value.",
    )
    parser.add_argument(
        "--max-single-engine-duration-ms",
        type=int,
        help="Fail when any single available engine run exceeds this duration.",
    )
    parser.add_argument(
        "--fail-on-engine-failure",
        action="store_true",
        help="Fail when any available engine returns status=failed, even if the fused OCR result succeeds.",
    )
    parser.add_argument(
        "--min-evidence-completeness",
        type=float,
        help="Fail when quality.evidenceCompleteness is below this value, e.g. 0.95.",
    )
    parser.add_argument(
        "--max-low-confidence-fields",
        type=int,
        help="Fail when quality.lowConfidenceFields has more entries than this value.",
    )
    parser.add_argument(
        "--max-missing-evidence",
        type=int,
        help="Fail when quality.missingEvidence has more entries than this value.",
    )
    parser.add_argument("--require-quality-status", choices=["auto_usable", "needs_human_review", "failed"])
    parser.add_argument(
        "--disable-result-cache",
        action="store_true",
        help="Bypass full parse-result cache while keeping engine/variant caches available.",
    )
    parser.add_argument(
        "--disable-engine-cache",
        action="store_true",
        help="Bypass per-engine raw result cache.",
    )
    parser.add_argument(
        "--disable-variant-cache",
        action="store_true",
        help="Bypass generated preprocess variant cache.",
    )
    parser.add_argument(
        "--run-all-variants",
        action="store_true",
        help="Route every generated candidate image through eligible engines for tuning comparisons.",
    )
    parser.add_argument(
        "--auto-discover-runtime",
        action="store_true",
        help="Apply runtime-doctor recommended local OCR Python and model paths when env vars are not already set.",
    )
    parser.add_argument(
        "--no-auto-allow-source-dir",
        action="store_true",
        help="Do not add the probed local source directory to AICHECK_OCR_ALLOWED_LOCAL_DIRS for this CLI run.",
    )
    parser.add_argument("--output", help="Optional full OCR parse-result JSON output path.")
    parser.add_argument("--summary-output", help="Optional compact JSON summary output path.")
    args = parser.parse_args()
    apply_auto_discovered_runtime(args)

    source = Path(args.source)
    if not bool(getattr(args, "no_auto_allow_source_dir", False)):
        allow_probe_source_dir(source)
    if source.is_dir():
        results = [run_one(path, args) for path in sorted(source.iterdir()) if path.is_file()]
        summary = build_directory_summary(results)
        payload: dict[str, Any] | list[dict[str, Any]] = results
    else:
        result = run_one(source, args)
        summary = result["summary"]
        payload = result["result"]
    summaries = summary.get("items") if isinstance(summary.get("items"), list) else [summary]
    gate_failures = collect_gate_failures(summaries, args)
    attach_gate_failures(summary, gate_failures)

    if args.output:
        Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.summary_output:
        Path(args.summary_output).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if gate_failures:
        print("OCR sample probe failed: " + "; ".join(item["message"] for item in gate_failures), file=sys.stderr)
        return 1
    return 0


def run_one(source: Path, args: argparse.Namespace) -> dict[str, Any]:
    global ocr_service
    if ocr_service is None:
        from apps.ocr_service.service import ocr_service as loaded_ocr_service

        ocr_service = loaded_ocr_service

    result = ocr_service.parse_document(
        str(source),
        file_name=source.name,
        profile_id=args.profile_id,
        document_type=args.document_type,
        options=build_parse_options(args),
    )
    return {"source": str(source), "summary": build_summary(result, source=str(source)), "result": result}


def apply_auto_discovered_runtime(args: argparse.Namespace) -> dict[str, str]:
    if not bool(getattr(args, "auto_discover_runtime", False)):
        return {}
    from apps.ocr_service.runtime_doctor import discover_runtime_candidates, recommended_env

    recommended = recommended_env(discover_runtime_candidates())
    applied: dict[str, str] = {}
    for key, value in recommended.items():
        if os.getenv(key) or not value:
            continue
        os.environ[key] = value
        applied[key] = value
    return applied


def allow_probe_source_dir(source: Path) -> None:
    paths: list[str] = []
    try:
        resolved = source.expanduser().resolve()
    except Exception:
        return
    if resolved.is_dir():
        paths.append(str(resolved))
    else:
        paths.append(str(resolved.parent))
    os.environ["AICHECK_OCR_ALLOWED_LOCAL_DIRS"] = merge_allowed_local_dirs(
        os.getenv("AICHECK_OCR_ALLOWED_LOCAL_DIRS"),
        paths,
    )


def merge_allowed_local_dirs(existing: str | None, additions: list[str]) -> str:
    values = [item.strip() for item in (existing or "").split(",") if item.strip()]
    for item in additions:
        if item and item not in values:
            values.append(item)
    return ",".join(values)


def build_parse_options(args: argparse.Namespace) -> dict[str, Any]:
    options: dict[str, Any] = {}
    if bool(getattr(args, "disable_result_cache", False)):
        options["disableResultCache"] = True
    if bool(getattr(args, "disable_engine_cache", False)):
        options["disableEngineResultCache"] = True
    if bool(getattr(args, "disable_variant_cache", False)):
        options["disableVariantCache"] = True
    if bool(getattr(args, "run_all_variants", False)):
        options["runAllVariants"] = True
    return options


def build_summary(result: dict[str, Any], *, source: str | None = None) -> dict[str, Any]:
    quality = result.get("quality") if isinstance(result.get("quality"), dict) else {}
    missing_evidence = [item for item in quality.get("missingEvidence") or [] if isinstance(item, dict)]
    image_variants = [item for item in result.get("imageVariants") or [] if isinstance(item, dict)]
    preprocess = result.get("preprocessStatus") if isinstance(result.get("preprocessStatus"), dict) else {}
    engine_runs = [item for item in result.get("engineRuns") or [] if isinstance(item, dict)]
    engine_metrics = engine_run_metrics(engine_runs)
    engine_rows = compact_engine_runs(engine_runs)
    engine_rows_with_source = [{**item, "source": source} for item in engine_rows]
    field_metrics = field_level_metrics(result.get("fields") or [])
    missing_required_fields = [str(item) for item in quality.get("missingFields") or []]
    table_metrics = table_level_metrics(result.get("tables") or [])
    missing_required_tables = [str(item) for item in quality.get("missingTables") or []]
    seal_metrics = seal_level_metrics(result.get("seals") or [])
    missing_expected_seal_types = [str(item) for item in quality.get("missingExpectedSealTypes") or []]
    matched_expected_seal_types = [str(item) for item in quality.get("matchedSealTypes") or []]
    return {
        "source": source,
        "status": result.get("status"),
        "parseResultId": result.get("parseResultId"),
        "profileId": result.get("profileId"),
        "documentType": result.get("documentType"),
        "qualityStatus": quality.get("status"),
        "qualityReasons": quality.get("reasons") or [],
        "evidenceCompleteness": safe_float(quality.get("evidenceCompleteness")),
        "lowConfidenceFields": len(quality.get("lowConfidenceFields") or []),
        "missingEvidence": len(missing_evidence),
        "missingEvidenceByType": count_missing_evidence_by_type(missing_evidence),
        "resultCacheHit": bool(result.get("resultCacheHit")),
        "imageVariants": len(image_variants),
        "variantCacheHits": len([item for item in image_variants if item.get("cacheHit")]),
        "requestedVariants": len(preprocess.get("requestedVariants") or []),
        "generatedVariants": len(preprocess.get("generatedVariants") or []),
        "missingVariants": preprocess.get("missingVariants") or [],
        **engine_metrics,
        "pageQuality": len(result.get("pageQuality") or []),
        "fragments": len(result.get("fragments") or []),
        "fields": len(result.get("fields") or []),
        **field_metrics,
        "missingRequiredFields": sorted(set(missing_required_fields)),
        "missingRequiredFieldCount": len(missing_required_fields),
        "missingRequiredFieldCounts": count_values(missing_required_fields),
        "tables": len(result.get("tables") or []),
        **table_metrics,
        "missingRequiredTables": sorted(set(missing_required_tables)),
        "missingRequiredTableCount": len(missing_required_tables),
        "missingRequiredTableCounts": count_values(missing_required_tables),
        "seals": len(result.get("seals") or []),
        **seal_metrics,
        "matchedExpectedSealTypes": sorted(set(matched_expected_seal_types)),
        "matchedExpectedSealTypeCount": len(matched_expected_seal_types),
        "matchedExpectedSealTypeCounts": count_values(matched_expected_seal_types),
        "missingExpectedSealTypes": sorted(set(missing_expected_seal_types)),
        "missingExpectedSealTypeCount": len(missing_expected_seal_types),
        "missingExpectedSealTypeCounts": count_values(missing_expected_seal_types),
        "diagnosticCodes": [
            item.get("code") if isinstance(item, dict) else str(item)
            for item in result.get("diagnostics") or []
        ],
        "engineStatusCounts": count_engine_statuses(engine_rows),
        "failedEngineRuns": failed_engine_runs(engine_rows_with_source),
        "slowestEngineRuns": slowest_engine_runs(engine_rows_with_source),
        "engineRuns": engine_rows,
    }


def build_directory_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    summaries = [item["summary"] for item in items]
    engine_runs = []
    for item in summaries:
        for run in item.get("engineRuns", []):
            if isinstance(run, dict):
                engine_runs.append({**run, "source": item.get("source")})
    engine_metrics = engine_run_metrics(engine_runs)
    return {
        "files": len(summaries),
        "passed": len([item for item in summaries if item.get("status") == "success"]),
        "failed": len([item for item in summaries if item.get("status") != "success"]),
        "resultCacheHits": len([item for item in summaries if item.get("resultCacheHit")]),
        "variantCacheHits": sum(int(item.get("variantCacheHits") or 0) for item in summaries),
        "averageEvidenceCompleteness": round(
            sum(float(item.get("evidenceCompleteness") or 0) for item in summaries) / (len(summaries) or 1),
            4,
        ),
        "totalLowConfidenceFields": sum(int(item.get("lowConfidenceFields") or 0) for item in summaries),
        "totalMissingEvidence": sum(int(item.get("missingEvidence") or 0) for item in summaries),
        "missingEvidenceByType": merge_count_maps(
            [item.get("missingEvidenceByType") for item in summaries if isinstance(item.get("missingEvidenceByType"), dict)]
        ),
        "qualityReasonCounts": count_values(
            reason
            for item in summaries
            for reason in item.get("qualityReasons", [])
        ),
        "diagnosticCodeCounts": count_values(
            code
            for item in summaries
            for code in item.get("diagnosticCodes", [])
        ),
        "engineStatusCounts": count_engine_statuses(engine_runs),
        "failedEngineRunCount": len(failed_engine_runs(engine_runs)),
        "slowestEngineRuns": slowest_engine_runs(engine_runs),
        "slowestFiles": slowest_files(summaries),
        **engine_metrics,
        "totalFragments": sum(int(item.get("fragments") or 0) for item in summaries),
        "totalFields": sum(int(item.get("fields") or 0) for item in summaries),
        "totalFieldConflicts": sum(int(item.get("fieldConflictCount") or 0) for item in summaries),
        "totalMissingRequiredFields": sum(int(item.get("missingRequiredFieldCount") or 0) for item in summaries),
        "missingRequiredFieldCounts": merge_count_maps(
            [
                item.get("missingRequiredFieldCounts")
                for item in summaries
                if isinstance(item.get("missingRequiredFieldCounts"), dict)
            ]
        ),
        "fieldCodeCounts": merge_count_maps(
            [item.get("fieldCodeCounts") for item in summaries if isinstance(item.get("fieldCodeCounts"), dict)]
        ),
        "fieldSourceCounts": merge_count_maps(
            [item.get("fieldSourceCounts") for item in summaries if isinstance(item.get("fieldSourceCounts"), dict)]
        ),
        "fieldQualityFlagCounts": merge_count_maps(
            [item.get("fieldQualityFlagCounts") for item in summaries if isinstance(item.get("fieldQualityFlagCounts"), dict)]
        ),
        "totalTables": sum(int(item.get("tables") or 0) for item in summaries),
        "totalMissingRequiredTables": sum(int(item.get("missingRequiredTableCount") or 0) for item in summaries),
        "missingRequiredTableCounts": merge_count_maps(
            [
                item.get("missingRequiredTableCounts")
                for item in summaries
                if isinstance(item.get("missingRequiredTableCounts"), dict)
            ]
        ),
        "totalFormalTables": sum(int(item.get("formalTables") or 0) for item in summaries),
        "totalHeuristicTables": sum(int(item.get("heuristicTables") or 0) for item in summaries),
        "totalTableReviewRequired": sum(int(item.get("tableReviewRequired") or 0) for item in summaries),
        "totalBusinessRows": sum(int(item.get("businessRows") or 0) for item in summaries),
        "totalNormalizedRows": sum(int(item.get("normalizedRows") or 0) for item in summaries),
        "tableSourceCounts": merge_count_maps(
            [item.get("tableSourceCounts") for item in summaries if isinstance(item.get("tableSourceCounts"), dict)]
        ),
        "tableQualityFlagCounts": merge_count_maps(
            [item.get("tableQualityFlagCounts") for item in summaries if isinstance(item.get("tableQualityFlagCounts"), dict)]
        ),
        "totalSeals": sum(int(item.get("seals") or 0) for item in summaries),
        "totalReadableSeals": sum(int(item.get("readableSeals") or 0) for item in summaries),
        "totalFragmentSeals": sum(int(item.get("fragmentSeals") or 0) for item in summaries),
        "totalVisualCandidateSeals": sum(int(item.get("visualCandidateSeals") or 0) for item in summaries),
        "totalSealReviewRequired": sum(int(item.get("sealReviewRequired") or 0) for item in summaries),
        "totalMissingExpectedSealTypes": sum(int(item.get("missingExpectedSealTypeCount") or 0) for item in summaries),
        "matchedExpectedSealTypeCounts": merge_count_maps(
            [
                item.get("matchedExpectedSealTypeCounts")
                for item in summaries
                if isinstance(item.get("matchedExpectedSealTypeCounts"), dict)
            ]
        ),
        "missingExpectedSealTypeCounts": merge_count_maps(
            [
                item.get("missingExpectedSealTypeCounts")
                for item in summaries
                if isinstance(item.get("missingExpectedSealTypeCounts"), dict)
            ]
        ),
        "sealTypeCounts": merge_count_maps(
            [item.get("sealTypeCounts") for item in summaries if isinstance(item.get("sealTypeCounts"), dict)]
        ),
        "readableSealTypeCounts": merge_count_maps(
            [
                item.get("readableSealTypeCounts")
                for item in summaries
                if isinstance(item.get("readableSealTypeCounts"), dict)
            ]
        ),
        "sealSourceCounts": merge_count_maps(
            [item.get("sealSourceCounts") for item in summaries if isinstance(item.get("sealSourceCounts"), dict)]
        ),
        "sealQualityFlagCounts": merge_count_maps(
            [item.get("sealQualityFlagCounts") for item in summaries if isinstance(item.get("sealQualityFlagCounts"), dict)]
        ),
        "qualityStatuses": sorted({str(item.get("qualityStatus")) for item in summaries}),
        "items": summaries,
    }


def collect_gate_failures(summaries: list[dict[str, Any]], args: argparse.Namespace) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for item in summaries:
        if item.get("status") != "success":
            failures.append(
                gate_failure(item, "STATUS_NOT_SUCCESS", "status", item.get("status"), "success", comparator="eq")
            )
        if safe_int(item.get("fragments")) < int(args.min_fragments):
            failures.append(gate_failure(item, "FRAGMENTS_BELOW_MIN", "fragments", item.get("fragments"), args.min_fragments))
        if safe_int(item.get("fields")) < int(getattr(args, "min_fields", 0) or 0):
            failures.append(gate_failure(item, "FIELDS_BELOW_MIN", "fields", item.get("fields"), getattr(args, "min_fields", 0)))
        required_field_codes = [str(code) for code in (getattr(args, "require_field_code", []) or [])]
        field_codes = {str(code) for code in item.get("fieldCodes") or []}
        for field_code in required_field_codes:
            if field_code in field_codes:
                continue
            failures.append(
                gate_failure(
                    item,
                    "REQUIRED_FIELD_CODE_MISSING",
                    f"fieldCodes.{field_code}",
                    "missing",
                    "present",
                    comparator="eq",
                )
            )
        if getattr(args, "max_field_conflicts", None) is not None and safe_int(item.get("fieldConflictCount")) > int(args.max_field_conflicts):
            failures.append(
                gate_failure(
                    item,
                    "FIELD_CONFLICTS_ABOVE_MAX",
                    "fieldConflictCount",
                    item.get("fieldConflictCount"),
                    args.max_field_conflicts,
                    comparator="lte",
                )
            )
        if getattr(args, "max_missing_required_fields", None) is not None and safe_int(item.get("missingRequiredFieldCount")) > int(
            args.max_missing_required_fields
        ):
            failures.append(
                gate_failure(
                    item,
                    "MISSING_REQUIRED_FIELDS_ABOVE_MAX",
                    "missingRequiredFieldCount",
                    item.get("missingRequiredFieldCount"),
                    args.max_missing_required_fields,
                    comparator="lte",
                )
            )
        if safe_int(item.get("tables")) < int(args.min_tables):
            failures.append(gate_failure(item, "TABLES_BELOW_MIN", "tables", item.get("tables"), args.min_tables))
        if getattr(args, "min_formal_tables", None) is not None and safe_int(item.get("formalTables")) < int(args.min_formal_tables):
            failures.append(
                gate_failure(
                    item,
                    "FORMAL_TABLES_BELOW_MIN",
                    "formalTables",
                    item.get("formalTables"),
                    args.min_formal_tables,
                )
            )
        if getattr(args, "min_business_rows", None) is not None and safe_int(item.get("businessRows")) < int(args.min_business_rows):
            failures.append(
                gate_failure(
                    item,
                    "BUSINESS_ROWS_BELOW_MIN",
                    "businessRows",
                    item.get("businessRows"),
                    args.min_business_rows,
                )
            )
        if getattr(args, "max_heuristic_tables", None) is not None and safe_int(item.get("heuristicTables")) > int(args.max_heuristic_tables):
            failures.append(
                gate_failure(
                    item,
                    "HEURISTIC_TABLES_ABOVE_MAX",
                    "heuristicTables",
                    item.get("heuristicTables"),
                    args.max_heuristic_tables,
                    comparator="lte",
                )
            )
        if getattr(args, "max_table_review_required", None) is not None and safe_int(item.get("tableReviewRequired")) > int(args.max_table_review_required):
            failures.append(
                gate_failure(
                    item,
                    "TABLE_REVIEW_REQUIRED_ABOVE_MAX",
                    "tableReviewRequired",
                    item.get("tableReviewRequired"),
                    args.max_table_review_required,
                    comparator="lte",
                )
            )
        if getattr(args, "max_missing_required_tables", None) is not None and safe_int(item.get("missingRequiredTableCount")) > int(
            args.max_missing_required_tables
        ):
            failures.append(
                gate_failure(
                    item,
                    "MISSING_REQUIRED_TABLES_ABOVE_MAX",
                    "missingRequiredTableCount",
                    item.get("missingRequiredTableCount"),
                    args.max_missing_required_tables,
                    comparator="lte",
                )
            )
        if safe_int(item.get("seals")) < int(args.min_seals):
            failures.append(gate_failure(item, "SEALS_BELOW_MIN", "seals", item.get("seals"), args.min_seals))
        if getattr(args, "min_readable_seals", None) is not None and safe_int(item.get("readableSeals")) < int(args.min_readable_seals):
            failures.append(
                gate_failure(
                    item,
                    "READABLE_SEALS_BELOW_MIN",
                    "readableSeals",
                    item.get("readableSeals"),
                    args.min_readable_seals,
                )
            )
        if getattr(args, "min_fragment_seals", None) is not None and safe_int(item.get("fragmentSeals")) < int(args.min_fragment_seals):
            failures.append(
                gate_failure(
                    item,
                    "FRAGMENT_SEALS_BELOW_MIN",
                    "fragmentSeals",
                    item.get("fragmentSeals"),
                    args.min_fragment_seals,
                )
            )
        required_seal_types = [str(seal_type) for seal_type in (getattr(args, "require_seal_type", []) or [])]
        readable_seal_types = {normalize_type_key(seal_type) for seal_type in item.get("readableSealTypes") or []}
        for seal_type in required_seal_types:
            if normalize_type_key(seal_type) in readable_seal_types:
                continue
            failures.append(
                gate_failure(
                    item,
                    "REQUIRED_SEAL_TYPE_MISSING",
                    f"readableSealTypes.{seal_type}",
                    "missing",
                    "present",
                    comparator="eq",
                )
            )
        if getattr(args, "max_missing_expected_seal_types", None) is not None and safe_int(item.get("missingExpectedSealTypeCount")) > int(
            args.max_missing_expected_seal_types
        ):
            failures.append(
                gate_failure(
                    item,
                    "MISSING_EXPECTED_SEAL_TYPES_ABOVE_MAX",
                    "missingExpectedSealTypeCount",
                    item.get("missingExpectedSealTypeCount"),
                    args.max_missing_expected_seal_types,
                    comparator="lte",
                )
            )
        if getattr(args, "max_seal_review_required", None) is not None and safe_int(item.get("sealReviewRequired")) > int(args.max_seal_review_required):
            failures.append(
                gate_failure(
                    item,
                    "SEAL_REVIEW_REQUIRED_ABOVE_MAX",
                    "sealReviewRequired",
                    item.get("sealReviewRequired"),
                    args.max_seal_review_required,
                    comparator="lte",
                )
            )
        if args.min_engine_cache_hit_rate is not None and safe_float(item.get("engineCacheHitRate")) < args.min_engine_cache_hit_rate:
            failures.append(
                gate_failure(
                    item,
                    "ENGINE_CACHE_HIT_RATE_BELOW_MIN",
                    "engineCacheHitRate",
                    item.get("engineCacheHitRate"),
                    args.min_engine_cache_hit_rate,
                )
            )
        if args.max_engine_duration_ms is not None and safe_int(item.get("totalEngineDurationMs")) > args.max_engine_duration_ms:
            failures.append(
                gate_failure(
                    item,
                    "ENGINE_DURATION_ABOVE_MAX",
                    "totalEngineDurationMs",
                    item.get("totalEngineDurationMs"),
                    args.max_engine_duration_ms,
                    comparator="lte",
                )
            )
        if args.max_single_engine_duration_ms is not None:
            for run in item.get("engineRuns") or []:
                if not isinstance(run, dict) or not run.get("available"):
                    continue
                if safe_int(run.get("durationMs")) <= args.max_single_engine_duration_ms:
                    continue
                failures.append(
                    gate_failure(
                        item,
                        "SINGLE_ENGINE_DURATION_ABOVE_MAX",
                        f"engine.{run.get('engine')}.durationMs",
                        run.get("durationMs"),
                        args.max_single_engine_duration_ms,
                        comparator="lte",
                    )
                )
        if bool(getattr(args, "fail_on_engine_failure", False)):
            for run in item.get("engineRuns") or []:
                if not isinstance(run, dict) or not run.get("available"):
                    continue
                if str(run.get("status") or "") != "failed":
                    continue
                failures.append(
                    gate_failure(
                        item,
                        "ENGINE_RUN_FAILED",
                        f"engine.{run.get('engine')}.status",
                        run.get("status"),
                        "non-failed",
                        comparator="eq",
                    )
                )
        if args.require_quality_status and item.get("qualityStatus") != args.require_quality_status:
            failures.append(
                gate_failure(
                    item,
                    "QUALITY_STATUS_MISMATCH",
                    "qualityStatus",
                    item.get("qualityStatus"),
                    args.require_quality_status,
                    comparator="eq",
                )
            )
        if args.min_evidence_completeness is not None and safe_float(item.get("evidenceCompleteness")) < args.min_evidence_completeness:
            failures.append(
                gate_failure(
                    item,
                    "EVIDENCE_COMPLETENESS_BELOW_MIN",
                    "evidenceCompleteness",
                    item.get("evidenceCompleteness"),
                    args.min_evidence_completeness,
                )
            )
        if args.max_low_confidence_fields is not None and safe_int(item.get("lowConfidenceFields")) > args.max_low_confidence_fields:
            failures.append(
                gate_failure(
                    item,
                    "LOW_CONFIDENCE_FIELDS_ABOVE_MAX",
                    "lowConfidenceFields",
                    item.get("lowConfidenceFields"),
                    args.max_low_confidence_fields,
                    comparator="lte",
                )
            )
        if args.max_missing_evidence is not None and safe_int(item.get("missingEvidence")) > args.max_missing_evidence:
            failures.append(
                gate_failure(
                    item,
                    "MISSING_EVIDENCE_ABOVE_MAX",
                    "missingEvidence",
                    item.get("missingEvidence"),
                    args.max_missing_evidence,
                    comparator="lte",
                )
            )
    return failures


def gate_failure(
    item: dict[str, Any],
    code: str,
    metric: str,
    actual: Any,
    expected: Any,
    *,
    comparator: str = "gte",
) -> dict[str, Any]:
    source = item.get("source") or item.get("parseResultId") or "unknown"
    symbols = {"gte": ">=", "lte": "<=", "eq": "==", "neq": "!="}
    return {
        "source": source,
        "code": code,
        "metric": metric,
        "actual": actual,
        "expected": expected,
        "comparator": comparator,
        "message": f"{source}: {metric} {actual} {symbols.get(comparator, comparator)} {expected} failed",
    }


def attach_gate_failures(summary: dict[str, Any], gate_failures: list[dict[str, Any]]) -> None:
    if isinstance(summary.get("items"), list):
        by_source: dict[str, list[dict[str, Any]]] = {}
        for failure in gate_failures:
            by_source.setdefault(str(failure.get("source") or "unknown"), []).append(failure)
        for item in summary["items"]:
            if not isinstance(item, dict):
                continue
            source = str(item.get("source") or item.get("parseResultId") or "unknown")
            item_failures = by_source.get(source, [])
            item["gatePassed"] = not item_failures
            item["gateFailures"] = item_failures
        summary["gatePassed"] = not gate_failures
        summary["gateFailures"] = gate_failures
        summary["gateFailureCounts"] = count_values(failure.get("code") for failure in gate_failures)
        return
    summary["gatePassed"] = not gate_failures
    summary["gateFailures"] = gate_failures
    summary["gateFailureCounts"] = count_values(failure.get("code") for failure in gate_failures)


def engine_run_metrics(engine_runs: list[dict[str, Any]]) -> dict[str, Any]:
    eligible_runs = [
        run
        for run in engine_runs
        if str(run.get("status") or "") == "success" and run.get("engine") != "ocr_result_cache"
    ]
    engine_cache_hits = len([run for run in eligible_runs if run.get("engineCacheHit")])
    total_duration = sum(safe_int(run.get("durationMs")) for run in engine_runs)
    return {
        "engineRunCount": len(engine_runs),
        "eligibleEngineRunCount": len(eligible_runs),
        "engineCacheHits": engine_cache_hits,
        "engineCacheHitRate": round(engine_cache_hits / (len(eligible_runs) or 1), 4),
        "totalEngineDurationMs": total_duration,
    }


def compact_engine_runs(engine_runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "engine": item.get("engine"),
            "status": item.get("status"),
            "available": item.get("available"),
            "durationMs": item.get("durationMs"),
            "variantId": item.get("variantId"),
            "variantCacheHit": item.get("variantCacheHit"),
            "engineCacheHit": item.get("engineCacheHit"),
            "workerMode": item.get("workerMode"),
        }
        for item in engine_runs
    ]


def failed_engine_runs(engine_runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "source": item.get("source"),
            "engine": item.get("engine"),
            "status": item.get("status"),
            "durationMs": safe_int(item.get("durationMs")),
            "variantId": item.get("variantId"),
        }
        for item in engine_runs
        if item.get("available") and str(item.get("status") or "") == "failed"
    ]


def slowest_engine_runs(engine_runs: list[dict[str, Any]], *, limit: int = 8) -> list[dict[str, Any]]:
    rows = [
        {
            "source": item.get("source"),
            "engine": item.get("engine"),
            "status": item.get("status"),
            "available": item.get("available"),
            "durationMs": safe_int(item.get("durationMs")),
            "variantId": item.get("variantId"),
            "engineCacheHit": item.get("engineCacheHit"),
        }
        for item in engine_runs
        if item.get("available")
    ]
    return sorted(rows, key=lambda item: item["durationMs"], reverse=True)[:limit]


def count_values(values: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value or "unknown")
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def count_engine_statuses(engine_runs: list[dict[str, Any]]) -> dict[str, int]:
    return count_values(
        f"{run.get('engine') or 'unknown'}:{run.get('status') or 'unknown'}"
        for run in engine_runs
    )


def slowest_files(summaries: list[dict[str, Any]], *, limit: int = 8) -> list[dict[str, Any]]:
    rows = [
        {
            "source": item.get("source"),
            "status": item.get("status"),
            "qualityStatus": item.get("qualityStatus"),
            "totalEngineDurationMs": safe_int(item.get("totalEngineDurationMs")),
            "fragments": safe_int(item.get("fragments")),
            "fields": safe_int(item.get("fields")),
            "fieldConflictCount": safe_int(item.get("fieldConflictCount")),
            "missingRequiredFieldCount": safe_int(item.get("missingRequiredFieldCount")),
            "tables": safe_int(item.get("tables")),
            "missingRequiredTableCount": safe_int(item.get("missingRequiredTableCount")),
            "formalTables": safe_int(item.get("formalTables")),
            "heuristicTables": safe_int(item.get("heuristicTables")),
            "businessRows": safe_int(item.get("businessRows")),
            "tableReviewRequired": safe_int(item.get("tableReviewRequired")),
            "seals": safe_int(item.get("seals")),
            "readableSeals": safe_int(item.get("readableSeals")),
            "fragmentSeals": safe_int(item.get("fragmentSeals")),
            "missingExpectedSealTypeCount": safe_int(item.get("missingExpectedSealTypeCount")),
            "sealReviewRequired": safe_int(item.get("sealReviewRequired")),
        }
        for item in summaries
    ]
    return sorted(rows, key=lambda item: item["totalEngineDurationMs"], reverse=True)[:limit]


def field_level_metrics(fields: Any) -> dict[str, Any]:
    field_items = [field for field in fields if isinstance(field, dict)] if isinstance(fields, list) else []
    code_counts: dict[str, int] = {}
    source_counts: dict[str, int] = {}
    flag_counts: dict[str, int] = {}
    conflict_count = 0
    confidence_values: list[float] = []
    for field in field_items:
        code = field_code_for(field)
        source = str(field.get("sourceEngine") or field.get("source") or "unknown")
        flags = [str(flag) for flag in field.get("qualityFlags") or []]
        code_counts[code] = code_counts.get(code, 0) + 1
        source_counts[source] = source_counts.get(source, 0) + 1
        has_conflict = False
        for flag in flags:
            flag_counts[flag] = flag_counts.get(flag, 0) + 1
            if "conflict" in flag.lower():
                has_conflict = True
        if has_conflict:
            conflict_count += 1
        confidence_values.append(safe_float(field.get("confidence")))
    known_codes = sorted(code for code in code_counts if code != "unknown")
    return {
        "fieldCodes": known_codes,
        "fieldCodeCounts": dict(sorted(code_counts.items(), key=lambda item: (-item[1], item[0]))),
        "fieldSourceCounts": dict(sorted(source_counts.items(), key=lambda item: (-item[1], item[0]))),
        "fieldQualityFlagCounts": dict(sorted(flag_counts.items(), key=lambda item: (-item[1], item[0]))),
        "fieldConflictCount": conflict_count,
        "averageFieldConfidence": round(sum(confidence_values) / (len(confidence_values) or 1), 4),
    }


def field_code_for(field: dict[str, Any]) -> str:
    return str(field.get("fieldCode") or field.get("fieldName") or field.get("name") or "unknown")


def table_level_metrics(tables: Any) -> dict[str, Any]:
    table_items = [table for table in tables if isinstance(table, dict)] if isinstance(tables, list) else []
    source_counts: dict[str, int] = {}
    flag_counts: dict[str, int] = {}
    formal = 0
    heuristic = 0
    review_required = 0
    business_rows = 0
    normalized_rows = 0
    cell_count = 0
    confidence_values: list[float] = []
    for table in table_items:
        flags = [str(flag) for flag in table.get("qualityFlags") or []]
        source = str(table.get("sourceEngine") or table.get("source") or "unknown")
        source_counts[source] = source_counts.get(source, 0) + 1
        for flag in flags:
            flag_counts[flag] = flag_counts.get(flag, 0) + 1
        confidence_values.append(safe_float(table.get("structureConfidence") or table.get("confidence")))
        if table_is_heuristic(table):
            heuristic += 1
        else:
            formal += 1
        if any(quality_flag_requires_review(flag) for flag in flags):
            review_required += 1
        business_rows += len([row for row in table.get("businessRows") or [] if isinstance(row, dict)])
        normalized_rows += len([row for row in table.get("normalizedRows") or [] if isinstance(row, dict)])
        cell_count += len([cell for cell in table.get("cells") or [] if isinstance(cell, dict)])
    total = len(table_items)
    return {
        "formalTables": formal,
        "heuristicTables": heuristic,
        "tableReviewRequired": review_required,
        "businessRows": business_rows,
        "normalizedRows": normalized_rows,
        "tableCells": cell_count,
        "averageTableConfidence": round(sum(confidence_values) / (len(confidence_values) or 1), 4),
        "formalTableRate": round(formal / (total or 1), 4),
        "heuristicTableRate": round(heuristic / (total or 1), 4),
        "tableReviewRequiredRate": round(review_required / (total or 1), 4),
        "tableSourceCounts": dict(sorted(source_counts.items(), key=lambda item: (-item[1], item[0]))),
        "tableQualityFlagCounts": dict(sorted(flag_counts.items(), key=lambda item: (-item[1], item[0]))),
    }


def table_is_heuristic(table: dict[str, Any]) -> bool:
    source = str(table.get("sourceEngine") or "")
    flags = {str(flag) for flag in table.get("qualityFlags") or []}
    return source.startswith("heuristic_") or "heuristic_table_fallback" in flags


def seal_level_metrics(seals: Any) -> dict[str, Any]:
    seal_items = [seal for seal in seals if isinstance(seal, dict)] if isinstance(seals, list) else []
    source_counts: dict[str, int] = {}
    flag_counts: dict[str, int] = {}
    type_counts: dict[str, int] = {}
    readable_type_counts: dict[str, int] = {}
    readable = 0
    fragment = 0
    visual = 0
    review_required = 0
    missing_text = 0
    confidence_values: list[float] = []
    for seal in seal_items:
        flags = [str(flag) for flag in seal.get("qualityFlags") or []]
        source = str(seal.get("sourceEngine") or seal.get("source") or "unknown")
        seal_type = str(seal.get("sealType") or "unknown")
        source_counts[source] = source_counts.get(source, 0) + 1
        type_counts[seal_type] = type_counts.get(seal_type, 0) + 1
        for flag in flags:
            flag_counts[flag] = flag_counts.get(flag, 0) + 1
        confidence_values.append(safe_float(seal.get("ocrConfidence") or seal.get("visualConfidence")))
        if seal_is_visual_candidate(seal):
            visual += 1
        if seal_text_is_readable(seal):
            readable += 1
            readable_type_counts[seal_type] = readable_type_counts.get(seal_type, 0) + 1
        if "fragment_seal_text" in flags or source == "fragment_seal_text_fusion":
            fragment += 1
        if any(quality_flag_requires_review(flag) for flag in flags):
            review_required += 1
        if seal_is_visual_candidate(seal) and not seal_text_is_readable(seal):
            missing_text += 1
    total = len(seal_items)
    return {
        "readableSeals": readable,
        "fragmentSeals": fragment,
        "visualCandidateSeals": visual,
        "sealReviewRequired": review_required,
        "missingSealText": missing_text,
        "averageSealConfidence": round(sum(confidence_values) / (len(confidence_values) or 1), 4),
        "readableSealRate": round(readable / (total or 1), 4),
        "fragmentSealRate": round(fragment / (total or 1), 4),
        "visualSealReviewRate": round(review_required / (visual or 1), 4),
        "sealTypes": sorted(key for key in type_counts if key != "unknown"),
        "readableSealTypes": sorted(key for key in readable_type_counts if key != "unknown"),
        "sealTypeCounts": dict(sorted(type_counts.items(), key=lambda item: (-item[1], item[0]))),
        "readableSealTypeCounts": dict(sorted(readable_type_counts.items(), key=lambda item: (-item[1], item[0]))),
        "sealSourceCounts": dict(sorted(source_counts.items(), key=lambda item: (-item[1], item[0]))),
        "sealQualityFlagCounts": dict(sorted(flag_counts.items(), key=lambda item: (-item[1], item[0]))),
    }


def seal_is_visual_candidate(seal: dict[str, Any]) -> bool:
    flags = {str(flag) for flag in seal.get("qualityFlags") or []}
    seal_type = str(seal.get("sealType") or "")
    seal_name = str(seal.get("sealName") or "")
    return "visual_candidate_only" in flags or seal_type.startswith("visual_") or seal_name.startswith("视觉")


def seal_text_is_readable(seal: dict[str, Any]) -> bool:
    if seal_is_visual_candidate(seal):
        return False
    seal_name = str(seal.get("sealName") or "").strip()
    if not seal_name:
        return False
    return safe_float(seal.get("ocrConfidence")) >= 0.65


def quality_flag_requires_review(flag: Any) -> bool:
    normalized = str(flag or "").lower()
    return any(
        token in normalized
        for token in ["missing", "requires", "review", "low_confidence", "conflict", "fallback", "failed", "timeout"]
    )


def normalize_type_key(value: Any) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")
    aliases = {
        "pressure_pipe_design_license_seal": "design_license_seal",
        "special_equipment_design_permit_seal": "design_license_seal",
        "special_equipment_design_license_seal": "design_license_seal",
        "design_permit_seal": "design_license_seal",
        "design_approval_seal": "drawing_approval_seal",
        "testing_seal": "inspection_testing_seal",
        "inspection_seal": "inspection_testing_seal",
        "quality_certificate_seal": "quality_seal",
    }
    return aliases.get(normalized, normalized)


def count_missing_evidence_by_type(items: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        target_type = str(item.get("targetType") or "unknown")
        counts[target_type] = counts.get(target_type, 0) + 1
    return counts


def merge_count_maps(items: list[dict[str, Any]]) -> dict[str, int]:
    merged: dict[str, int] = {}
    for item in items:
        for key, value in item.items():
            merged[str(key)] = merged.get(str(key), 0) + safe_int(value)
    return merged


def safe_float(value: Any) -> float:
    try:
        return round(float(value or 0), 4)
    except (TypeError, ValueError):
        return 0.0


def safe_int(value: Any) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
