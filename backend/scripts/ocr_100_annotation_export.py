from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.ocr_service.annotation_schema import validate_expected_schema
from apps.ocr_service.evaluation import ocr_100_thresholds
from scripts.ocr_100_annotation_pack import certification_blockers
from scripts.ocr_100_corpus import expected_evidence_failures
from scripts.ocr_annotation_readiness import is_machine_draft_label
from scripts.ocr_eval_set import write_text_file

READY_STATUSES = {"labeled", "verified", "ready_for_eval"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Export completed OCR 100 annotation tasks into a release eval set.")
    parser.add_argument("annotation_tasks", help="annotation_tasks.json file or annotation pack directory.")
    parser.add_argument("--output", required=True, help="Output release eval set JSON path.")
    parser.add_argument("--report-output", help="Optional export validation report JSON path.")
    parser.add_argument("--allow-incomplete", action="store_true", help="Write output even when tasks still have placeholder labels or missing evidence.")
    parser.add_argument("--mark-status", default="labeled", choices=sorted(READY_STATUSES), help="collectionStatus to assign to exported cases.")
    args = parser.parse_args()

    report = export_annotation_tasks(
        Path(args.annotation_tasks),
        output_path=Path(args.output),
        allow_incomplete=bool(args.allow_incomplete),
        mark_status=args.mark_status,
    )
    public_report = {key: value for key, value in report.items() if key != "cases"}
    if args.report_output:
        write_text_file(Path(args.report_output), json.dumps(public_report, ensure_ascii=False, indent=2))
    print(json.dumps(public_report["summary"], ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


def export_annotation_tasks(
    annotation_tasks: Path,
    *,
    output_path: Path,
    allow_incomplete: bool = False,
    mark_status: str = "labeled",
) -> dict[str, Any]:
    tasks_path = resolve_tasks_path(annotation_tasks)
    payload = json.loads(tasks_path.read_text(encoding="utf-8"))
    tasks = payload.get("tasks") if isinstance(payload, dict) else payload
    if not isinstance(tasks, list):
        raise ValueError("annotation tasks must be a JSON object with tasks[] or a raw task list.")
    exported_at = datetime.now(UTC).isoformat()
    cases = merge_page_level_cases(
        [export_task(task, exported_at=exported_at, mark_status=mark_status) for task in tasks if isinstance(task, dict)]
    )
    failures = export_failures(cases)
    eval_set = {
        "name": "aicheck_ocr_100_labeled_release_set",
        "schemaVersion": "aicheck-ocr-100-labeled-release-set-v1",
        "generatedAt": exported_at,
        "thresholds": ocr_100_thresholds(),
        "annotationSource": str(tasks_path),
        "allowIncomplete": bool(allow_incomplete),
        "cases": cases,
    }
    ok = bool(allow_incomplete or not failures)
    if ok:
        write_text_file(output_path, json.dumps(eval_set, ensure_ascii=False, indent=2))
    summary = {
        "annotationTasks": len(tasks),
        "exportedCases": len(cases),
        "failureCount": len(failures),
        "outputWritten": ok,
        "allowIncomplete": bool(allow_incomplete),
    }
    return {
        "schemaVersion": "aicheck-ocr-100-annotation-export-report-v1",
        "ok": ok,
        "summary": summary,
        "failures": failures,
        "cases": cases,
    }


def resolve_tasks_path(path: Path) -> Path:
    resolved = path.expanduser()
    if resolved.is_dir():
        resolved = resolved / "annotation_tasks.json"
    if not resolved.is_file():
        raise FileNotFoundError(str(resolved))
    return resolved


def export_task(task: dict[str, Any], *, exported_at: str, mark_status: str) -> dict[str, Any]:
    expected = labelled_expected(task)
    source = {
        "path": task.get("sourcePath"),
        "fileName": task.get("fileName"),
        "pageCount": task.get("pageCount"),
        "notes": task.get("notes"),
        "annotationTaskId": task.get("taskId"),
    }
    return {
        "caseId": task.get("caseId"),
        "scenario": task.get("scenario"),
        "profileId": task.get("profileId"),
        "documentType": task.get("documentType"),
        "collectionStatus": mark_status,
        "source": {key: value for key, value in source.items() if value is not None},
        "expected": expected,
        "annotation": {
            "sourceTaskId": task.get("taskId"),
            "parentTaskId": task.get("parentTaskId"),
            "pageNo": task.get("pageNo"),
            "sourceCollectionStatus": task.get("collectionStatus"),
            "machineDraftLabel": task.get("machineDraftLabel") if isinstance(task.get("machineDraftLabel"), dict) else None,
            "exportedAt": exported_at,
            "labeler": task.get("labeler"),
            "reviewer": task.get("reviewer"),
            "reviewedAt": task.get("reviewedAt"),
        },
    }


def labelled_expected(task: dict[str, Any]) -> dict[str, Any]:
    for key in ["labeledExpected", "labelledExpected", "expected", "expectedTemplate"]:
        value = task.get(key)
        if isinstance(value, dict):
            return value
    return {}


def merge_page_level_cases(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for case in cases:
        case_id = str(case.get("caseId") or "")
        if not case_id:
            order.append(f"__missing_{len(order)}")
            grouped[order[-1]] = case
            continue
        if case_id not in grouped:
            grouped[case_id] = case
            order.append(case_id)
            continue
        grouped[case_id] = merge_case(grouped[case_id], case)
    return [grouped[key] for key in order]


def merge_case(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    merged = {**left}
    expected = {**(left.get("expected") if isinstance(left.get("expected"), dict) else {})}
    right_expected = right.get("expected") if isinstance(right.get("expected"), dict) else {}
    for bucket in ["fields", "tables", "seals"]:
        expected[bucket] = [
            *[item for item in expected.get(bucket) or [] if isinstance(item, dict)],
            *[item for item in right_expected.get(bucket) or [] if isinstance(item, dict)],
        ]
    for key in ["qualityStatus", "minEvidenceCompleteness", "maxEvidenceCompleteness"]:
        if key not in expected and key in right_expected:
            expected[key] = right_expected[key]
    merged["expected"] = expected
    left_source = left.get("source") if isinstance(left.get("source"), dict) else {}
    right_source = right.get("source") if isinstance(right.get("source"), dict) else {}
    merged["source"] = {**right_source, **left_source}
    annotation = merged.get("annotation") if isinstance(merged.get("annotation"), dict) else {}
    page_tasks = [*annotation.get("pageTasks", []), right.get("annotation")]
    annotation["pageTasks"] = [item for item in page_tasks if isinstance(item, dict)]
    merged["annotation"] = annotation
    return merged


def export_failures(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, case in enumerate(cases):
        case_id = str(case.get("caseId") or f"case[{index}]")
        if not case.get("caseId"):
            failures.append({"code": "OCR_100_ANNOTATION_CASE_ID_MISSING", "message": f"{case_id}: caseId is required.", "caseId": case_id})
        elif case_id in seen:
            failures.append({"code": "OCR_100_ANNOTATION_CASE_ID_DUPLICATE", "message": f"Duplicate caseId: {case_id}", "caseId": case_id})
        seen.add(case_id)
        expected = case.get("expected") if isinstance(case.get("expected"), dict) else {}
        annotation = case.get("annotation") if isinstance(case.get("annotation"), dict) else {}
        if is_machine_draft_label({"machineDraftLabel": annotation.get("machineDraftLabel")}, expected):
            failures.append(
                {
                    "code": "OCR_100_ANNOTATION_MACHINE_DRAFT_NOT_CONFIRMED",
                    "message": f"{case_id}: machine draft labels must be reviewed by a human labeler and second reviewer before export.",
                    "caseId": case_id,
                }
            )
        for schema_failure in validate_expected_schema(
            expected,
            scenario=str(case.get("scenario") or ""),
            page_count=safe_int(case.get("source", {}).get("pageCount")) if isinstance(case.get("source"), dict) else None,
            page_dimensions={},
            require_review=str(case.get("collectionStatus") or "") == "ready_for_eval",
        ):
            failures.append(
                {
                    **schema_failure,
                    "caseId": case_id,
                    "source": "annotation_export_schema",
                }
            )
        for blocker in certification_blockers(expected):
            failures.append(
                {
                    "code": "OCR_100_ANNOTATION_INCOMPLETE",
                    "message": f"{case_id}: annotation still has blocker {blocker}.",
                    "caseId": case_id,
                    "blocker": blocker,
                }
            )
        failures.extend(expected_evidence_failures(case, case_id=case_id, source="annotation_export"))
        if not str(case.get("source", {}).get("path") if isinstance(case.get("source"), dict) else "").strip():
            failures.append({"code": "OCR_100_ANNOTATION_SOURCE_MISSING", "message": f"{case_id}: source.path is required.", "caseId": case_id})
        if not str(case.get("scenario") or "").strip():
            failures.append({"code": "OCR_100_ANNOTATION_SCENARIO_MISSING", "message": f"{case_id}: scenario is required.", "caseId": case_id})
    return failures


def safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    raise SystemExit(main())
