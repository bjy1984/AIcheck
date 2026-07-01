from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.ocr_service.annotation_schema import validate_expected_schema
from scripts.ocr_100_annotation_pack import certification_blockers
from scripts.ocr_eval_set import write_text_file


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize AIcheck OCR annotation readiness before OCR 100 evaluation.")
    parser.add_argument("annotation_tasks", help="annotation_tasks.json, prelabelled tasks JSON, or annotation pack directory.")
    parser.add_argument("--output", help="Optional readiness report JSON output path.")
    parser.add_argument("--markdown-output", help="Optional Markdown report output path.")
    parser.add_argument("--strict", action="store_true", help="Return non-zero when any task is not ready for evaluation.")
    args = parser.parse_args()

    report = build_annotation_readiness_report(Path(args.annotation_tasks))
    if args.output:
        write_text_file(Path(args.output), json.dumps(report, ensure_ascii=False, indent=2))
    if args.markdown_output:
        write_text_file(Path(args.markdown_output), annotation_readiness_markdown(report))
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 1 if args.strict and not report.get("ok") else 0


def build_annotation_readiness_report(path: Path) -> dict[str, Any]:
    tasks_path = resolve_tasks_path(path)
    payload = json.loads(tasks_path.read_text(encoding="utf-8"))
    tasks = payload.get("tasks") if isinstance(payload, dict) else payload
    if not isinstance(tasks, list):
        raise ValueError("annotation tasks must be a JSON object with tasks[] or a raw task list.")
    return build_annotation_readiness_from_tasks(tasks, source=str(tasks_path))


def build_annotation_readiness_from_tasks(tasks: list[Any], *, source: str = "memory") -> dict[str, Any]:
    items = [annotation_task_status(task) for task in tasks if isinstance(task, dict)]
    scenario_counts = Counter(str(item.get("scenario") or "unspecified") for item in items)
    ready_by_scenario = Counter(str(item.get("scenario") or "unspecified") for item in items if item.get("readyForEval"))
    blocker_counts: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    for item in items:
        status_counts[str(item.get("collectionStatus") or "unknown")] += 1
        for blocker in item.get("blockers") or []:
            blocker_counts[str(blocker)] += 1
    ready_count = len([item for item in items if item.get("readyForEval")])
    human_labeled_count = len([item for item in items if item.get("hasHumanLabel")])
    scenario_gaps = scenario_gap_summary(items)
    report = {
        "schemaVersion": "aicheck-ocr-annotation-readiness-v1",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "ok": bool(items) and ready_count == len(items),
        "summary": {
            "tasks": len(items),
            "humanLabeled": human_labeled_count,
            "readyForEval": ready_count,
            "missingHumanLabels": len(items) - human_labeled_count,
            "completionRate": round(ready_count / (len(items) or 1), 4),
            "scenarioCounts": dict(sorted(scenario_counts.items())),
            "readyScenarioCounts": dict(sorted(ready_by_scenario.items())),
            "statusCounts": dict(sorted(status_counts.items())),
            "blockerCounts": dict(sorted(blocker_counts.items())),
            "scenarioGaps": scenario_gaps,
        },
        "scenarioGaps": scenario_gaps,
        "nextActions": next_actions(items),
        "tasks": items,
    }
    return report


