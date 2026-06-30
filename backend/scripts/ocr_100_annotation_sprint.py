from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from io import StringIO
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.ocr_100_corpus import (
    OCR_100_SCENARIO_TARGETS,
    SCENARIO_COLLECTION_HINTS,
    expected_annotation_checklist,
)
from scripts.ocr_annotation_readiness import (
    annotation_task_status,
    build_annotation_readiness_from_tasks,
    resolve_tasks_path,
)
from scripts.ocr_eval_set import write_text_file


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a human annotation sprint plan for OCR 100 release corpus work.")
    parser.add_argument("annotation_tasks", help="annotation_tasks.json, prelabelled_tasks.json, labeled_tasks.json, or annotation pack directory.")
    parser.add_argument("--limit", type=int, default=30, help="Maximum prioritized task rows in the top-level sprint list.")
    parser.add_argument("--output", help="Optional JSON sprint plan output path.")
    parser.add_argument("--markdown-output", help="Optional Markdown sprint plan output path.")
    parser.add_argument("--csv-output", help="Optional CSV worklist output path.")
    args = parser.parse_args()

    plan = build_annotation_sprint_plan(Path(args.annotation_tasks), limit=args.limit)
    if args.output:
        write_text_file(Path(args.output), json.dumps(plan, ensure_ascii=False, indent=2))
    if args.markdown_output:
        write_text_file(Path(args.markdown_output), annotation_sprint_markdown(plan))
    if args.csv_output:
        write_text_file(Path(args.csv_output), annotation_sprint_csv(plan))
    print(json.dumps(plan["summary"], ensure_ascii=False, indent=2))
    return 0


def build_annotation_sprint_plan(path: Path, *, limit: int = 30) -> dict[str, Any]:
    tasks_path = resolve_tasks_path(path)
    payload = json.loads(tasks_path.read_text(encoding="utf-8"))
    tasks = payload.get("tasks") if isinstance(payload, dict) else payload
    if not isinstance(tasks, list):
        raise ValueError("annotation tasks must be a JSON object with tasks[] or a raw task list.")
    task_items = [task for task in tasks if isinstance(task, dict)]
    readiness = build_annotation_readiness_from_tasks(task_items, source=str(tasks_path))
    scenario_counts = Counter(str(task.get("scenario") or "unspecified") for task in task_items)
    ready_counts = Counter(
        str(status.get("scenario") or "unspecified")
        for status in readiness.get("tasks") or []
        if isinstance(status, dict) and status.get("readyForEval")
    )
    scenario_plan = scenario_sprint_items(scenario_counts, ready_counts)
    work_items = sorted(
        [annotation_work_item(task) for task in task_items],
        key=lambda item: (-float(item["priorityScore"]), item["scenario"], item["caseId"]),
    )
    top_items = work_items[: max(0, int(limit))]
    return {
        "schemaVersion": "aicheck-ocr-100-annotation-sprint-v1",
        "source": str(tasks_path),
        "summary": {
            "tasks": len(task_items),
            "readyForEval": readiness.get("summary", {}).get("readyForEval", 0),
            "humanLabeled": readiness.get("summary", {}).get("humanLabeled", 0),
            "remainingHumanLabels": readiness.get("summary", {}).get("missingHumanLabels", len(task_items)),
            "scenarioCounts": dict(sorted(scenario_counts.items())),
            "readyScenarioCounts": dict(sorted(ready_counts.items())),
            "scenarioTargetGaps": {
                scenario: item["missingReadyCases"]
                for scenario, item in scenario_plan.items()
                if item["missingReadyCases"] > 0
            },
            "topWorkItems": len(top_items),
            "collectionMissingCases": sum(int(item["collectionMissingCases"]) for item in scenario_plan.values()),
        },
        "readiness": {
            "ok": readiness.get("ok"),
            "blockerCounts": readiness.get("summary", {}).get("blockerCounts", {}),
            "nextActions": readiness.get("nextActions", []),
        },
        "scenarioPlan": scenario_plan,
        "workItems": top_items,
    }


