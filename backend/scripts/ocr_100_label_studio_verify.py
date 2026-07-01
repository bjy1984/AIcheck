from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.ocr_100_annotation_export import resolve_tasks_path
from scripts.ocr_eval_set import write_text_file


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify an OCR 100 Label Studio export before human annotation starts.")
    parser.add_argument("label_studio_dir", help="Directory containing label_config.xml, label_studio_tasks.json, and label_studio_summary.json.")
    parser.add_argument("--annotation-tasks", help="Optional source annotation tasks JSON. Defaults to summary.source when available.")
    parser.add_argument("--output", help="Optional JSON verification report path.")
    parser.add_argument("--markdown-output", help="Optional Markdown verification report path.")
    parser.add_argument("--strict", action="store_true", help="Return non-zero when the package is not ready for annotation.")
    args = parser.parse_args()

    report = verify_label_studio_pack(
        Path(args.label_studio_dir),
        annotation_tasks=Path(args.annotation_tasks) if args.annotation_tasks else None,
    )
    if args.output:
        write_text_file(Path(args.output), json.dumps(report, ensure_ascii=False, indent=2))
    if args.markdown_output:
        write_text_file(Path(args.markdown_output), label_studio_verify_markdown(report))
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 1 if args.strict and not report.get("ok") else 0


def verify_label_studio_pack(label_studio_dir: Path, *, annotation_tasks: Path | None = None) -> dict[str, Any]:
    root = label_studio_dir.expanduser().resolve()
    summary_path = root / "label_studio_summary.json"
    tasks_path = root / "label_studio_tasks.json"
    config_path = root / "label_config.xml"
    failures: list[dict[str, Any]] = []
    summary = load_json_object(summary_path, failures=failures, label="summary")
    tasks_payload = load_json(tasks_path, failures=failures, label="tasks")
    label_tasks = tasks_payload if isinstance(tasks_payload, list) else []
    if not config_path.exists():
        failures.append(failure("LABEL_STUDIO_CONFIG_MISSING", "label_config.xml is missing.", path=str(config_path)))
    elif "<RectangleLabels" not in config_path.read_text(encoding="utf-8", errors="ignore"):
        failures.append(failure("LABEL_STUDIO_CONFIG_INVALID", "label_config.xml does not contain RectangleLabels.", path=str(config_path)))
    source_tasks_path = resolve_source_tasks_path(annotation_tasks, summary)
    source_tasks = load_source_tasks(source_tasks_path, failures=failures) if source_tasks_path else []
    source_by_case = {str(task.get("caseId") or task.get("taskId")): task for task in source_tasks if isinstance(task, dict)}
    label_by_case: dict[str, dict[str, Any]] = {}
    local_root = Path(str(summary.get("localFilesRoot") or root)).expanduser().resolve()
    prefix = str(summary.get("imageUrlPrefix") or "/data/local-files/?d=")
    prediction_tasks = 0
    image_failures = 0
    for index, task in enumerate(label_tasks):
        if not isinstance(task, dict):
            failures.append(failure("LABEL_STUDIO_TASK_INVALID", "Label Studio task is not an object.", index=index))
            continue
        data = task.get("data") if isinstance(task.get("data"), dict) else {}
        meta = task.get("meta") if isinstance(task.get("meta"), dict) else {}
        case_id = str(data.get("case_id") or meta.get("taskId") or "").strip()
        if not case_id:
            failures.append(failure("LABEL_STUDIO_CASE_ID_MISSING", "Label Studio task lacks data.case_id.", index=index))
        elif case_id in label_by_case:
            failures.append(failure("LABEL_STUDIO_CASE_ID_DUPLICATE", "Duplicate case_id in Label Studio tasks.", caseId=case_id))
        else:
            label_by_case[case_id] = task
        image_path = resolve_image_path(str(data.get("image") or ""), local_root=local_root, image_url_prefix=prefix)
        if image_path is None or not image_path.exists():
            image_failures += 1
            failures.append(
                failure(
                    "LABEL_STUDIO_IMAGE_MISSING",
                    "Preview image referenced by Label Studio task is missing.",
                    caseId=case_id or None,
                    image=data.get("image"),
                )
            )
        if not safe_positive_int(meta.get("imageWidth")) or not safe_positive_int(meta.get("imageHeight")):
            failures.append(failure("LABEL_STUDIO_IMAGE_SIZE_MISSING", "Task meta lacks positive imageWidth/imageHeight.", caseId=case_id or None))
        if task.get("predictions"):
            prediction_tasks += 1
    if source_by_case:
        missing_cases = sorted(set(source_by_case) - set(label_by_case))
        unexpected_cases = sorted(set(label_by_case) - set(source_by_case))
        if missing_cases:
            failures.append(failure("LABEL_STUDIO_CASES_MISSING", "Some source cases were not exported.", caseIds=missing_cases[:50], count=len(missing_cases)))
        if unexpected_cases:
            failures.append(failure("LABEL_STUDIO_CASES_UNEXPECTED", "Label Studio export contains unknown cases.", caseIds=unexpected_cases[:50], count=len(unexpected_cases)))
    if summary.get("tasks") != len(label_tasks):
        failures.append(failure("LABEL_STUDIO_SUMMARY_TASK_COUNT_MISMATCH", "summary.tasks does not match label_studio_tasks length.", summaryTasks=summary.get("tasks"), actualTasks=len(label_tasks)))
    if summary.get("predictionTasks") != prediction_tasks:
        failures.append(
            failure(
                "LABEL_STUDIO_SUMMARY_PREDICTION_COUNT_MISMATCH",
                "summary.predictionTasks does not match tasks with predictions.",
                summaryPredictionTasks=summary.get("predictionTasks"),
                actualPredictionTasks=prediction_tasks,
            )
        )
    if int(summary.get("skipped") or 0) > 0 and not bool(summary.get("allowSkipped")):
        failures.append(failure("LABEL_STUDIO_SKIPPED_TASKS", "Export skipped tasks without allowSkipped=true.", skipped=summary.get("skipped")))
    report_summary = {
        "schemaVersion": "aicheck-ocr-100-label-studio-verify-v1",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "labelStudioDir": str(root),
        "source": str(source_tasks_path) if source_tasks_path else summary.get("source"),
        "ok": not failures and bool(label_tasks),
        "tasks": len(label_tasks),
        "sourceTasks": len(source_tasks) if source_tasks else summary.get("sourceTasks"),
        "predictionTasks": prediction_tasks,
        "imageFailures": image_failures,
        "skipped": summary.get("skipped", 0),
        "failureCount": len(failures),
    }
    return {"schemaVersion": "aicheck-ocr-100-label-studio-verify-v1", "ok": report_summary["ok"], "summary": report_summary, "failures": failures}


