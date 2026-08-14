from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.ocr_100_annotation_export import resolve_tasks_path
from scripts.ocr_100_corpus import expected_evidence_failures, has_evidence
from scripts.ocr_eval_set import write_text_file

ParseRunner = Callable[[dict[str, Any]], dict[str, Any]]


def apply_auto_discovered_runtime() -> dict[str, str]:
    from apps.ocr_service.runtime_doctor import discover_runtime_candidates, recommended_env

    applied: dict[str, str] = {}
    for key, value in recommended_env(discover_runtime_candidates()).items():
        if value and not os.getenv(key):
            os.environ[key] = str(value)
            applied[key] = str(value)
    return applied


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate machine OCR prelabels for an OCR 100 annotation pack.")
    parser.add_argument("annotation_tasks", help="annotation_tasks.json file or annotation pack directory.")
    parser.add_argument("--output", required=True, help="Output prelabelled annotation_tasks.json path.")
    parser.add_argument("--source-base-dir", default=".", help="Base directory for relative sourcePath values.")
    parser.add_argument("--result-dir", help="Optional directory with precomputed OCR result JSON files keyed by caseId.")
    parser.add_argument("--save-result-dir", help="Optional directory where raw OCR/prelabel parse result JSON files are written per caseId.")
    parser.add_argument("--run-ocr", action="store_true", help="Run local OCR when no precomputed result is available.")
    parser.add_argument("--disable-result-cache", action="store_true", help="Bypass OCR result cache when --run-ocr is used.")
    parser.add_argument("--disable-remediation", action="store_true", help="Skip second-pass OCR remediation during batch prelabel retries.")
    parser.add_argument("--retry-fast-timeouts", action="store_true", help="Apply shorter OCR engine subprocess timeouts for retry batches.")
    parser.add_argument("--engine-timeout-seconds", type=float, default=60.0, help="Timeout value used with --retry-fast-timeouts.")
    parser.add_argument("--auto-discover-runtime", action="store_true", help="Apply runtime-doctor recommended OCR subprocess/model paths before running local OCR.")
    parser.add_argument("--prefer-previews", action="store_true", default=True, help="Use rendered preview images when available so prelabels share annotator pixel coordinates.")
    parser.add_argument("--max-fields", type=int, default=12)
    parser.add_argument("--max-tables", type=int, default=5)
    parser.add_argument("--max-seals", type=int, default=5)
    parser.add_argument("--case-id", action="append", default=[], help="Only prelabel selected caseId values. Repeatable.")
    parser.add_argument("--limit", type=int, help="Maximum number of tasks to prelabel after filtering.")
    args = parser.parse_args()

    applied_runtime = apply_auto_discovered_runtime() if args.auto_discover_runtime else {}
    report = prelabel_annotation_tasks(
        Path(args.annotation_tasks),
        output_path=Path(args.output),
        source_base_dir=Path(args.source_base_dir),
        result_dir=Path(args.result_dir) if args.result_dir else None,
        save_result_dir=Path(args.save_result_dir) if args.save_result_dir else None,
        run_ocr=bool(args.run_ocr),
        disable_result_cache=bool(args.disable_result_cache),
        disable_remediation=bool(args.disable_remediation),
        engine_timeout_seconds=float(args.engine_timeout_seconds) if args.retry_fast_timeouts else None,
        prefer_previews=bool(args.prefer_previews),
        max_fields=max(1, int(args.max_fields)),
        max_tables=max(1, int(args.max_tables)),
        max_seals=max(1, int(args.max_seals)),
        case_ids=args.case_id,
        limit=args.limit,
    )
    if applied_runtime:
        report["summary"]["appliedAutoDiscoveredRuntime"] = applied_runtime
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