def scenario_sprint_items(scenario_counts: Counter[str], ready_counts: Counter[str]) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for scenario, target in OCR_100_SCENARIO_TARGETS.items():
        current = int(scenario_counts.get(scenario, 0))
        ready = int(ready_counts.get(scenario, 0))
        output[scenario] = {
            "scenario": scenario,
            "targetCases": target,
            "queuedCases": current,
            "readyForEval": ready,
            "missingReadyCases": max(0, target - ready),
            "collectionMissingCases": max(0, target - current),
            "reviewBacklogCases": max(0, current - ready),
            "minimumExpectedAnnotations": expected_annotation_checklist(scenario),
            "collectionHint": SCENARIO_COLLECTION_HINTS.get(scenario, ""),
        }
    return output


def annotation_work_item(task: dict[str, Any]) -> dict[str, Any]:
    status = annotation_task_status(task)
    suggested = task.get("suggestedExpected") if isinstance(task.get("suggestedExpected"), dict) else {}
    template = task.get("expectedTemplate") if isinstance(task.get("expectedTemplate"), dict) else {}
    scenario = str(task.get("scenario") or "unspecified")
    checklist = expected_annotation_checklist(scenario) if scenario in OCR_100_SCENARIO_TARGETS else task.get("checklist") or []
    suggested_counts = expected_counts(suggested)
    template_counts = expected_counts(template)
    positive_evidence_counts = expected_positive_evidence_counts(suggested)
    blockers = [str(item) for item in status.get("blockers") or []]
    priority = priority_score(status, suggested_counts, positive_evidence_counts, scenario)
    return {
        "caseId": task.get("caseId"),
        "taskId": task.get("taskId"),
        "scenario": scenario,
        "profileId": task.get("profileId"),
        "documentType": task.get("documentType"),
        "sourcePath": task.get("sourcePath"),
        "previewPaths": task.get("previewPaths") or [],
        "collectionStatus": task.get("collectionStatus"),
        "hasMachineSuggestion": bool(suggested),
        "hasMachineDraftLabel": bool(status.get("hasMachineDraftLabel")),
        "hasHumanLabel": bool(status.get("hasHumanLabel")),
        "readyForEval": bool(status.get("readyForEval")),
        "priorityScore": round(priority, 4),
        "blockers": blockers,
        "suggestedQualityStatus": suggested.get("qualityStatus"),
        "suggestedEvidenceCompleteness": suggested.get("minEvidenceCompleteness"),
        "suggestedCounts": suggested_counts,
        "suggestedPositiveEvidenceCounts": positive_evidence_counts,
        "templateCounts": template_counts,
        "checklist": checklist,
        "humanActions": human_actions(status, suggested, template),
    }


def priority_score(
    status: dict[str, Any],
    suggested_counts: dict[str, int],
    positive_evidence_counts: dict[str, int],
    scenario: str,
) -> float:
    if status.get("readyForEval"):
        return 0.0
    score = 10.0
    if status.get("hasMachineSuggestion"):
        score += 8.0
    if suggested_counts["fields"] or suggested_counts["tables"] or suggested_counts["seals"]:
        score += 5.0
    score += min(5.0, sum(positive_evidence_counts.values()) * 0.8)
    target = OCR_100_SCENARIO_TARGETS.get(scenario, 0)
    if target:
        score += 2.0
    if "placeholder_labels" in (status.get("blockers") or []):
        score -= 1.0
    if "zero_area_bbox" in (status.get("blockers") or []):
        score -= 1.0
    return max(score, 0.0)


def expected_counts(expected: dict[str, Any]) -> dict[str, int]:
    return {
        "fields": len([item for item in expected.get("fields") or [] if isinstance(item, dict)]),
        "tables": len([item for item in expected.get("tables") or [] if isinstance(item, dict)]),
        "seals": len([item for item in expected.get("seals") or [] if isinstance(item, dict)]),
        "diagnostics": len([item for item in expected.get("diagnostics") or [] if isinstance(item, dict)]),
    }


def expected_positive_evidence_counts(expected: dict[str, Any]) -> dict[str, int]:
    return {
        section: len([item for item in expected.get(section) or [] if isinstance(item, dict) and has_positive_evidence(item)])
        for section in ["fields", "tables", "seals"]
    }


