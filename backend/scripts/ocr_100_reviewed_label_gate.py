from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.ocr_service.readiness import build_ocr_100_scorecard
from apps.ocr_service.service import ocr_service
from scripts.ocr_100_annotation_export import export_annotation_tasks
from scripts.ocr_100_label_studio_import import import_label_studio_annotations
from scripts.ocr_100_scorecard import evaluate_eval_set, load_sample_summaries
from scripts.ocr_annotation_readiness import build_annotation_readiness_report, build_annotation_readiness_from_tasks
from scripts.ocr_eval_set import write_text_file


def main() -> int:
    parser = argparse.ArgumentParser(description="Gate reviewed OCR 100 labels into a release eval set and optional scorecard.")
    parser.add_argument("annotation_tasks", help="Original/prelabelled annotation tasks JSON or annotation pack directory.")
    parser.add_argument("--label-studio-export", help="Optional Label Studio export JSON to import first.")
    parser.add_argument("--output-dir", required=True, help="Directory where gate reports and release eval set are written.")
    parser.add_argument("--sample-summary", action="append", default=[], help="Sample probe summary JSON. Repeatable for scorecard.")
    parser.add_argument("--sample-summary-dir", action="append", default=[], help="Directory with sample probe summary JSON files.")
    parser.add_argument("--eval-report", help="Optional precomputed evaluation report JSON for scorecard.")
    parser.add_argument("--run-ocr-scorecard", action="store_true", help="Run OCR while building scorecard from the exported eval set.")
    parser.add_argument("--auto-discover-runtime", action="store_true", help="Apply runtime discovery before scorecard OCR.")
    parser.add_argument("--allow-incomplete", action="store_true", help="Write draft outputs even if annotation readiness/export is incomplete.")
    parser.add_argument("--strict", action="store_true", help="Return non-zero unless the reviewed labels pass all gates.")
    args = parser.parse_args()

    report = run_reviewed_label_gate(
        Path(args.annotation_tasks),
        label_studio_export=Path(args.label_studio_export) if args.label_studio_export else None,
        output_dir=Path(args.output_dir),
        sample_summary_paths=[Path(item) for item in args.sample_summary],
        sample_summary_dirs=[Path(item) for item in args.sample_summary_dir],
        eval_report_path=Path(args.eval_report) if args.eval_report else None,
        run_ocr_scorecard=bool(args.run_ocr_scorecard),
        auto_discover_runtime=bool(args.auto_discover_runtime),
        allow_incomplete=bool(args.allow_incomplete),
    )
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 0 if (report.get("ok") or not args.strict) else 1


def run_reviewed_label_gate(
    annotation_tasks: Path,
    *,
    label_studio_export: Path | None = None,
    output_dir: Path,
    sample_summary_paths: list[Path] | None = None,
    sample_summary_dirs: list[Path] | None = None,
    eval_report_path: Path | None = None,
    run_ocr_scorecard: bool = False,
    auto_discover_runtime: bool = False,
    allow_incomplete: bool = False,
) -> dict[str, Any]:
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    imported_tasks_path = output_dir / "labeled_tasks.json"
    import_report_path = output_dir / "label_studio_import_report.json"
    readiness_path = output_dir / "readiness.json"
    readiness_md_path = output_dir / "readiness.md"
    eval_set_path = output_dir / "ocr_100_labeled_release_set.json"
    export_report_path = output_dir / "annotation_export_report.json"
    scorecard_path = output_dir / "ocr_100_scorecard.json"

    failures: list[dict[str, Any]] = []
    import_report: dict[str, Any] | None = None
    tasks_path = annotation_tasks
    if label_studio_export is not None:
        import_report = import_label_studio_annotations(
            label_studio_export,
            annotation_tasks=annotation_tasks,
            output_path=imported_tasks_path,
            mark_status="ready_for_eval",
            allow_incomplete=allow_incomplete,
        )
        public_import_report = {key: value for key, value in import_report.items() if key != "tasks"}
        write_text_file(import_report_path, json.dumps(public_import_report, ensure_ascii=False, indent=2))
        if import_report.get("ok"):
            tasks_path = imported_tasks_path
        else:
            draft_output = import_report.get("summary", {}).get("draftOutput")
            if draft_output:
                tasks_path = Path(draft_output)
            failures.append({"code": "LABEL_STUDIO_IMPORT_NOT_READY", "message": "Label Studio import did not pass certification gates."})

    readiness = build_annotation_readiness_report(tasks_path) if Path(tasks_path).exists() else build_annotation_readiness_from_tasks(
        import_report.get("tasks") if isinstance(import_report, dict) else [],
        source=str(tasks_path),
    )
    write_text_file(readiness_path, json.dumps(readiness, ensure_ascii=False, indent=2))
    write_text_file(readiness_md_path, readiness_markdown(readiness))
    if not readiness.get("ok"):
        failures.append({"code": "ANNOTATION_READINESS_NOT_READY", "message": "Reviewed annotation tasks are not ready for OCR 100 evaluation."})

    export_report: dict[str, Any] | None = None
    if readiness.get("ok") or allow_incomplete:
        export_report = export_annotation_tasks(
            tasks_path,
            output_path=eval_set_path,
            allow_incomplete=allow_incomplete,
            mark_status="ready_for_eval",
        )
        public_export_report = {key: value for key, value in export_report.items() if key != "cases"}
        write_text_file(export_report_path, json.dumps(public_export_report, ensure_ascii=False, indent=2))
        if not export_report.get("ok"):
            failures.append({"code": "ANNOTATION_EXPORT_NOT_READY", "message": "Release eval set export did not pass certification gates."})
    else:
        write_text_file(
            export_report_path,
            json.dumps(
                {
                    "schemaVersion": "aicheck-ocr-100-annotation-export-report-v1",
                    "ok": False,
                    "summary": {"outputWritten": False, "reason": "readiness_not_ok"},
                    "failures": [{"code": "READINESS_NOT_OK", "message": "Readiness must pass before release eval export."}],
                },
                ensure_ascii=False,
                indent=2,
            ),
        )

    scorecard: dict[str, Any] | None = None
    if eval_set_path.exists() and (run_ocr_scorecard or eval_report_path is not None):
        scorecard = build_scorecard(
            eval_set_path,
            eval_report_path=eval_report_path,
            sample_summary_paths=sample_summary_paths or [],
            sample_summary_dirs=sample_summary_dirs or [],
            run_ocr=run_ocr_scorecard,
            auto_discover_runtime=auto_discover_runtime,
        )
        write_text_file(scorecard_path, json.dumps(scorecard, ensure_ascii=False, indent=2))
        if not scorecard.get("ok"):
            failures.append({"code": "OCR_100_SCORECARD_NOT_READY", "message": "OCR 100 scorecard did not pass."})

    summary = {
        "schemaVersion": "aicheck-ocr-100-reviewed-label-gate-v1",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "annotationTasks": str(annotation_tasks),
        "labelStudioExport": str(label_studio_export) if label_studio_export else None,
        "outputDir": str(output_dir),
        "ready": not failures,
        "importOk": import_report.get("ok") if import_report else None,
        "readinessOk": readiness.get("ok"),
        "readyForEval": readiness.get("summary", {}).get("readyForEval"),
        "humanLabeled": readiness.get("summary", {}).get("humanLabeled"),
        "tasks": readiness.get("summary", {}).get("tasks"),
        "exportOk": export_report.get("ok") if export_report else False,
        "evalSetWritten": eval_set_path.exists(),
        "scorecardScore": scorecard.get("score") if scorecard else None,
        "scorecardOk": scorecard.get("ok") if scorecard else None,
        "failureCount": len(failures),
    }
    report = {
        "schemaVersion": "aicheck-ocr-100-reviewed-label-gate-v1",
        "ok": not failures,
        "summary": summary,
        "failures": failures,
        "readiness": readiness,
        "importReport": {key: value for key, value in import_report.items() if key != "tasks"} if import_report else None,
        "exportReport": {key: value for key, value in export_report.items() if key != "cases"} if export_report else None,
        "scorecard": scorecard,
    }
    write_text_file(output_dir / "reviewed_label_gate.json", json.dumps(report, ensure_ascii=False, indent=2))
    write_text_file(output_dir / "reviewed_label_gate.md", gate_markdown(report))
    return report


