from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.ocr_100_annotation_sprint import build_annotation_sprint_plan
from scripts.ocr_100_certification_status import build_certification_status, default_report_paths
from scripts.ocr_100_corpus import OCR_100_SCENARIO_TARGETS, SCENARIO_COLLECTION_HINTS, expected_annotation_checklist
from scripts.ocr_eval_set import write_text_file


DEFAULT_REPORT_DIR = Path("ocr_eval/reports")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build an actionable OCR 100 work board from certification, collection, and annotation evidence.")
    parser.add_argument("--reports-dir", default=str(DEFAULT_REPORT_DIR), help="Base reports directory for default OCR 100 reports.")
    parser.add_argument("--certification-status", help="Existing ocr_100_certification_status.json path. Built from default reports when omitted.")
    parser.add_argument("--closure-plan", help="ocr_100_closure_plan*.json path.")
    parser.add_argument("--annotation-tasks", help="annotation_tasks/prelabelled_tasks/labeled_tasks JSON or annotation pack directory.")
    parser.add_argument("--candidates", help="ocr_100_collection_candidates.json path.")
    parser.add_argument("--limit", type=int, default=30, help="Maximum label work items to include.")
    parser.add_argument("--output", help="Optional JSON output path.")
    parser.add_argument("--markdown-output", help="Optional Markdown output path.")
    parser.add_argument("--csv-output", help="Optional CSV output path.")
    parser.add_argument("--handoff-output-dir", help="Optional directory for collector/labeler handoff Markdown and CSV files.")
    parser.add_argument("--strict", action="store_true", help="Return non-zero unless the OCR 100 action board is complete.")
    args = parser.parse_args()

    report = build_action_board(
        reports_dir=Path(args.reports_dir),
        certification_status_path=Path(args.certification_status) if args.certification_status else None,
        closure_plan_path=Path(args.closure_plan) if args.closure_plan else None,
        annotation_tasks_path=Path(args.annotation_tasks) if args.annotation_tasks else None,
        candidates_path=Path(args.candidates) if args.candidates else None,
        limit=args.limit,
    )
    if args.output:
        write_text_file(Path(args.output), json.dumps(report, ensure_ascii=False, indent=2))
    if args.markdown_output:
        write_text_file(Path(args.markdown_output), action_board_markdown(report))
    if args.csv_output:
        write_text_file(Path(args.csv_output), action_board_csv(report))
    if args.handoff_output_dir:
        write_action_handoff(report, Path(args.handoff_output_dir))
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 0 if (report.get("ok") or not args.strict) else 1


def build_action_board(
    *,
    reports_dir: Path = DEFAULT_REPORT_DIR,
    certification_status_path: Path | None = None,
    closure_plan_path: Path | None = None,
    annotation_tasks_path: Path | None = None,
    candidates_path: Path | None = None,
    limit: int = 30,
) -> dict[str, Any]:
    status = load_certification_status(reports_dir=reports_dir, certification_status_path=certification_status_path, closure_plan_path=closure_plan_path)
    closure = load_json(closure_plan_path) if closure_plan_path else load_json(path_from_status(status, "closurePlan"))
    candidates = load_json(candidates_path) if candidates_path else load_json(latest_match(reports_dir, "ocr_100_scan_candidates.json"))
    sprint = build_sprint(annotation_tasks_path, limit=limit)
    actions: list[dict[str, Any]] = []
    actions.extend(collection_actions(closure))
    actions.extend(label_actions(sprint))
    actions.extend(candidate_actions(candidates))
    actions.extend(gate_actions(status))
    actions = sorted(actions, key=lambda item: (-float(item.get("priority", 0)), str(item.get("lane")), str(item.get("scenario")), str(item.get("id"))))
    summary = board_summary(status, closure, sprint, candidates, actions)
    return {
        "schemaVersion": "aicheck-ocr-100-action-board-v1",
        "ok": bool(summary.get("status") == "complete"),
        "summary": summary,
        "actions": actions,
        "scenarioPlan": scenario_plan_from_closure(closure),
        "labelSprint": sprint,
        "candidateSummary": candidates.get("summary", {}) if isinstance(candidates, dict) else {},
    }