def has_positive_evidence(item: dict[str, Any]) -> bool:
    bbox = item.get("bbox")
    if isinstance(bbox, list) and len(bbox) >= 4:
        try:
            x0, y0, x1, y1 = [float(value) for value in bbox[:4]]
            return x1 > x0 and y1 > y0
        except (TypeError, ValueError):
            return False
    polygon = item.get("polygon")
    if isinstance(polygon, list) and len(polygon) >= 3:
        xs: list[float] = []
        ys: list[float] = []
        for point in polygon:
            if not isinstance(point, list | tuple) or len(point) < 2:
                continue
            try:
                xs.append(float(point[0]))
                ys.append(float(point[1]))
            except (TypeError, ValueError):
                continue
        return bool(xs and ys and max(xs) > min(xs) and max(ys) > min(ys))
    return False


def human_actions(status: dict[str, Any], suggested: dict[str, Any], template: dict[str, Any]) -> list[str]:
    actions: list[str] = []
    blockers = set(str(item) for item in status.get("blockers") or [])
    if "machine_draft_not_human_confirmed" in blockers:
        actions.append("Review machine draft labeledExpected, correct values/bboxes, then replace machine_prelabel with a real labeler.")
    if "missing_human_label" in blockers and suggested:
        actions.append("Review suggestedExpected, correct values/bboxes, then copy it to labeledExpected.")
    elif "missing_human_label" in blockers:
        actions.append("Create labeledExpected from the preview and source document.")
    if "placeholder_labels" in blockers:
        actions.append("Replace placeholder values with exact human labels.")
    if "zero_area_bbox" in blockers or any(blocker.endswith("_evidence_missing") for blocker in blockers):
        actions.append("Draw positive-area bbox/polygon evidence for every required field/table/seal.")
    if not suggested and template:
        actions.append("Use expectedTemplate as the checklist; do not submit placeholders.")
    actions.append("Set collectionStatus=ready_for_eval and fill different labeler/reviewer names after second review.")
    return sorted(dict.fromkeys(actions))


def annotation_sprint_markdown(plan: dict[str, Any]) -> str:
    summary = plan.get("summary", {})
    lines = [
        "# OCR 100 Annotation Sprint",
        "",
        f"- Tasks: {summary.get('tasks', 0)}",
        f"- Ready for eval: {summary.get('readyForEval', 0)}",
        f"- Human labeled: {summary.get('humanLabeled', 0)}",
        f"- Remaining human labels: {summary.get('remainingHumanLabels', 0)}",
        f"- Collection missing cases: {summary.get('collectionMissingCases', 0)}",
        "",
        "## Scenario Gaps",
        "",
        "| Scenario | Target | Queued | Ready | Need Ready | Need Collection |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for scenario, item in (plan.get("scenarioPlan") or {}).items():
        lines.append(
            f"| {scenario} | {item.get('targetCases')} | {item.get('queuedCases')} | {item.get('readyForEval')} | "
            f"{item.get('missingReadyCases')} | {item.get('collectionMissingCases')} |"
        )
    lines.extend(["", "## Priority Worklist", "", "| Priority | Case | Scenario | Source | Blockers | Action |", "| ---: | --- | --- | --- | --- | --- |"])
    for item in plan.get("workItems") or []:
        action = "; ".join(item.get("humanActions") or [])
        blockers = ", ".join(item.get("blockers") or [])
        lines.append(
            f"| {item.get('priorityScore')} | {item.get('caseId')} | {item.get('scenario')} | "
            f"{item.get('sourcePath')} | {blockers} | {action} |"
        )
    lines.append("")
    return "\n".join(lines)


def annotation_sprint_csv(plan: dict[str, Any]) -> str:
    fieldnames = [
        "priorityScore",
        "caseId",
        "scenario",
        "profileId",
        "documentType",
        "sourcePath",
        "collectionStatus",
        "hasMachineSuggestion",
        "hasMachineDraftLabel",
        "hasHumanLabel",
        "readyForEval",
        "blockers",
        "humanActions",
        "previewPaths",
    ]
    handle = StringIO()
    writer = csv.DictWriter(handle, fieldnames=fieldnames)
    writer.writeheader()
    for item in plan.get("workItems") or []:
        writer.writerow(
            {
                key: "; ".join(str(value) for value in item.get(key) or [])
                if key in {"blockers", "humanActions", "previewPaths"}
                else item.get(key)
                for key in fieldnames
            }
        )
    return handle.getvalue()


if __name__ == "__main__":
    raise SystemExit(main())