def build_scorecard(
    eval_set_path: Path,
    *,
    eval_report_path: Path | None,
    sample_summary_paths: list[Path],
    sample_summary_dirs: list[Path],
    run_ocr: bool,
    auto_discover_runtime: bool,
) -> dict[str, Any]:
    if auto_discover_runtime:
        apply_auto_discovered_runtime()
    eval_payload = json.loads(eval_set_path.read_text(encoding="utf-8"))
    if eval_report_path:
        evaluation_report = json.loads(eval_report_path.read_text(encoding="utf-8"))
    else:
        evaluation_report = evaluate_eval_set(eval_payload, eval_set_path=eval_set_path, run_ocr=run_ocr)
    runtime_doctor = ocr_service.runtime_doctor_payload()
    sample_summaries = load_sample_summaries([str(path) for path in sample_summary_paths], [str(path) for path in sample_summary_dirs])
    return build_ocr_100_scorecard(
        evaluation_report=evaluation_report,
        runtime_doctor=runtime_doctor,
        sample_summaries=sample_summaries,
    )


def apply_auto_discovered_runtime() -> None:
    from apps.ocr_service.runtime_doctor import discover_runtime_candidates, recommended_env

    for key, value in recommended_env(discover_runtime_candidates()).items():
        if value and not os.getenv(key):
            os.environ[key] = value


def readiness_markdown(report: dict[str, Any]) -> str:
    from scripts.ocr_annotation_readiness import annotation_readiness_markdown

    return annotation_readiness_markdown(report)


def gate_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    lines = [
        "# OCR 100 Reviewed Label Gate",
        "",
        f"- Status: {'PASS' if report.get('ok') else 'BLOCKED'}",
        f"- Tasks: {summary.get('tasks', 0)}",
        f"- Human labeled: {summary.get('humanLabeled', 0)}",
        f"- Ready for eval: {summary.get('readyForEval', 0)}",
        f"- Eval set written: {summary.get('evalSetWritten')}",
        f"- Scorecard: {summary.get('scorecardScore')}",
        "",
        "## Gates",
        "",
        "| Gate | Status |",
        "| --- | --- |",
        f"| Import | {summary.get('importOk')} |",
        f"| Readiness | {summary.get('readinessOk')} |",
        f"| Export | {summary.get('exportOk')} |",
        f"| Scorecard | {summary.get('scorecardOk')} |",
        "",
        "## Failures",
        "",
    ]
    failures = report.get("failures") if isinstance(report.get("failures"), list) else []
    if failures:
        lines.extend(["| Code | Message |", "| --- | --- |"])
        for failure in failures:
            if isinstance(failure, dict):
                lines.append(f"| {failure.get('code')} | {failure.get('message')} |")
    else:
        lines.append("No failures.")
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
