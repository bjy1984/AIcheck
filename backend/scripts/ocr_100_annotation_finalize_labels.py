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

from scripts.ocr_annotation_readiness import (
    annotation_task_status,
    build_annotation_readiness_from_tasks,
    is_machine_draft_label,
    resolve_tasks_path,
)
from scripts.ocr_eval_set import write_text_file


def main() -> int:
    parser = argparse.ArgumentParser(description="Finalize human-reviewed OCR annotation labels before release evaluation export.")
    parser.add_argument("annotation_tasks", help="draft/human-labeled task JSON or annotation pack directory.")
    parser.add_argument("--output", required=True, help="Output labeled task JSON.")
    parser.add_argument("--report-output", help="Optional finalization report JSON.")
    parser.add_argument("--case-id", action="append", default=[], help="Only finalize the selected caseId. Can be repeated.")
    parser.add_argument("--labeler", required=True, help="Human labeler name or ID.")
    parser.add_argument("--reviewer", required=True, help="Second reviewer name or ID. Must differ from labeler.")
    parser.add_argument("--comment", default="", help="Optional human review comment.")
    parser.add_argument("--mark-status", default="ready_for_eval", choices=["labeled", "verified", "ready_for_eval"])
    parser.add_argument(
        "--confirm-human-reviewed",
        action="store_true",
        help="Required to convert machine draft labels into human-reviewed labels.",
    )
    parser.add_argument("--allow-incomplete", action="store_true", help="Write output even when selected tasks still fail readiness.")
    args = parser.parse_args()

    result = finalize_human_labels(
        Path(args.annotation_tasks),
        output_path=Path(args.output),
        report_output=Path(args.report_output) if args.report_output else None,
        case_ids=set(str(item) for item in args.case_id),
        labeler=str(args.labeler),
        reviewer=str(args.reviewer),
        comment=str(args.comment or ""),
        mark_status=str(args.mark_status),
        confirm_human_reviewed=bool(args.confirm_human_reviewed),
        allow_incomplete=bool(args.allow_incomplete),
    )
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


def finalize_human_labels(
    annotation_tasks: Path,
    *,
    output_path: Path,
    report_output: Path | None = None,
    case_ids: set[str] | None = None,
    labeler: str,
    reviewer: str,
    comment: str = "",
    mark_status: str = "ready_for_eval",
    confirm_human_reviewed: bool = False,
    allow_incomplete: bool = False,
) -> dict[str, Any]:
    labeler = labeler.strip()
    reviewer = reviewer.strip()
    if not labeler:
        raise ValueError("labeler is required")
    if not reviewer:
        raise ValueError("reviewer is required")
    if labeler == reviewer:
        raise ValueError("reviewer must be different from labeler")

    tasks_path = resolve_tasks_path(annotation_tasks)
    payload = json.loads(tasks_path.read_text(encoding="utf-8"))
    tasks = payload.get("tasks") if isinstance(payload, dict) else payload
    if not isinstance(tasks, list):
        raise ValueError("annotation tasks must be a JSON object with tasks[] or a raw task list.")

    selected_case_ids = set(case_ids or set())
    finalized_at = datetime.now(timezone.utc).isoformat()
    output_tasks: list[Any] = []
    selected: list[dict[str, Any]] = []
    finalized_case_ids: list[str] = []
    skipped: dict[str, list[str]] = {"case_filter": [], "missing_label": [], "machine_draft_unconfirmed": []}
    failures: list[dict[str, Any]] = []

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

        expected = task.get("labeledExpected") if isinstance(task.get("labeledExpected"), dict) else None
        if not expected:
            skipped["missing_label"].append(case_id)
            failures.append({"caseId": case_id, "code": "OCR_100_FINALIZE_LABEL_MISSING", "message": "labeledExpected is required."})
            output_tasks.append(task)
            continue

        machine_draft = is_machine_draft_label(task, expected)
        if machine_draft and not confirm_human_reviewed:
            skipped["machine_draft_unconfirmed"].append(case_id)
            failures.append(
                {
                    "caseId": case_id,
                    "code": "OCR_100_FINALIZE_MACHINE_DRAFT_REQUIRES_CONFIRMATION",
                    "message": "Pass --confirm-human-reviewed only after a human has corrected values, tables, seals, and evidence boxes.",
                }
            )
            output_tasks.append(task)
            continue

        finalize_task(task, labeler=labeler, reviewer=reviewer, comment=comment, finalized_at=finalized_at, mark_status=mark_status)
        selected.append(task)
        finalized_case_ids.append(case_id)
        output_tasks.append(task)

    readiness = build_annotation_readiness_from_tasks([task for task in output_tasks if isinstance(task, dict)], source=str(output_path))
    selected_statuses = [annotation_task_status(task) for task in selected]
    for status in selected_statuses:
        if not status.get("readyForEval"):
            failures.append(
                {
                    "caseId": status.get("caseId"),
                    "code": "OCR_100_FINALIZE_READINESS_FAILED",
                    "message": "Finalized task still does not pass readiness.",
                    "blockers": status.get("blockers") or [],
                }
            )

    ok = bool(finalized_case_ids) and not failures
    write_ok = bool(ok or allow_incomplete)
    output_payload = deepcopy(payload) if isinstance(payload, dict) else {"tasks": output_tasks}
    output_payload["tasks"] = output_tasks
    summary = {
        "schemaVersion": "aicheck-ocr-100-finalize-labels-summary-v1",
        "generatedAt": finalized_at,
        "source": str(tasks_path),
        "ok": ok,
        "outputWritten": write_ok,
        "finalized": len(finalized_case_ids),
        "finalizedCaseIds": finalized_case_ids,
        "skipped": {key: value for key, value in skipped.items() if value},
        "failureCount": len(failures),
        "readiness": readiness.get("summary", {}),
    }
    report = {
        "schemaVersion": "aicheck-ocr-100-finalize-labels-report-v1",
        "ok": ok,
        "summary": summary,
        "failures": failures,
    }
    output_payload["finalizeLabelSummary"] = summary
    if write_ok:
        write_text_file(output_path, json.dumps(output_payload, ensure_ascii=False, indent=2))
    if report_output:
        write_text_file(report_output, json.dumps(report, ensure_ascii=False, indent=2))
    return {"ok": ok, "summary": summary, "report": report, "payload": output_payload, "readiness": readiness}


def finalize_task(
    task: dict[str, Any],
    *,
    labeler: str,
    reviewer: str,
    comment: str,
    finalized_at: str,
    mark_status: str,
) -> None:
    expected = task.get("labeledExpected") if isinstance(task.get("labeledExpected"), dict) else {}
    review = expected.get("review") if isinstance(expected.get("review"), dict) else {}
    previous_source = str(review.get("source") or "")
    review.update(
        {
            "source": "human_review",
            "labeler": labeler,
            "reviewer": reviewer,
            "reviewedAt": finalized_at,
            "requiresHumanConfirmation": False,
        }
    )
    if previous_source and previous_source != "human_review":
        review["previousSource"] = previous_source
    if comment:
        review["comment"] = comment
    expected["review"] = review
    task["labeledExpected"] = expected
    task["collectionStatus"] = mark_status
    task["labeler"] = labeler
    task["reviewer"] = reviewer
    task["reviewedAt"] = finalized_at
    task.pop("machineDraftLabel", None)


if __name__ == "__main__":
    raise SystemExit(main())