def prelabel_annotation_tasks(
    annotation_tasks: Path,
    *,
    output_path: Path,
    source_base_dir: Path,
    result_dir: Path | None = None,
    save_result_dir: Path | None = None,
    run_ocr: bool = False,
    disable_result_cache: bool = False,
    disable_remediation: bool = False,
    engine_timeout_seconds: float | None = None,
    prefer_previews: bool = True,
    max_fields: int = 12,
    max_tables: int = 5,
    max_seals: int = 5,
    case_ids: list[str] | None = None,
    limit: int | None = None,
    parse_runner: ParseRunner | None = None,
) -> dict[str, Any]:
    tasks_path = resolve_tasks_path(annotation_tasks)
    payload = json.loads(tasks_path.read_text(encoding="utf-8"))
    tasks = payload.get("tasks") if isinstance(payload, dict) else payload
    if not isinstance(tasks, list):
        raise ValueError("annotation tasks must be a JSON object with tasks[] or a raw task list.")
    source_base_dir = source_base_dir.expanduser().resolve()
    pack_dir = tasks_path.parent
    result_dir = result_dir.expanduser().resolve() if result_dir else None
    save_result_dir = save_result_dir.expanduser().resolve() if save_result_dir else None
    if save_result_dir:
        save_result_dir.mkdir(parents=True, exist_ok=True)
    selected_case_ids = {str(item) for item in case_ids or []}
    filtered_tasks = [
        task
        for task in tasks
        if isinstance(task, dict)
        and (not selected_case_ids or str(task.get("caseId") or task.get("taskId") or "") in selected_case_ids)
    ]
    if limit is not None:
        filtered_tasks = filtered_tasks[: max(0, int(limit))]
    prelabelled: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    for task in filtered_tasks:
        if not isinstance(task, dict):
            continue
        updated = json.loads(json.dumps(task, ensure_ascii=False))
        case_id = str(updated.get("caseId") or updated.get("taskId") or "unknown")
        parse_result, event = parse_result_for_task(
            updated,
            pack_dir=pack_dir,
            source_base_dir=source_base_dir,
            result_dir=result_dir,
            run_ocr=run_ocr,
            prefer_previews=prefer_previews,
            disable_result_cache=disable_result_cache,
            disable_remediation=disable_remediation,
            engine_timeout_seconds=engine_timeout_seconds,
            parse_runner=parse_runner,
        )
        event_record = {"caseId": case_id, **event}
        if save_result_dir is not None:
            saved_path = save_parse_artifact(
                save_result_dir,
                case_id=case_id,
                parse_result=parse_result,
                event=event,
            )
            event_record["savedResultPath"] = str(saved_path)
        events.append(event_record)
        if parse_result is not None:
            suggested = suggested_expected_from_result(
                parse_result,
                max_fields=max_fields,
                max_tables=max_tables,
                max_seals=max_seals,
            )
            blockers = prelabel_blockers(suggested)
            updated["suggestedExpected"] = suggested
            updated["prelabelStatus"] = "suggested" if suggested_has_content(suggested) else "empty"
            updated["prelabelSummary"] = {
                "source": event.get("source"),
                "status": parse_result.get("status"),
                "fieldSuggestions": len(suggested.get("fields") or []),
                "tableSuggestions": len(suggested.get("tables") or []),
                "sealSuggestions": len(suggested.get("seals") or []),
                "blockers": blockers,
                "generatedAt": datetime.now(UTC).isoformat(),
            }
        else:
            updated["prelabelStatus"] = "unavailable"
            updated["prelabelSummary"] = {"source": event.get("source"), "error": event.get("error"), "generatedAt": datetime.now(UTC).isoformat()}
        prelabelled.append(updated)
    output_payload = {**payload, "tasks": prelabelled} if isinstance(payload, dict) else {"tasks": prelabelled}
    output_payload["prelabelSummary"] = {
        "schemaVersion": "aicheck-ocr-100-prelabel-report-v1",
        "generatedAt": datetime.now(UTC).isoformat(),
        "sourceTasks": len(tasks),
        "tasks": len(prelabelled),
        "selectedCaseIds": sorted(selected_case_ids),
        "suggested": len([task for task in prelabelled if task.get("prelabelStatus") == "suggested"]),
        "empty": len([task for task in prelabelled if task.get("prelabelStatus") == "empty"]),
        "unavailable": len([task for task in prelabelled if task.get("prelabelStatus") == "unavailable"]),
        "events": events,
        "engineTimeoutSeconds": engine_timeout_seconds,
        "disableRemediation": bool(disable_remediation),
    }
    write_text_file(output_path, json.dumps(output_payload, ensure_ascii=False, indent=2))
    return {"ok": True, "summary": output_payload["prelabelSummary"], "tasks": prelabelled}