def load_json(path: Path, *, failures: list[dict[str, Any]], label: str) -> Any:
    if not path.exists():
        failures.append(failure("LABEL_STUDIO_FILE_MISSING", f"{label} file is missing.", path=str(path)))
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        failures.append(failure("LABEL_STUDIO_FILE_INVALID", f"{label} file is not valid JSON.", path=str(path), error=exc.__class__.__name__))
        return None


def load_json_object(path: Path, *, failures: list[dict[str, Any]], label: str) -> dict[str, Any]:
    payload = load_json(path, failures=failures, label=label)
    if isinstance(payload, dict):
        return payload
    if payload is not None:
        failures.append(failure("LABEL_STUDIO_FILE_INVALID", f"{label} file must contain a JSON object.", path=str(path)))
    return {}


def resolve_source_tasks_path(annotation_tasks: Path | None, summary: dict[str, Any]) -> Path | None:
    if annotation_tasks is not None:
        return resolve_tasks_path(annotation_tasks)
    source = summary.get("source")
    if not source:
        return None
    path = Path(str(source)).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return resolve_tasks_path(path)


def load_source_tasks(path: Path | None, *, failures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if path is None:
        return []
    if not path.exists():
        failures.append(failure("LABEL_STUDIO_SOURCE_MISSING", "Source annotation tasks file is missing.", path=str(path)))
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        failures.append(failure("LABEL_STUDIO_SOURCE_INVALID", "Source annotation tasks file is invalid.", path=str(path), error=exc.__class__.__name__))
        return []
    tasks = payload.get("tasks") if isinstance(payload, dict) else payload
    if not isinstance(tasks, list):
        failures.append(failure("LABEL_STUDIO_SOURCE_INVALID", "Source annotation tasks must contain tasks[].", path=str(path)))
        return []
    return [task for task in tasks if isinstance(task, dict)]


def resolve_image_path(image_url: str, *, local_root: Path, image_url_prefix: str) -> Path | None:
    if not image_url:
        return None
    raw = image_url
    if raw.startswith(image_url_prefix):
        raw = raw[len(image_url_prefix) :]
    raw = unquote(raw)
    path = Path(raw)
    return path if path.is_absolute() else (local_root / path).resolve()


def safe_positive_int(value: Any) -> bool:
    try:
        return int(value) > 0
    except (TypeError, ValueError):
        return False


def failure(code: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"code": code, "message": message, **{key: value for key, value in extra.items() if value is not None}}


def label_studio_verify_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    lines = [
        "# OCR 100 Label Studio Verify",
        "",
        f"- OK: {summary.get('ok')}",
        f"- Tasks: {summary.get('tasks')}",
        f"- Source tasks: {summary.get('sourceTasks')}",
        f"- Prediction tasks: {summary.get('predictionTasks')}",
        f"- Image failures: {summary.get('imageFailures')}",
        f"- Skipped: {summary.get('skipped')}",
        f"- Failure count: {summary.get('failureCount')}",
        "",
    ]
    if report.get("failures"):
        lines.extend(["## Failures", "", "| Code | Message | Detail |", "| --- | --- | --- |"])
        for item in report.get("failures") or []:
            detail = {key: value for key, value in item.items() if key not in {"code", "message"}}
            lines.append(f"| {item.get('code')} | {item.get('message')} | {json.dumps(detail, ensure_ascii=False)} |")
    else:
        lines.append("No failures. The package is ready for human annotation import.")
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
