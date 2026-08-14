from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.ocr_annotation_readiness import (
    build_annotation_readiness_from_tasks,
    is_machine_draft_label,
    resolve_tasks_path,
)
from scripts.ocr_eval_set import write_text_file


def main() -> int:
    parser = argparse.ArgumentParser(description="Copy OCR machine suggestions into draft labels for human review.")
    parser.add_argument("annotation_tasks", help="prelabelled_tasks.json, merged prelabel file, or annotation pack directory.")
    parser.add_argument("--output", required=True, help="Output task JSON with draft labeledExpected values.")
    parser.add_argument("--case-id", action="append", default=[], help="Only draft the selected caseId. Can be repeated.")
    parser.add_argument("--limit", type=int, default=0, help="Maximum number of drafts to create. 0 means no limit.")
    parser.add_argument("--only-auto-usable", action="store_true", help="Only draft suggestions where qualityStatus=auto_usable.")
    parser.add_argument("--overwrite-machine-drafts", action="store_true", help="Replace existing machine draft labels.")
    parser.add_argument("--allow-overwrite-human-labels", action="store_true", help="Replace existing human labels. Dangerous; off by default.")
    parser.add_argument("--draft-status", default="needs_human_review", help="collectionStatus assigned to newly drafted tasks.")
    args = parser.parse_args()

    result = draft_labels_from_suggestions(
        Path(args.annotation_tasks),
        output_path=Path(args.output),
        case_ids={str(item) for item in args.case_id},
        limit=max(0, int(args.limit)),
        only_auto_usable=bool(args.only_auto_usable),
        overwrite_machine_drafts=bool(args.overwrite_machine_drafts),
        allow_overwrite_human_labels=bool(args.allow_overwrite_human_labels),
        draft_status=str(args.draft_status or "needs_human_review"),
    )
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 0


def draft_labels_from_suggestions(
    annotation_tasks: Path,
    *,
    output_path: Path,
    case_ids: set[str] | None = None,
    limit: int = 0,
    only_auto_usable: bool = False,
    overwrite_machine_drafts: bool = False,
    allow_overwrite_human_labels: bool = False,
    draft_status: str = "needs_human_review",
) -> dict[str, Any]:
    tasks_path = resolve_tasks_path(annotation_tasks)
    payload = json.loads(tasks_path.read_text(encoding="utf-8"))
    tasks = payload.get("tasks") if isinstance(payload, dict) else payload
    if not isinstance(tasks, list):
        raise ValueError("annotation tasks must be a JSON object with tasks[] or a raw task list.")
    selected_case_ids = set(case_ids or set())
    drafted_at = datetime.now(UTC).isoformat()
    output_tasks: list[Any] = []
    drafted_case_ids: list[str] = []
    skipped: dict[str, list[str]] = {
        "case_filter": [],
        "no_suggestion": [],
        "quality_filter": [],
        "existing_human_label": [],
        "existing_machine_draft": [],
        "limit": [],
    }
    drafted_count = 0
    for raw_task in tasks:
        if not isinstance(raw_task, dict):
            output_tasks.append(raw_task)
            continue
        task = deepcopy(raw_task)
        case_id = str(task.get("caseId") or task.get("taskId") or "")
        if selected_case_ids and case_id not in selected_case_ids:
            skipped["case_filter"].append(case_id)
            output_tasks.append(task)
            continue
        if limit and drafted_count >= limit:
            skipped["limit"].append(case_id)
            output_tasks.append(task)
            continue
        suggested = task.get("suggestedExpected") if isinstance(task.get("suggestedExpected"), dict) else None
        if not suggested:
            skipped["no_suggestion"].append(case_id)
            output_tasks.append(task)
            continue
        if only_auto_usable and str(suggested.get("qualityStatus") or "") != "auto_usable":
            skipped["quality_filter"].append(case_id)
            output_tasks.append(task)
            continue
        existing = task.get("labeledExpected") if isinstance(task.get("labeledExpected"), dict) else None
        if existing and not is_machine_draft_label(task, existing) and not allow_overwrite_human_labels:
            skipped["existing_human_label"].append(case_id)
            output_tasks.append(task)
            continue
        if existing and is_machine_draft_label(task, existing) and not overwrite_machine_drafts:
            skipped["existing_machine_draft"].append(case_id)
            output_tasks.append(task)
            continue

        draft = deepcopy(suggested)
        review = draft.get("review") if isinstance(draft.get("review"), dict) else {}
        review.update(
            {
                "source": "machine_suggestion_draft",
                "labeler": "machine_prelabel",
                "reviewer": "",
                "requiresHumanConfirmation": True,
                "draftedAt": drafted_at,
            }
        )
        draft["review"] = review
        task["labeledExpected"] = draft
        task["collectionStatus"] = draft_status
        task.pop("labeler", None)
        task.pop("reviewer", None)
        task["machineDraftLabel"] = {
            "source": "machine_suggestion_draft",
            "draftedAt": drafted_at,
            "sourcePrelabelStatus": task.get("prelabelStatus"),
            "sourceQualityStatus": suggested.get("qualityStatus"),
            "requiresHumanConfirmation": True,
        }
        drafted_count += 1
        drafted_case_ids.append(case_id)
        output_tasks.append(task)

    output_payload = deepcopy(payload) if isinstance(payload, dict) else {"tasks": output_tasks}
    output_payload["tasks"] = output_tasks
    output_payload["draftLabelSummary"] = {
        "schemaVersion": "aicheck-ocr-100-draft-label-summary-v1",
        "generatedAt": drafted_at,
        "source": str(tasks_path),
        "drafted": drafted_count,
        "draftedCaseIds": drafted_case_ids,
        "skipped": {key: value for key, value in skipped.items() if value},
        "safety": {
            "machineDraftsAreNotHumanLabels": True,
            "readyForEvalRequiresHumanLabelerAndReviewer": True,
        },
    }
    readiness = build_annotation_readiness_from_tasks(
        [task for task in output_tasks if isinstance(task, dict)],
        source=str(output_path),
    )
    output_payload["draftLabelSummary"]["readiness"] = readiness.get("summary", {})
    write_text_file(output_path, json.dumps(output_payload, ensure_ascii=False, indent=2))
    return {
        "payload": output_payload,
        "readiness": readiness,
        "summary": output_payload["draftLabelSummary"],
    }


if __name__ == "__main__":
    raise SystemExit(main())