def save_parse_artifact(
    save_result_dir: Path,
    *,
    case_id: str,
    parse_result: dict[str, Any] | None,
    event: dict[str, Any],
) -> Path:
    path = save_result_dir / f"{safe_name(case_id)}.json"
    payload = parse_result if parse_result is not None else failed_parse_artifact(case_id=case_id, event=event)
    write_text_file(path, json.dumps(payload, ensure_ascii=False, indent=2))
    return path


def failed_parse_artifact(*, case_id: str, event: dict[str, Any]) -> dict[str, Any]:
    error = str(event.get("error") or "prelabel_unavailable")
    return {
        "caseId": case_id,
        "status": "failed",
        "fileName": Path(str(event.get("sourcePath") or case_id)).name,
        "sourcePath": event.get("sourcePath"),
        "diagnostics": [
            {
                "code": "OCR_PRELABEL_FAILED",
                "level": "error",
                "message": error,
                "source": event.get("source"),
            }
        ],
        "prelabelEvent": event,
    }


def parse_result_for_task(
    task: dict[str, Any],
    *,
    pack_dir: Path,
    source_base_dir: Path,
    result_dir: Path | None,
    run_ocr: bool,
    prefer_previews: bool,
    disable_result_cache: bool,
    disable_remediation: bool,
    engine_timeout_seconds: float | None,
    parse_runner: ParseRunner | None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    case_id = str(task.get("caseId") or task.get("taskId") or "unknown")
    embedded = task.get("parseResult")
    if isinstance(embedded, dict):
        return embedded, {"source": "embedded_parse_result"}
    result_path = result_path_for_case(case_id, result_dir=result_dir)
    if result_path and result_path.exists():
        return json.loads(result_path.read_text(encoding="utf-8")), {"source": "result_dir", "resultPath": str(result_path)}
    if not run_ocr and parse_runner is None:
        return None, {"source": "none", "error": "no_result_and_run_ocr_disabled"}
    source_path = task_source_path(task, pack_dir=pack_dir, source_base_dir=source_base_dir, prefer_previews=prefer_previews)
    if not source_path.exists():
        return None, {"source": "local_ocr", "error": "source_missing", "sourcePath": str(source_path)}
    parse_case = {
        "caseId": case_id,
        "source": str(source_path),
        "fileName": source_path.name,
        "profileId": task.get("profileId"),
        "documentType": task.get("documentType"),
        "options": {
            "disableResultCache": bool(disable_result_cache),
            "disableRemediation": bool(disable_remediation),
        },
    }
    try:
        with temporary_engine_timeouts(engine_timeout_seconds):
            result = parse_runner(parse_case) if parse_runner else run_local_ocr(parse_case, source_base_dir=source_base_dir)
        return result, {"source": "local_ocr", "sourcePath": str(source_path)}
    except Exception as exc:
        return None, {"source": "local_ocr", "sourcePath": str(source_path), "error": exc.__class__.__name__}


def result_path_for_case(case_id: str, *, result_dir: Path | None) -> Path | None:
    if result_dir is None:
        return None
    for name in [f"{case_id}.json", f"{safe_name(case_id)}.json"]:
        path = result_dir / name
        if path.exists():
            return path
    return None


def task_source_path(task: dict[str, Any], *, pack_dir: Path, source_base_dir: Path, prefer_previews: bool) -> Path:
    if prefer_previews:
        previews = [item for item in task.get("previewPaths") or [] if isinstance(item, str) and item.strip()]
        if previews:
            preview = Path(previews[0]).expanduser()
            return preview if preview.is_absolute() else (pack_dir / preview).resolve()
    source_path = Path(str(task.get("sourcePath") or "")).expanduser()
    return source_path if source_path.is_absolute() else (source_base_dir / source_path).resolve()


def run_local_ocr(case: dict[str, Any], *, source_base_dir: Path) -> dict[str, Any]:
    os.environ["AICHECK_OCR_ALLOWED_LOCAL_DIRS"] = merge_allowed_local_dirs(
        os.getenv("AICHECK_OCR_ALLOWED_LOCAL_DIRS"),
        [str(source_base_dir), str(Path(case["source"]).resolve().parent)],
    )
    from apps.ocr_service.service import ocr_service

    return ocr_service.parse_document(
        str(case["source"]),
        file_name=case.get("fileName"),
        profile_id=case.get("profileId"),
        document_type=case.get("documentType"),
        options=case.get("options") if isinstance(case.get("options"), dict) else {},
    )


def merge_allowed_local_dirs(existing: str | None, additions: list[str]) -> str:
    values = [item.strip() for item in (existing or "").split(",") if item.strip()]
    for item in additions:
        if item and item not in values:
            values.append(item)
    return ",".join(values)


@contextlib.contextmanager
def temporary_engine_timeouts(timeout_seconds: float | None):
    if not timeout_seconds or timeout_seconds <= 0:
        yield
        return
    timeout = str(float(timeout_seconds))
    shorter = str(float(max(10.0, min(float(timeout_seconds), 45.0))))
    keys = {
        "AICHECK_OCR_SUBPROCESS_TIMEOUT": timeout,
        "AICHECK_OCR_PERSISTENT_WORKER_TIMEOUT": timeout,
        "AICHECK_PP_STRUCTURE_TIMEOUT": timeout,
        "AICHECK_DOCLING_TIMEOUT": timeout,
        "AICHECK_PADDLEOCR_VL_TIMEOUT": timeout,
        "AICHECK_PADDLEX_SEAL_TIMEOUT": shorter,
        "AICHECK_AGENTDESIGN_SEAL_TIMEOUT": shorter,
        "AICHECK_AGENTDESIGN_SEAL_DOCUMENT_TIMEOUT": shorter,
        "AICHECK_AGENTDESIGN_SEAL_CANDIDATE_TIMEOUT": shorter,
        "AICHECK_OCR_VISUAL_SEAL_TIMEOUT": shorter,
        "AICHECK_OPENCV_TABLE_GRID_TIMEOUT": shorter,
    }
    previous = {key: os.environ.get(key) for key in keys}
    try:
        for key, value in keys.items():
            os.environ[key] = value
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def suggested_expected_from_result(
    result: dict[str, Any],
    *,
    max_fields: int,
    max_tables: int,
    max_seals: int,
) -> dict[str, Any]:
    quality = result.get("quality") if isinstance(result.get("quality"), dict) else {}
    suggested: dict[str, Any] = {
        "qualityStatus": quality.get("status") or ("auto_usable" if result.get("status") == "success" else "failed"),
        "minEvidenceCompleteness": quality.get("evidenceCompleteness", 0.95),
        "prelabelSource": "machine_ocr_suggestion",
    }
    fields = [suggested_field(item) for item in result.get("fields") or [] if isinstance(item, dict)]
    fields = [item for item in fields if item.get("fieldCode") and item.get("value") is not None]
    tables = [suggested_table(item) for item in result.get("tables") or [] if isinstance(item, dict)]
    tables = [item for item in tables if item.get("businessSchema") or item.get("bbox")]
    seals = [suggested_seal(item) for item in result.get("seals") or [] if isinstance(item, dict)]
    seals = [item for item in seals if item.get("nameContains") or item.get("sealType") or item.get("bbox")]
    if fields:
        suggested["fields"] = fields[:max_fields]
    if tables:
        suggested["tables"] = tables[:max_tables]
    if seals:
        suggested["seals"] = seals[:max_seals]
    reasons = quality.get("reasons") if isinstance(quality.get("reasons"), list) else []
    if reasons:
        suggested["qualityReasons"] = reasons
    diagnostics = result.get("diagnostics") if isinstance(result.get("diagnostics"), list) else []
    if diagnostics and result.get("status") != "success":
        suggested["diagnostics"] = [
            {"code": str(item.get("code") or "OCR_DIAGNOSTIC"), "level": str(item.get("level") or "error")}
            for item in diagnostics
            if isinstance(item, dict)
        ][:5]
    return suggested


def suggested_field(field: dict[str, Any]) -> dict[str, Any]:
    code = field.get("fieldCode") or field.get("fieldName") or field.get("field")
    output = {
        "fieldCode": str(code) if code else None,
        "value": field.get("fieldValue", field.get("value", field.get("text"))),
        "pageNo": field.get("pageNo"),
        "bbox": normalized_bbox(field.get("bbox"), field.get("polygon")),
        "confidence": field.get("confidence"),
        "sourceEngine": field.get("sourceEngine"),
        "reviewStatus": "machine_suggested",
    }
    return {key: value for key, value in output.items() if value is not None}


def suggested_table(table: dict[str, Any]) -> dict[str, Any]:
    rows = table.get("rows")
    if rows is None and isinstance(table.get("businessRows"), list):
        rows = len(table["businessRows"])
    columns = table.get("columns")
    output = {
        "businessSchema": table.get("businessSchema") or table.get("tableId") or "table_suggestion",
        "minRows": rows,
        "minColumns": columns,
        "bbox": normalized_bbox(table.get("bbox"), table.get("polygon")),
        "structureConfidence": table.get("structureConfidence") or table.get("confidence"),
        "sourceEngine": table.get("sourceEngine"),
        "reviewStatus": "machine_suggested",
    }
    if isinstance(table.get("businessSchemas"), list) and table["businessSchemas"]:
        output["businessSchemas"] = [str(item) for item in table["businessSchemas"] if item]
    if isinstance(table.get("matchedRequiredTables"), list) and table["matchedRequiredTables"]:
        output["matchedRequiredTables"] = [str(item) for item in table["matchedRequiredTables"] if item]
    elif table.get("matchedRequiredTable"):
        output["matchedRequiredTables"] = [str(table["matchedRequiredTable"])]
    business_rows = table.get("businessRows") or table.get("normalizedRows")
    if isinstance(business_rows, list) and business_rows:
        output["requiredBusinessKeys"] = sorted(str(key) for key in business_rows[0].keys()) if isinstance(business_rows[0], dict) else None
    return {key: value for key, value in output.items() if value is not None}


def suggested_seal(seal: dict[str, Any]) -> dict[str, Any]:
    name = seal.get("sealName") or seal.get("text") or seal.get("name")
    output = {
        "nameContains": name,
        "sealType": seal.get("sealType"),
        "bbox": normalized_bbox(seal.get("bbox"), seal.get("polygon")),
        "minConfidence": seal.get("ocrConfidence") or seal.get("visualConfidence") or seal.get("confidence"),
        "sourceEngine": seal.get("sourceEngine"),
        "reviewStatus": "machine_suggested",
    }
    return {key: value for key, value in output.items() if value is not None}


def normalized_bbox(*candidates: Any) -> list[float] | None:
    for candidate in candidates:
        bbox = bbox_from_value(candidate)
        if bbox is not None:
            return bbox
    return None


def bbox_from_value(value: Any) -> list[float] | None:
    if not isinstance(value, list) or not value:
        return None
    if len(value) >= 4 and all(isinstance(item, int | float | str) for item in value[:4]):
        try:
            x1, y1, x2, y2 = [float(item) for item in value[:4]]
        except (TypeError, ValueError):
            return None
        min_x, max_x = sorted([x1, x2])
        min_y, max_y = sorted([y1, y2])
        if max_x <= min_x or max_y <= min_y:
            return None
        return [min_x, min_y, max_x, max_y]
    points: list[tuple[float, float]] = []
    for point in value:
        if not isinstance(point, list | tuple) or len(point) < 2:
            return None
        try:
            points.append((float(point[0]), float(point[1])))
        except (TypeError, ValueError):
            return None
    if len(points) < 2:
        return None
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    if max_x <= min_x or max_y <= min_y:
        return None
    return [min_x, min_y, max_x, max_y]


def suggested_has_content(expected: dict[str, Any]) -> bool:
    return any(expected.get(key) for key in ["fields", "tables", "seals", "diagnostics"])


def prelabel_blockers(expected: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    for failure in expected_evidence_failures({"expected": expected}, case_id="suggested", source="prelabel"):
        blockers.append(str(failure.get("code")))
    for bucket in ["fields", "tables", "seals"]:
        for item in expected.get(bucket) or []:
            if isinstance(item, dict) and not has_evidence(item):
                blockers.append(f"{bucket}_missing_positive_area_evidence")
    return sorted(set(blockers))


def safe_name(value: Any) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in str(value)).strip("_") or "case"


if __name__ == "__main__":
    raise SystemExit(main())
