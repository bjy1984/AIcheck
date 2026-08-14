from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.ocr_100_annotation_export import resolve_tasks_path
from scripts.ocr_eval_set import write_text_file


def main() -> int:
    parser = argparse.ArgumentParser(description="Merge refreshed OCR prelabels into a base annotation task pack.")
    parser.add_argument("base", help="Base prelabelled_tasks.json, annotation_tasks.json, or annotation pack directory.")
    parser.add_argument("updates", nargs="+", help="One or more refreshed prelabelled task JSON files.")
    parser.add_argument("--output", required=True, help="Merged output JSON path.")
    parser.add_argument(
        "--allow-overwrite-human-labels",
        action="store_true",
        help="Allow refreshed task payloads to replace existing labeledExpected. Default preserves human labels.",
    )
    args = parser.parse_args()

    result = merge_prelabel_packs(
        Path(args.base),
        [Path(item) for item in args.updates],
        output_path=Path(args.output),
        preserve_human_labels=not bool(args.allow_overwrite_human_labels),
    )
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 0


def merge_prelabel_packs(
    base_path: Path,
    update_paths: list[Path],
    *,
    output_path: Path | None = None,
    preserve_human_labels: bool = True,
) -> dict[str, Any]:
    base_resolved = resolve_tasks_path(base_path)
    base_payload = load_task_payload(base_resolved)
    base_tasks = base_payload.get("tasks") if isinstance(base_payload, dict) else base_payload
    if not isinstance(base_tasks, list):
        raise ValueError("base annotation pack must contain tasks[]")
    updates_by_case: dict[str, dict[str, Any]] = {}
    update_sources: dict[str, str] = {}
    for update_path in update_paths:
        update_payload = load_task_payload(update_path)
        update_tasks = update_payload.get("tasks") if isinstance(update_payload, dict) else update_payload
        if not isinstance(update_tasks, list):
            raise ValueError(f"update pack must contain tasks[]: {update_path}")
        for task in update_tasks:
            if not isinstance(task, dict):
                continue
            case_id = str(task.get("caseId") or task.get("taskId") or "").strip()
            if not case_id:
                continue
            updates_by_case[case_id] = task
            update_sources[case_id] = str(update_path)

    merged_tasks: list[dict[str, Any]] = []
    merged_cases: list[str] = []
    skipped_human_labels: list[str] = []
    for task in base_tasks:
        if not isinstance(task, dict):
            merged_tasks.append(task)
            continue
        case_id = str(task.get("caseId") or task.get("taskId") or "").strip()
        update = updates_by_case.get(case_id)
        if not update:
            merged_tasks.append(task)
            continue
        merged = merge_task(task, update, preserve_human_labels=preserve_human_labels)
        if preserve_human_labels and task.get("labeledExpected") and update.get("labeledExpected"):
            skipped_human_labels.append(case_id)
        merged["prelabelMerge"] = {
            "source": update_sources.get(case_id),
            "mergedAt": datetime.now(UTC).isoformat(),
            "preservedHumanLabel": bool(preserve_human_labels and task.get("labeledExpected")),
        }
        merged_tasks.append(merged)
        merged_cases.append(case_id)

    output_payload = dict(base_payload) if isinstance(base_payload, dict) else {"tasks": merged_tasks}
    output_payload["tasks"] = merged_tasks
    output_payload["prelabelMergeSummary"] = {
        "schemaVersion": "aicheck-ocr-100-prelabel-merge-report-v1",
        "generatedAt": datetime.now(UTC).isoformat(),
        "base": str(base_resolved),
        "updateFiles": [str(path) for path in update_paths],
        "baseTasks": len(base_tasks),
        "updateTasks": len(updates_by_case),
        "mergedTasks": len(merged_cases),
        "missingUpdateCases": sorted(set(updates_by_case) - {str(task.get("caseId") or task.get("taskId") or "") for task in base_tasks if isinstance(task, dict)}),
        "mergedCaseIds": sorted(merged_cases),
        "preserveHumanLabels": preserve_human_labels,
        "skippedHumanLabelCaseIds": sorted(skipped_human_labels),
    }
    if output_path:
        write_text_file(output_path, json.dumps(output_payload, ensure_ascii=False, indent=2))
    return {"summary": output_payload["prelabelMergeSummary"], "payload": output_payload}


def merge_task(base: dict[str, Any], update: dict[str, Any], *, preserve_human_labels: bool) -> dict[str, Any]:
    merged = dict(base)
    for key in [
        "suggestedExpected",
        "prelabelStatus",
        "prelabelSummary",
        "parseResult",
        "previewPaths",
        "previewStatus",
        "previewEvents",
    ]:
        if key in update:
            merged[key] = update[key]
    if not preserve_human_labels:
        if "labeledExpected" in update:
            merged["labeledExpected"] = update.get("labeledExpected")
        if "collectionStatus" in update:
            merged["collectionStatus"] = update.get("collectionStatus")
        for key in ["labeler", "reviewer"]:
            if key in update:
                merged[key] = update[key]
    return merged


def load_task_payload(path: Path) -> Any:
    resolved = resolve_tasks_path(path)
    return json.loads(resolved.read_text(encoding="utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