def scenario_gap_summary(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for item in items:
        scenario = str(item.get("scenario") or "unspecified")
        bucket = output.setdefault(
            scenario,
            {
                "scenario": scenario,
                "tasks": 0,
                "humanLabeled": 0,
                "readyForEval": 0,
                "missingHumanLabels": 0,
                "reviewRequired": 0,
                "machineSuggestions": 0,
                "machineDraftLabels": 0,
                "blockerCounts": {},
                "evidenceBlockerCounts": {},
                "nextHumanAction": "",
            },
        )
        bucket["tasks"] += 1
        if item.get("hasHumanLabel"):
            bucket["humanLabeled"] += 1
        else:
            bucket["missingHumanLabels"] += 1
        if item.get("readyForEval"):
            bucket["readyForEval"] += 1
        if item.get("hasMachineSuggestion"):
            bucket["machineSuggestions"] += 1
        if item.get("hasMachineDraftLabel"):
            bucket["machineDraftLabels"] += 1
        blockers = [str(blocker) for blocker in item.get("blockers") or []]
        if blockers:
            bucket["reviewRequired"] += 1
        for blocker in blockers:
            counts = bucket["blockerCounts"]
            counts[blocker] = counts.get(blocker, 0) + 1
            if blocker.endswith("_evidence_missing") or blocker in {"zero_area_bbox", "invalid_bbox", "bbox_out_of_bounds"}:
                evidence_counts = bucket["evidenceBlockerCounts"]
                evidence_counts[blocker] = evidence_counts.get(blocker, 0) + 1
    for bucket in output.values():
        bucket["blockerCounts"] = dict(sorted(bucket["blockerCounts"].items()))
        bucket["evidenceBlockerCounts"] = dict(sorted(bucket["evidenceBlockerCounts"].items()))
        bucket["nextHumanAction"] = scenario_next_action(bucket)
    return dict(sorted(output.items()))


def scenario_next_action(bucket: dict[str, Any]) -> str:
    blockers = set(str(blocker) for blocker in (bucket.get("blockerCounts") or {}).keys())
    if "missing_human_label" in blockers and bucket.get("machineSuggestions"):
        return "Review machine suggestions, correct values and evidence boxes, then confirm with human labeler/reviewer."
    if "missing_human_label" in blockers:
        return "Create human labeledExpected values and positive-area evidence from the source document."
    if any(blocker.endswith("_evidence_missing") or blocker == "zero_area_bbox" for blocker in blockers):
        return "Draw or correct positive-area field/table/seal evidence boxes before export."
    if "review_required" in blockers:
        return "Set collectionStatus=ready_for_eval only after second review."
    if bucket.get("readyForEval") == bucket.get("tasks"):
        return "Ready to export into the OCR release eval set."
    return "Review remaining blockers for this scenario."


def resolve_tasks_path(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    if resolved.is_dir():
        for name in ["labeled_tasks.json", "prelabelled_tasks.json", "annotation_tasks.json"]:
            candidate = resolved / name
            if candidate.exists():
                return candidate
    return resolved


def annotation_task_status(task: dict[str, Any]) -> dict[str, Any]:
    labeled = task.get("labeledExpected") if isinstance(task.get("labeledExpected"), dict) else None
    suggested = task.get("suggestedExpected") if isinstance(task.get("suggestedExpected"), dict) else None
    template = task.get("expectedTemplate") if isinstance(task.get("expectedTemplate"), dict) else None
    expected = labeled or template or {}
    collection_status = str(task.get("collectionStatus") or "")
    machine_draft = bool(labeled and is_machine_draft_label(task, labeled))
    human_labeled = bool(labeled) and not machine_draft
    blockers = []
    if not human_labeled:
        blockers.append("missing_human_label")
    if machine_draft:
        blockers.append("machine_draft_not_human_confirmed")
    elif human_labeled and collection_status != "ready_for_eval":
        blockers.append("review_required")
    blockers.extend(certification_blockers(expected))
    blockers.extend(evidence_blockers(expected))
    blockers.extend(schema_blockers(task, expected))
    if collection_status == "ready_for_eval":
        blockers.extend(review_blockers(task, expected))
    if suggested and not labeled:
        blockers.append("machine_suggestion_not_confirmed")
    blockers = sorted(dict.fromkeys(blockers))
    return {
        "taskId": task.get("taskId"),
        "caseId": task.get("caseId"),
        "scenario": task.get("scenario"),
        "profileId": task.get("profileId"),
        "documentType": task.get("documentType"),
        "collectionStatus": task.get("collectionStatus"),
        "hasMachineSuggestion": bool(suggested),
        "hasMachineDraftLabel": bool(machine_draft),
        "hasHumanLabel": bool(human_labeled),
        "readyForEval": bool(human_labeled) and collection_status == "ready_for_eval" and not blockers,
        "blockers": blockers,
        "previewPaths": task.get("previewPaths") or [],
    }


def is_machine_draft_label(task: dict[str, Any], expected: dict[str, Any] | None = None) -> bool:
    expected = expected if isinstance(expected, dict) else task.get("labeledExpected")
    review = expected.get("review") if isinstance(expected, dict) and isinstance(expected.get("review"), dict) else {}
    machine_draft = task.get("machineDraftLabel") if isinstance(task.get("machineDraftLabel"), dict) else {}
    source = str(review.get("source") or machine_draft.get("source") or "").strip()
    labeler = str(review.get("labeler") or task.get("labeler") or "").strip()
    return bool(
        machine_draft
        or review.get("requiresHumanConfirmation") is True
        or source in {"machine_suggestion_draft", "machine_prelabel_draft", "ocr_prelabel_draft"}
        or labeler in {"machine_prelabel", "machine_suggestion", "ocr_prelabel"}
    )


def evidence_blockers(expected: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    for section in ["fields", "tables", "seals"]:
        items = [item for item in expected.get(section) or [] if isinstance(item, dict)]
        if not items:
            continue
        missing = [item for item in items if not has_positive_evidence(item)]
        if missing:
            blockers.append(f"{section}_evidence_missing")
    return blockers


def schema_blockers(task: dict[str, Any], expected: dict[str, Any]) -> list[str]:
    page_count = safe_int(task.get("pageCount"))
    page_dimensions = page_dimensions_for_task(task)
    failures = validate_expected_schema(
        expected,
        scenario=str(task.get("scenario") or ""),
        page_count=page_count,
        page_dimensions=page_dimensions,
    )
    return [str(item.get("code")) for item in failures if item.get("code")]


def review_blockers(task: dict[str, Any], expected: dict[str, Any]) -> list[str]:
    review = expected.get("review") if isinstance(expected.get("review"), dict) else {}
    labeler = str(task.get("labeler") or review.get("labeler") or "").strip()
    reviewer = str(task.get("reviewer") or review.get("reviewer") or "").strip()
    if not labeler:
        return ["review_labeler_missing"]
    if not reviewer:
        return ["review_reviewer_missing"]
    if labeler == reviewer:
        return ["reviewer_equals_labeler"]
    return []


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


def has_positive_evidence(item: dict[str, Any]) -> bool:
    bbox = item.get("bbox")
    if isinstance(bbox, list) and len(bbox) >= 4:
        try:
            x1, y1, x2, y2 = [float(value) for value in bbox[:4]]
            if x2 > x1 and y2 > y1:
                return True
        except (TypeError, ValueError):
            pass
    polygon = item.get("polygon")
    if isinstance(polygon, list) and len(polygon) >= 3:
        try:
            xs = [float(point[0]) for point in polygon if isinstance(point, list) and len(point) >= 2]
            ys = [float(point[1]) for point in polygon if isinstance(point, list) and len(point) >= 2]
        except (TypeError, ValueError):
            return False
        return bool(xs and ys and max(xs) > min(xs) and max(ys) > min(ys))
    return False


def next_actions(items: list[dict[str, Any]]) -> list[str]:
    if not items:
        return ["Generate an annotation pack from the real sample queue first."]
    actions: list[str] = []
    if any("missing_human_label" in (item.get("blockers") or []) for item in items):
        actions.append("Import the Label Studio package, correct machine predictions, and export human annotations.")
    if any("machine_draft_not_human_confirmed" in (item.get("blockers") or []) for item in items):
        actions.append("Review machine draft labels, correct values/bboxes, then set a real labeler and reviewer before ready_for_eval.")
    if any("machine_suggestion_not_confirmed" in (item.get("blockers") or []) for item in items):
        actions.append("Run ocr_100_label_studio_import.py so predictions become reviewed labeledExpected values.")
    if any("placeholder_labels" in (item.get("blockers") or []) for item in items):
        actions.append("Replace placeholder labels such as replace-with-label with exact human values.")
    if any("zero_area_bbox" in (item.get("blockers") or []) for item in items):
        actions.append("Replace [0,0,0,0] placeholders with positive-area evidence boxes.")
    if any(str(blocker).endswith("_evidence_missing") for item in items for blocker in (item.get("blockers") or [])):
        actions.append("Add field/table/seal bbox or polygon evidence before exporting the release eval set.")
    if not actions:
        actions.append("Export the tasks with ocr_100_annotation_export.py and run ocr_eval_set.py.")
    return actions


def annotation_readiness_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    lines = [
        "# OCR Annotation Readiness",
        "",
        f"- Status: {'PASS' if report.get('ok') else 'BLOCKED'}",
        f"- Tasks: {summary.get('tasks', 0)}",
        f"- Human labeled: {summary.get('humanLabeled', 0)}",
        f"- Ready for eval: {summary.get('readyForEval', 0)}",
        f"- Completion rate: {summary.get('completionRate', 0)}",
        "",
        "## Blockers",
        "",
    ]
    blocker_counts = summary.get("blockerCounts") if isinstance(summary.get("blockerCounts"), dict) else {}
    if blocker_counts:
        lines.extend(["| Blocker | Count |", "| --- | ---: |"])
        for blocker, count in blocker_counts.items():
            lines.append(f"| {blocker} | {count} |")
    else:
        lines.append("No blockers.")
    scenario_gaps = report.get("scenarioGaps") if isinstance(report.get("scenarioGaps"), dict) else {}
    lines.extend(["", "## Scenario Gaps", ""])
    if scenario_gaps:
        lines.extend(["| Scenario | Tasks | Human labeled | Ready | Missing human labels | Review required | Top blockers | Next action |", "| --- | ---: | ---: | ---: | ---: | ---: | --- | --- |"])
        for scenario, item in scenario_gaps.items():
            if not isinstance(item, dict):
                continue
            blocker_counts = item.get("blockerCounts") if isinstance(item.get("blockerCounts"), dict) else {}
            top_blockers = "; ".join(f"{name}:{count}" for name, count in list(blocker_counts.items())[:4])
            lines.append(
                f"| {scenario} | {item.get('tasks', 0)} | {item.get('humanLabeled', 0)} | "
                f"{item.get('readyForEval', 0)} | {item.get('missingHumanLabels', 0)} | "
                f"{item.get('reviewRequired', 0)} | {top_blockers or 'none'} | {item.get('nextHumanAction') or ''} |"
            )
    else:
        lines.append("No scenario gaps.")
    lines.extend(["", "## Next Actions", ""])
    for action in report.get("nextActions") or []:
        lines.append(f"- {action}")
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
