from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.ocr_service.annotation_schema import validate_expected_schema
from scripts.ocr_100_annotation_export import resolve_tasks_path
from scripts.ocr_100_annotation_pack import certification_blockers
from scripts.ocr_100_corpus import expected_evidence_failures
from scripts.ocr_eval_set import write_text_file

LABEL_TO_BUCKET = {
    "field": "fields",
    "fields": "fields",
    "table": "tables",
    "tables": "tables",
    "seal": "seals",
    "seals": "seals",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Import Label Studio OCR 100 annotations back into annotation tasks.")
    parser.add_argument("label_studio_export", help="Label Studio exported JSON task list.")
    parser.add_argument("--annotation-tasks", required=True, help="Original annotation_tasks.json, prelabelled tasks JSON, or annotation pack directory.")
    parser.add_argument("--output", required=True, help="Output updated annotation tasks JSON.")
    parser.add_argument("--report-output", help="Optional import validation report JSON path.")
    parser.add_argument("--mark-status", default="labeled", choices=["labeled", "verified", "ready_for_eval"], help="collectionStatus for imported tasks.")
    parser.add_argument(
        "--allow-incomplete",
        action="store_true",
        help="Write imported tasks even when certification blockers or missing evidence remain. Use only for draft review, not OCR 100 certification.",
    )
    args = parser.parse_args()

    report = import_label_studio_annotations(
        Path(args.label_studio_export),
        annotation_tasks=Path(args.annotation_tasks),
        output_path=Path(args.output),
        mark_status=args.mark_status,
        allow_incomplete=bool(args.allow_incomplete),
    )
    public_report = {key: value for key, value in report.items() if key != "tasks"}
    if args.report_output:
        write_text_file(Path(args.report_output), json.dumps(public_report, ensure_ascii=False, indent=2))
    print(json.dumps(public_report["summary"], ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


def import_label_studio_annotations(
    label_studio_export: Path,
    *,
    annotation_tasks: Path,
    output_path: Path,
    mark_status: str = "labeled",
    allow_incomplete: bool = False,
) -> dict[str, Any]:
    tasks_path = resolve_tasks_path(annotation_tasks)
    original_payload = json.loads(tasks_path.read_text(encoding="utf-8"))
    original_tasks = original_payload.get("tasks") if isinstance(original_payload, dict) else original_payload
    if not isinstance(original_tasks, list):
        raise ValueError("annotation tasks must be a JSON object with tasks[] or a raw task list.")

    label_payload = json.loads(label_studio_export.expanduser().read_text(encoding="utf-8"))
    label_tasks = label_payload.get("tasks") if isinstance(label_payload, dict) else label_payload
    if not isinstance(label_tasks, list):
        raise ValueError("Label Studio export must be a JSON object with tasks[] or a raw task list.")

    original_by_case_id = {str(task.get("caseId")): task for task in original_tasks if isinstance(task, dict) and task.get("caseId")}
    original_by_task_id = {str(task.get("taskId")): task for task in original_tasks if isinstance(task, dict) and task.get("taskId")}
    updated_tasks = [deepcopy(task) for task in original_tasks if isinstance(task, dict)]
    updated_by_case_id = {str(task.get("caseId")): task for task in updated_tasks if task.get("caseId")}
    updated_by_task_id = {str(task.get("taskId")): task for task in updated_tasks if task.get("taskId")}

    imported_at = datetime.now(timezone.utc).isoformat()
    imported: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    json_expected_count = 0
    region_expected_count = 0

    for label_task in label_tasks:
        if not isinstance(label_task, dict):
            continue
        case_id = label_case_id(label_task)
        task_id = label_task_id(label_task)
        original = original_by_case_id.get(case_id) if case_id else None
        original = original or (original_by_task_id.get(task_id) if task_id else None)
        target = updated_by_case_id.get(case_id) if case_id else None
        target = target or (updated_by_task_id.get(task_id) if task_id else None)
        if original is None or target is None:
            unmatched.append({"caseId": case_id, "taskId": task_id, "reason": "original_task_not_found"})
            continue
        annotation = selected_annotation(label_task)
        if annotation is None:
            skipped.append({"caseId": target.get("caseId"), "taskId": target.get("taskId"), "reason": "no_human_annotation"})
            continue
        results = annotation_results(annotation)
        page_no = label_page_no(label_task)
        expected_from_json = expected_from_label_json(results)
        import_mode = "label_json"
        if expected_from_json is not None:
            expected = apply_page_metadata(expected_from_json, page_no=page_no)
            json_expected_count += 1
        else:
            expected = expected_from_regions(results, original_task=original, label_task=label_task)
            region_expected_count += 1
            import_mode = "regions"

        target["labeledExpected"] = expected
        target["collectionStatus"] = mark_status
        target["labelStudioImport"] = {
            "importedAt": imported_at,
            "source": str(label_studio_export),
            "annotationId": annotation.get("id"),
            "annotationUpdatedAt": annotation.get("updated_at") or annotation.get("created_at"),
            "resultCount": len(results),
            "mode": import_mode,
            "pageNo": page_no,
            "pageDimensions": page_dimensions_payload(page_no, label_image_size(label_task, results)),
        }
        target["pageNo"] = page_no or target.get("pageNo")
        target["pageDimensions"] = page_dimensions_payload(page_no, label_image_size(label_task, results))
        target["schemaFailures"] = schema_failures_for_task(target)
        target["certificationBlockers"] = [
            *certification_blockers(expected),
            *[failure["code"] for failure in target.get("schemaFailures") or []],
        ]
        imported.append({"caseId": target.get("caseId"), "taskId": target.get("taskId"), "mode": import_mode})

    output_payload = {
        "summary": {
            "schemaVersion": "aicheck-ocr-100-label-studio-import-v1",
            "generatedAt": imported_at,
            "source": str(label_studio_export),
            "annotationTasks": str(tasks_path),
            "sourceTasks": len(original_tasks),
            "labelStudioTasks": len(label_tasks),
            "importedTasks": len(imported),
            "unmatchedTasks": len(unmatched),
            "skippedTasks": len(skipped),
            "jsonExpectedTasks": json_expected_count,
            "regionExpectedTasks": region_expected_count,
            "markStatus": mark_status,
            "allowIncomplete": bool(allow_incomplete),
        },
        "tasks": updated_tasks,
    }

    failures = import_failures(updated_tasks)
    summary = dict(output_payload["summary"])
    summary["failureCount"] = len(failures)
    ok = len(imported) > 0 and not unmatched and not skipped and (allow_incomplete or not failures)
    official_output_written = bool(ok)
    draft_output_path = None
    if official_output_written:
        write_text_file(output_path, json.dumps(output_payload, ensure_ascii=False, indent=2))
    else:
        draft_output_path = draft_path(output_path)
        write_text_file(draft_output_path, json.dumps(output_payload, ensure_ascii=False, indent=2))
    summary["outputWritten"] = official_output_written
    summary["draftOutput"] = str(draft_output_path) if draft_output_path else None
    return {
        "schemaVersion": "aicheck-ocr-100-label-studio-import-report-v1",
        "ok": ok,
        "summary": summary,
        "imported": imported,
        "unmatched": unmatched,
        "skipped": skipped,
        "failures": failures,
        "tasks": updated_tasks,
    }


def label_case_id(task: dict[str, Any]) -> str:
    data = task.get("data") if isinstance(task.get("data"), dict) else {}
    for key in ["case_id", "caseId", "case"]:
        if data.get(key):
            return str(data[key])
    for key in ["case_id", "caseId"]:
        if task.get(key):
            return str(task[key])
    return ""


def label_task_id(task: dict[str, Any]) -> str:
    meta = task.get("meta") if isinstance(task.get("meta"), dict) else {}
    if meta.get("taskId"):
        return str(meta["taskId"])
    data = task.get("data") if isinstance(task.get("data"), dict) else {}
    if data.get("task_id"):
        return str(data["task_id"])
    return str(task.get("taskId") or task.get("id") or "")


def label_page_no(task: dict[str, Any]) -> int | None:
    data = task.get("data") if isinstance(task.get("data"), dict) else {}
    meta = task.get("meta") if isinstance(task.get("meta"), dict) else {}
    for value in [data.get("page_no"), data.get("pageNo"), meta.get("pageNo"), task.get("pageNo")]:
        try:
            if int(value) > 0:
                return int(value)
        except (TypeError, ValueError):
            continue
    return None


def selected_annotation(task: dict[str, Any]) -> dict[str, Any] | None:
    annotations = task.get("annotations")
    if isinstance(annotations, list):
        usable = [item for item in annotations if isinstance(item, dict) and not item.get("was_cancelled") and annotation_results(item)]
        if usable:
            usable.sort(key=lambda item: str(item.get("updated_at") or item.get("created_at") or item.get("id") or ""))
            return usable[-1]
    if annotation_results(task):
        return task
    return None


def annotation_results(annotation: dict[str, Any]) -> list[dict[str, Any]]:
    results = annotation.get("result")
    return [item for item in results if isinstance(item, dict)] if isinstance(results, list) else []


def expected_from_label_json(results: list[dict[str, Any]]) -> dict[str, Any] | None:
    for result in results:
        if result.get("from_name") != "label_json":
            continue
        value = result.get("value") if isinstance(result.get("value"), dict) else {}
        texts = value.get("text")
        if isinstance(texts, str):
            texts = [texts]
        if not isinstance(texts, list):
            continue
        for text in texts:
            parsed = parse_json_text(str(text))
            if not isinstance(parsed, dict):
                continue
            expected = parsed.get("expected") if isinstance(parsed.get("expected"), dict) else parsed
            return expected
    return None


def parse_json_text(value: str) -> Any:
    text = value.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def expected_from_regions(results: list[dict[str, Any]], *, original_task: dict[str, Any], label_task: dict[str, Any]) -> dict[str, Any]:
    expected = base_expected(original_task, results)
    suggested = suggested_expected(original_task, label_task)
    image_size = label_image_size(label_task, results)
    label_page = label_page_no(label_task)
    used_suggestion_ids: set[str] = set()
    for result in results:
        bucket = bucket_for_region(result)
        if bucket is None:
            continue
        bbox = region_bbox(result, image_size=image_size)
        if bbox is None:
            continue
        item = default_item(bucket)
        suggestion, suggestion_id = best_suggestion(bucket, bbox, suggested, used_suggestion_ids=used_suggestion_ids)
        if suggestion:
            item.update(metadata_from_suggestion(bucket, suggestion))
            used_suggestion_ids.add(suggestion_id)
        item["bbox"] = bbox
        item["pageNo"] = int(suggestion.get("pageNo") or label_page or original_task.get("pageNo") or 1) if suggestion else int(label_page or original_task.get("pageNo") or 1)
        item["annotationSource"] = "label_studio_region"
        expected.setdefault(bucket, [])
        expected[bucket].append(item)
    return expected


def apply_page_metadata(expected: dict[str, Any], *, page_no: int | None) -> dict[str, Any]:
    updated = deepcopy(expected)
    if not page_no:
        return updated
    for bucket in ["fields", "tables", "seals"]:
        for item in updated.get(bucket) or []:
            if isinstance(item, dict) and not item.get("pageNo"):
                item["pageNo"] = page_no
    return updated


def base_expected(original_task: dict[str, Any], results: list[dict[str, Any]]) -> dict[str, Any]:
    template = original_task.get("expectedTemplate") if isinstance(original_task.get("expectedTemplate"), dict) else {}
    expected: dict[str, Any] = {}
    min_evidence = template.get("minEvidenceCompleteness")
    if min_evidence is not None:
        expected["minEvidenceCompleteness"] = min_evidence
    choice = quality_choice(results)
    if choice:
        expected["qualityStatus"] = choice
    else:
        raw_status = template.get("qualityStatus")
        expected["qualityStatus"] = raw_status if isinstance(raw_status, str) and "|" not in raw_status else "needs_human_review"
    return expected


def quality_choice(results: list[dict[str, Any]]) -> str | None:
    for result in results:
        if result.get("from_name") != "quality_status":
            continue
        value = result.get("value") if isinstance(result.get("value"), dict) else {}
        choices = value.get("choices")
        if isinstance(choices, list) and choices:
            return str(choices[0])
    return None


def suggested_expected(original_task: dict[str, Any], label_task: dict[str, Any]) -> dict[str, Any]:
    if isinstance(original_task.get("suggestedExpected"), dict):
        return original_task["suggestedExpected"]
    data = label_task.get("data") if isinstance(label_task.get("data"), dict) else {}
    raw = data.get("suggested_expected")
    if isinstance(raw, str):
        parsed = parse_json_text(raw)
        if isinstance(parsed, dict):
            return parsed
    if isinstance(raw, dict):
        return raw
    return {}


def label_image_size(label_task: dict[str, Any], results: list[dict[str, Any]]) -> tuple[int, int]:
    for result in results:
        width = result.get("original_width")
        height = result.get("original_height")
        if positive_number(width) and positive_number(height):
            return int(width), int(height)
    meta = label_task.get("meta") if isinstance(label_task.get("meta"), dict) else {}
    width = meta.get("imageWidth") or meta.get("image_width")
    height = meta.get("imageHeight") or meta.get("image_height")
    if positive_number(width) and positive_number(height):
        return int(width), int(height)
    return 100, 100


def page_dimensions_payload(page_no: int | None, image_size: tuple[int, int]) -> dict[str, list[int]]:
    if not page_no:
        return {}
    return {str(page_no): [int(image_size[0]), int(image_size[1])]}


def positive_number(value: Any) -> bool:
    try:
        return float(value) > 0
    except (TypeError, ValueError):
        return False


def bucket_for_region(result: dict[str, Any]) -> str | None:
    if result.get("type") != "rectanglelabels" and result.get("from_name") != "bbox":
        return None
    value = result.get("value") if isinstance(result.get("value"), dict) else {}
    labels = value.get("rectanglelabels")
    if not isinstance(labels, list) or not labels:
        return None
    return LABEL_TO_BUCKET.get(str(labels[0]).strip().lower())


def region_bbox(result: dict[str, Any], *, image_size: tuple[int, int]) -> list[int] | None:
    value = result.get("value") if isinstance(result.get("value"), dict) else {}
    try:
        x = float(value["x"])
        y = float(value["y"])
        width = float(value["width"])
        height = float(value["height"])
    except (KeyError, TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    image_width, image_height = image_size
    x1 = round(x / 100 * image_width)
    y1 = round(y / 100 * image_height)
    x2 = round((x + width) / 100 * image_width)
    y2 = round((y + height) / 100 * image_height)
    if x2 <= x1 or y2 <= y1:
        return None
    return [int(x1), int(y1), int(x2), int(y2)]


def default_item(bucket: str) -> dict[str, Any]:
    if bucket == "fields":
        return {"fieldCode": "replace-with-field-code", "value": "replace-with-label"}
    if bucket == "tables":
        return {"businessSchema": "replace-with-table-schema"}
    if bucket == "seals":
        return {"nameContains": "replace-with-seal-text"}
    return {}


def best_suggestion(
    bucket: str,
    bbox: list[int],
    suggested: dict[str, Any],
    *,
    used_suggestion_ids: set[str],
) -> tuple[dict[str, Any] | None, str]:
    candidates = suggested.get(bucket) if isinstance(suggested.get(bucket), list) else []
    best: tuple[float, int, dict[str, Any]] | None = None
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            continue
        suggestion_id = f"{bucket}:{index}"
        if suggestion_id in used_suggestion_ids:
            continue
        candidate_bbox = candidate.get("bbox")
        if not bbox_valid(candidate_bbox):
            continue
        score = bbox_iou(bbox, [int(float(item)) for item in candidate_bbox[:4]])
        if best is None or score > best[0]:
            best = (score, index, candidate)
    if best and best[0] > 0:
        return best[2], f"{bucket}:{best[1]}"
    return None, ""


def metadata_from_suggestion(bucket: str, suggestion: dict[str, Any]) -> dict[str, Any]:
    keys_by_bucket = {
        "fields": ["fieldCode", "value", "sourceEngine", "confidence"],
        "tables": ["businessSchema", "minRows", "minColumns", "normalizedRows", "sourceEngine", "structureConfidence"],
        "seals": ["nameContains", "sealType", "sourceEngine", "ocrConfidence", "visualConfidence"],
    }
    return {key: deepcopy(suggestion[key]) for key in keys_by_bucket.get(bucket, []) if key in suggestion}


def bbox_valid(value: Any) -> bool:
    if not isinstance(value, list) or len(value) < 4:
        return False
    try:
        x1, y1, x2, y2 = [float(item) for item in value[:4]]
    except (TypeError, ValueError):
        return False
    return x2 > x1 and y2 > y1


def bbox_iou(left: list[int], right: list[int]) -> float:
    left_x1, left_y1, left_x2, left_y2 = left
    right_x1, right_y1, right_x2, right_y2 = right
    inter_x1 = max(left_x1, right_x1)
    inter_y1 = max(left_y1, right_y1)
    inter_x2 = min(left_x2, right_x2)
    inter_y2 = min(left_y2, right_y2)
    if inter_x2 <= inter_x1 or inter_y2 <= inter_y1:
        return 0.0
    inter_area = float((inter_x2 - inter_x1) * (inter_y2 - inter_y1))
    left_area = float((left_x2 - left_x1) * (left_y2 - left_y1))
    right_area = float((right_x2 - right_x1) * (right_y2 - right_y1))
    denominator = left_area + right_area - inter_area
    return inter_area / denominator if denominator > 0 else 0.0


def import_failures(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for task in tasks:
        if not isinstance(task, dict) or "labeledExpected" not in task:
            continue
        case_id = str(task.get("caseId") or "unknown")
        expected = task.get("labeledExpected") if isinstance(task.get("labeledExpected"), dict) else {}
        for schema_failure in schema_failures_for_task(task):
            failures.append(
                {
                    **schema_failure,
                    "caseId": case_id,
                    "source": "label_studio_import_schema",
                }
            )
        for blocker in certification_blockers(expected):
            failures.append(
                {
                    "code": "OCR_100_LABEL_STUDIO_IMPORT_INCOMPLETE",
                    "message": f"{case_id}: imported annotation still has blocker {blocker}.",
                    "caseId": case_id,
                    "blocker": blocker,
                }
            )
        failures.extend(
            expected_evidence_failures(
                {"caseId": case_id, "expected": expected},
                case_id=case_id,
                source="label_studio_import",
            )
        )
    return failures


def schema_failures_for_task(task: dict[str, Any]) -> list[dict[str, Any]]:
    expected = task.get("labeledExpected") if isinstance(task.get("labeledExpected"), dict) else {}
    page_dimensions = page_dimensions_for_task(task)
    page_count = safe_int(task.get("pageCount")) or (max(page_dimensions) if page_dimensions else None)
    return validate_expected_schema(
        expected,
        scenario=str(task.get("scenario") or ""),
        page_count=page_count,
        page_dimensions=page_dimensions,
    )


def page_dimensions_for_task(task: dict[str, Any]) -> dict[int, tuple[int, int]]:
    dimensions = task.get("pageDimensions") if isinstance(task.get("pageDimensions"), dict) else {}
    parsed: dict[int, tuple[int, int]] = {}
    for raw_page, raw_size in dimensions.items():
        if not isinstance(raw_size, list) or len(raw_size) < 2:
            continue
        try:
            parsed[int(raw_page)] = (int(raw_size[0]), int(raw_size[1]))
        except (TypeError, ValueError):
            continue
    return parsed


def safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def draft_path(output_path: Path) -> Path:
    suffix = output_path.suffix or ".json"
    return output_path.with_name(f"{output_path.stem}.draft{suffix}")


if __name__ == "__main__":
    raise SystemExit(main())