def load_certification_status(*, reports_dir: Path, certification_status_path: Path | None, closure_plan_path: Path | None) -> dict[str, Any]:
    if certification_status_path:
        return load_json(certification_status_path)
    paths = default_report_paths(reports_dir, closure_plan=closure_plan_path)
    return build_certification_status(paths)


def build_sprint(path: Path | None, *, limit: int) -> dict[str, Any]:
    if path is None or not path.expanduser().exists():
        return {"summary": {"tasks": 0, "readyForEval": 0, "humanLabeled": 0, "remainingHumanLabels": 0}, "workItems": [], "scenarioPlan": {}}
    return build_annotation_sprint_plan(path, limit=limit)


def collection_actions(closure: dict[str, Any]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for scenario, item in scenario_plan_from_closure(closure).items():
        missing = safe_int(item.get("collectionMissingCases"))
        if missing <= 0:
            continue
        actions.append(
            {
                "id": f"collect-{scenario}",
                "lane": "collect_samples",
                "priority": 90 + missing,
                "scenario": scenario,
                "title": f"Collect {missing} real OCR sample(s) for {scenario}",
                "targetCases": safe_int(item.get("targetCases"), OCR_100_SCENARIO_TARGETS.get(scenario, 0)),
                "queuedCases": safe_int(item.get("queuedCases")),
                "readyForEval": safe_int(item.get("readyForEval")),
                "missingCases": missing,
                "dropDirectory": f"ocr_eval/reports/ocr_100_sample_intake_after_batch6_dedupe/samples/{scenario}",
                "collectionHint": item.get("collectionHint") or SCENARIO_COLLECTION_HINTS.get(scenario, ""),
                "checklist": item.get("minimumExpectedAnnotations") or expected_annotation_checklist(scenario),
                "doneWhen": "Real customer/field files are present in the scenario drop directory and manifest_autofilled.json has no placeholders for this scenario.",
            }
        )
    return actions


def label_actions(sprint: dict[str, Any]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for item in sprint.get("workItems") or []:
        if not isinstance(item, dict) or item.get("readyForEval"):
            continue
        case_id = str(item.get("caseId") or item.get("taskId") or "unknown")
        actions.append(
            {
                "id": f"label-{case_id}",
                "lane": "label_existing",
                "priority": 70 + float(item.get("priorityScore") or 0),
                "scenario": item.get("scenario"),
                "caseId": item.get("caseId"),
                "taskId": item.get("taskId"),
                "title": f"Human-review OCR label for {case_id}",
                "sourcePath": item.get("sourcePath"),
                "previewPaths": item.get("previewPaths") or [],
                "blockers": item.get("blockers") or [],
                "humanActions": item.get("humanActions") or [],
                "doneWhen": "labeledExpected is human-corrected with positive evidence, collectionStatus=ready_for_eval, and labeler/reviewer are different people.",
            }
        )
    return actions


def candidate_actions(candidates: dict[str, Any]) -> list[dict[str, Any]]:
    summary = candidates.get("summary") if isinstance(candidates.get("summary"), dict) else {}
    new_count = safe_int(summary.get("newCandidates"))
    if new_count <= 0:
        return []
    return [
        {
            "id": "triage-new-candidates",
            "lane": "triage_candidates",
            "priority": 85,
            "scenario": "mixed",
            "title": f"Triage {new_count} new local OCR sample candidate(s)",
            "newCandidates": new_count,
            "newScenarioCounts": summary.get("newScenarioCounts") or {},
            "doneWhen": "New candidates are copied into the correct scenario folders, deduped, and included in manifest_autofilled.json.",
        }
    ]


def gate_actions(status: dict[str, Any]) -> list[dict[str, Any]]:
    summary = status.get("summary") if isinstance(status.get("summary"), dict) else {}
    status_code = str(summary.get("status") or "")
    if status_code == "complete":
        return []
    ready = safe_int(summary.get("readyForEval"))
    required = safe_int(summary.get("requiredReadyForEval"), 100)
    actions: list[dict[str, Any]] = []
    if status_code == "needs_release_eval_export" or ready >= required:
        actions.append(
            {
                "id": "export-release-eval-set",
                "lane": "release_eval",
                "priority": 60,
                "scenario": "all",
                "title": "Export reviewed labels into the OCR 100 release eval set",
                "doneWhen": "ocr_100_reviewed_label_gate.py writes release_eval_set.json without readiness blockers.",
            }
        )
    if status_code == "needs_scorecard_rerun":
        actions.append(
            {
                "id": "rerun-scorecard",
                "lane": "scorecard",
                "priority": 55,
                "scenario": "all",
                "title": "Rerun OCR 100 scorecard against the release eval set",
                "doneWhen": "ocr_100_scorecard.json has ok=true and score=100.",
            }
        )
    return actions


def board_summary(
    status: dict[str, Any],
    closure: dict[str, Any],
    sprint: dict[str, Any],
    candidates: dict[str, Any],
    actions: list[dict[str, Any]],
) -> dict[str, Any]:
    status_summary = status.get("summary") if isinstance(status.get("summary"), dict) else {}
    sprint_summary = sprint.get("summary") if isinstance(sprint.get("summary"), dict) else {}
    candidate_summary = candidates.get("summary") if isinstance(candidates.get("summary"), dict) else {}
    lane_counts: dict[str, int] = {}
    for action in actions:
        lane = str(action.get("lane") or "unspecified")
        lane_counts[lane] = lane_counts.get(lane, 0) + 1
    return {
        "schemaVersion": "aicheck-ocr-100-action-board-v1",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "status": status_summary.get("status"),
        "score": status_summary.get("score"),
        "readyForEval": status_summary.get("readyForEval", sprint_summary.get("readyForEval", 0)),
        "requiredReadyForEval": status_summary.get("requiredReadyForEval", 100),
        "collectionMissingCases": status_summary.get("collectionMissingCases", collection_missing_from_closure(closure)),
        "placeholderSampleSlots": status_summary.get("placeholderSampleSlots"),
        "annotationTasks": sprint_summary.get("tasks", 0),
        "remainingHumanLabels": sprint_summary.get("remainingHumanLabels", 0),
        "newLocalCandidates": candidate_summary.get("newCandidates", 0),
        "duplicateLocalCandidates": candidate_summary.get("duplicates", 0),
        "actions": len(actions),
        "laneCounts": dict(sorted(lane_counts.items())),
    }


def scenario_plan_from_closure(closure: dict[str, Any]) -> dict[str, dict[str, Any]]:
    plan = closure.get("scenarioPlan") if isinstance(closure, dict) and isinstance(closure.get("scenarioPlan"), dict) else {}
    return {str(key): value for key, value in plan.items() if isinstance(value, dict)}


def collection_missing_from_closure(closure: dict[str, Any]) -> int:
    return sum(safe_int(item.get("collectionMissingCases")) for item in scenario_plan_from_closure(closure).values())


def path_from_status(status: dict[str, Any], report_name: str) -> Path | None:
    reports = status.get("reports") if isinstance(status.get("reports"), dict) else {}
    item = reports.get(report_name) if isinstance(reports.get(report_name), dict) else {}
    raw_path = item.get("path")
    return Path(str(raw_path)) if raw_path else None


def latest_match(base: Path, pattern: str) -> Path | None:
    matches = [path for path in base.expanduser().glob(pattern) if path.is_file()]
    if not matches:
        return None
    return max(matches, key=lambda path: path.stat().st_mtime)


def load_json(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    resolved = path.expanduser()
    if not resolved.exists():
        return {}
    payload = json.loads(resolved.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def action_board_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    lines = [
        "# OCR 100 Action Board",
        "",
        f"- Status: {summary.get('status')}",
        f"- Score: {summary.get('score')}",
        f"- Ready for eval: {summary.get('readyForEval')} / {summary.get('requiredReadyForEval')}",
        f"- Collection missing cases: {summary.get('collectionMissingCases')}",
        f"- Remaining human labels: {summary.get('remainingHumanLabels')}",
        f"- New local candidates: {summary.get('newLocalCandidates')}",
        "",
        "## Lane Counts",
        "",
        "| Lane | Count |",
        "| --- | ---: |",
    ]
    lane_counts = summary.get("laneCounts") if isinstance(summary.get("laneCounts"), dict) else {}
    for lane, count in lane_counts.items():
        lines.append(f"| {lane} | {count} |")
    if not lane_counts:
        lines.append("| none | 0 |")
    lines.extend(["", "## Actions", "", "| Priority | Lane | Scenario | Title | Detail | Done When |", "| ---: | --- | --- | --- | --- | --- |"])
    for action in report.get("actions") or []:
        if not isinstance(action, dict):
            continue
        detail = action_detail_for_export(action)
        lines.append(
            f"| {action.get('priority')} | {action.get('lane')} | {action.get('scenario')} | "
            f"{action.get('title')} | {detail} | {action.get('doneWhen')} |"
        )
    lines.append("")
    return "\n".join(lines)


def action_board_csv(report: dict[str, Any]) -> str:
    fieldnames = [
        "priority",
        "lane",
        "scenario",
        "id",
        "title",
        "caseId",
        "taskId",
        "sourcePath",
        "dropDirectory",
        "missingCases",
        "checklist",
        "collectionHint",
        "blockers",
        "humanActions",
        "previewPaths",
        "doneWhen",
    ]
    handle = StringIO()
    writer = csv.DictWriter(handle, fieldnames=fieldnames)
    writer.writeheader()
    for action in report.get("actions") or []:
        if not isinstance(action, dict):
            continue
        writer.writerow(
            {
                key: "; ".join(str(value) for value in action.get(key) or [])
                if key in {"blockers", "humanActions", "previewPaths", "checklist"}
                else action.get(key)
                for key in fieldnames
            }
        )
    return handle.getvalue()


def write_action_handoff(report: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    actions = [action for action in report.get("actions") or [] if isinstance(action, dict)]
    grouped = actions_by_lane(actions)
    files = {
        "readme": output_dir / "README.md",
        "collectMarkdown": output_dir / "collect_samples.md",
        "collectCsv": output_dir / "collect_samples.csv",
        "labelMarkdown": output_dir / "label_existing.md",
        "labelCsv": output_dir / "label_existing.csv",
    }
    write_text_file(files["readme"], action_handoff_readme(report, grouped))
    write_text_file(files["collectMarkdown"], lane_markdown(report, grouped.get("collect_samples", []), lane="collect_samples"))
    write_text_file(files["collectCsv"], lane_csv(grouped.get("collect_samples", []), lane="collect_samples"))
    write_text_file(files["labelMarkdown"], lane_markdown(report, grouped.get("label_existing", []), lane="label_existing"))
    write_text_file(files["labelCsv"], lane_csv(grouped.get("label_existing", []), lane="label_existing"))
    manifest = {
        "schemaVersion": "aicheck-ocr-100-action-handoff-v1",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "outputDir": str(output_dir),
        "summary": report.get("summary") if isinstance(report.get("summary"), dict) else {},
        "laneCounts": {lane: len(items) for lane, items in sorted(grouped.items())},
        "files": {key: str(path) for key, path in files.items()},
    }
    write_text_file(output_dir / "handoff_manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    return manifest


def actions_by_lane(actions: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for action in actions:
        lane = str(action.get("lane") or "unspecified")
        grouped.setdefault(lane, []).append(action)
    return grouped


def action_handoff_readme(report: dict[str, Any], grouped: dict[str, list[dict[str, Any]]]) -> str:
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    collect_count = len(grouped.get("collect_samples", []))
    label_count = len(grouped.get("label_existing", []))
    lines = [
        "# OCR 100 Operator Handoff",
        "",
        f"- Status: {summary.get('status')}",
        f"- Score: {summary.get('score')}",
        f"- Ready for eval: {summary.get('readyForEval')} / {summary.get('requiredReadyForEval')}",
        f"- Missing real sample slots: {summary.get('collectionMissingCases')}",
        f"- Remaining human labels: {summary.get('remainingHumanLabels')}",
        f"- Collection actions: {collect_count}",
        f"- Labeling actions: {label_count}",
        "",
        "## Files",
        "",
        "| File | Owner | Purpose |",
        "| --- | --- | --- |",
        "| `collect_samples.md` / `collect_samples.csv` | Sample collector | Scenario gaps, drop folders, and minimum annotation checklist. |",
        "| `label_existing.md` / `label_existing.csv` | Human labeler/reviewer | Existing Scan tasks that need field/table/seal correction and evidence boxes. |",
        "",
        "## Execution Order",
        "",
        "1. Collect missing real files into each `dropDirectory` listed in `collect_samples.*`.",
        "2. Run intake autofill and strict verification from `ocr_100_sample_intake.../commands.json`.",
        "3. Complete existing annotation tasks from `label_existing.*`; do not submit machine suggestions as gold labels without human review.",
        "4. Finalize labels only after values, quality status, and positive-area evidence are reviewed.",
        "5. Rerun `ocr_100_action_board.py` and `ocr_100_certification_status.py` until `readyForEval` reaches the required target.",
        "",
    ]
    return "\n".join(lines)


def lane_markdown(report: dict[str, Any], actions: list[dict[str, Any]], *, lane: str) -> str:
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    title = "Collect Real OCR Samples" if lane == "collect_samples" else "Human Label Existing OCR Samples"
    lines = [
        f"# {title}",
        "",
        f"- Board status: {summary.get('status')}",
        f"- Actions: {len(actions)}",
        "",
    ]
    if lane == "collect_samples":
        lines.extend(["| Priority | Scenario | Missing | Drop Directory | Checklist | Hint | Done When |", "| ---: | --- | ---: | --- | --- | --- | --- |"])
        for action in actions:
            lines.append(
                f"| {action.get('priority')} | {action.get('scenario')} | {action.get('missingCases')} | "
                f"{action.get('dropDirectory')} | {join_values(action.get('checklist'))} | "
                f"{action.get('collectionHint') or ''} | {action.get('doneWhen') or ''} |"
            )
    elif lane == "label_existing":
        lines.extend(["| Priority | Case | Scenario | Source | Previews | Blockers | Human Actions | Done When |", "| ---: | --- | --- | --- | --- | --- | --- | --- |"])
        for action in actions:
            lines.append(
                f"| {action.get('priority')} | {action.get('caseId') or action.get('taskId')} | {action.get('scenario')} | "
                f"{action.get('sourcePath') or ''} | {join_values(action.get('previewPaths'))} | "
                f"{join_values(action.get('blockers'))} | {join_values(action.get('humanActions'))} | {action.get('doneWhen') or ''} |"
            )
    else:
        lines.extend(["| Priority | Lane | Scenario | Title | Done When |", "| ---: | --- | --- | --- | --- |"])
        for action in actions:
            lines.append(f"| {action.get('priority')} | {action.get('lane')} | {action.get('scenario')} | {action.get('title')} | {action.get('doneWhen') or ''} |")
    lines.append("")
    return "\n".join(lines)


def lane_csv(actions: list[dict[str, Any]], *, lane: str) -> str:
    if lane == "collect_samples":
        fieldnames = ["priority", "scenario", "missingCases", "dropDirectory", "checklist", "collectionHint", "doneWhen"]
    elif lane == "label_existing":
        fieldnames = ["priority", "caseId", "taskId", "scenario", "sourcePath", "previewPaths", "blockers", "humanActions", "doneWhen"]
    else:
        fieldnames = ["priority", "lane", "scenario", "id", "title", "doneWhen"]
    handle = StringIO()
    writer = csv.DictWriter(handle, fieldnames=fieldnames)
    writer.writeheader()
    for action in actions:
        writer.writerow({key: join_values(action.get(key)) if key in {"checklist", "previewPaths", "blockers", "humanActions"} else action.get(key) for key in fieldnames})
    return handle.getvalue()


def join_values(value: Any) -> str:
    if isinstance(value, list):
        return "; ".join(str(item) for item in value)
    if value is None:
        return ""
    return str(value)


def action_detail_for_export(action: dict[str, Any]) -> str:
    lane = str(action.get("lane") or "")
    if lane == "collect_samples":
        checklist = "; ".join(str(value) for value in action.get("checklist") or [])
        return " · ".join(
            item
            for item in [
                f"missing={action.get('missingCases')}",
                str(action.get("dropDirectory") or ""),
                checklist,
            ]
            if item
        )
    if lane == "label_existing":
        blockers = "; ".join(str(value) for value in action.get("blockers") or [])
        return " · ".join(item for item in [str(action.get("sourcePath") or ""), blockers] if item)
    if lane == "triage_candidates":
        return json.dumps(action.get("newScenarioCounts") or {}, ensure_ascii=False, sort_keys=True)
    return str(action.get("doneWhen") or "")


if __name__ == "__main__":
    raise SystemExit(main())
