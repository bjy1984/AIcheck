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

from scripts.ocr_100_annotation_export import resolve_tasks_path
from scripts.ocr_100_corpus import OCR_100_SCENARIO_TARGETS
from scripts.ocr_annotation_readiness import is_machine_draft_label
from scripts.ocr_eval_set import write_text_file


def main() -> int:
    parser = argparse.ArgumentParser(description="Plan OCR 100 failed prelabel retry batches without running OCR.")
    parser.add_argument("annotation_tasks", help="prelabelled_tasks.json, merged prelabel file, or annotation pack directory.")
    parser.add_argument("--manifest-audit", help="Optional ocr_100_manifest_audit.py JSON report.")
    parser.add_argument("--limit", type=int, default=12, help="Maximum retry candidates in the main plan.")
    parser.add_argument("--batch-size", type=int, default=3, help="Maximum caseIds per generated retry command.")
    parser.add_argument("--output", help="Optional JSON retry plan output.")
    parser.add_argument("--csv-output", help="Optional CSV retry plan output.")
    parser.add_argument("--shell-output", help="Optional shell script with prelabel/merge/audit commands.")
    parser.add_argument("--refresh-output", default="./ocr_eval/reports/scan_annotation_pack/prelabelled_retry_refreshed_tasks.json")
    parser.add_argument("--merged-output", default="./ocr_eval/reports/scan_annotation_pack/prelabelled_tasks_retry_merged.json")
    parser.add_argument("--result-dir", default="./ocr_eval/reports/scan_ocr_results_refreshed")
    parser.add_argument("--source-base-dir", default="..")
    parser.add_argument("--engine-timeout-seconds", type=float, default=60.0, help="Timeout value added to generated retry commands.")
    parser.add_argument("--enable-remediation", action="store_true", help="Do not add --disable-remediation to generated retry commands.")
    parser.add_argument("--no-fast-timeouts", action="store_true", help="Do not add --retry-fast-timeouts to generated retry commands.")
    parser.add_argument("--include-mismatches", action="store_true", help="Include manifest mismatch cases in OCR retry batches.")
    args = parser.parse_args()

    plan = build_prelabel_retry_plan(
        Path(args.annotation_tasks),
        manifest_audit_path=Path(args.manifest_audit) if args.manifest_audit else None,
        limit=max(0, int(args.limit)),
        batch_size=max(1, int(args.batch_size)),
        refresh_output=str(args.refresh_output),
        merged_output=str(args.merged_output),
        result_dir=str(args.result_dir),
        source_base_dir=str(args.source_base_dir),
        engine_timeout_seconds=float(args.engine_timeout_seconds),
        fast_timeouts=not bool(args.no_fast_timeouts),
        disable_remediation=not bool(args.enable_remediation),
        include_mismatches=bool(args.include_mismatches),
    )
    if args.output:
        write_text_file(Path(args.output), json.dumps(plan, ensure_ascii=False, indent=2))
    if args.csv_output:
        write_text_file(Path(args.csv_output), prelabel_retry_plan_csv(plan))
    if args.shell_output:
        write_text_file(Path(args.shell_output), prelabel_retry_plan_shell(plan))
    print(json.dumps(plan["summary"], ensure_ascii=False, indent=2))
    return 0


def build_prelabel_retry_plan(
    annotation_tasks: Path,
    *,
    manifest_audit_path: Path | None = None,
    limit: int = 12,
    batch_size: int = 3,
    refresh_output: str,
    merged_output: str,
    result_dir: str,
    source_base_dir: str,
    engine_timeout_seconds: float = 60.0,
    fast_timeouts: bool = True,
    disable_remediation: bool = True,
    include_mismatches: bool = False,
) -> dict[str, Any]:
    tasks_path = resolve_tasks_path(annotation_tasks)
    payload = json.loads(tasks_path.read_text(encoding="utf-8"))
    tasks = payload.get("tasks") if isinstance(payload, dict) else payload
    if not isinstance(tasks, list):
        raise ValueError("annotation tasks must be a JSON object with tasks[] or a raw task list.")
    audit_items = load_manifest_audit_items(manifest_audit_path)
    items = [
        retry_item(task, audit_items=audit_items, include_mismatches=include_mismatches)
        for task in tasks
        if isinstance(task, dict)
    ]
    retry_candidates = [item for item in items if item.get("retryRecommended")]
    retry_candidates = sorted(retry_candidates, key=lambda item: (-float(item.get("priorityScore") or 0), str(item.get("scenario")), str(item.get("caseId"))))
    if limit:
        retry_candidates = retry_candidates[:limit]
    review_first = [item for item in items if item.get("reviewBeforeRetry")]
    batches = retry_batches(
        retry_candidates,
        batch_size=batch_size,
        annotation_tasks=str(tasks_path),
        refresh_output=refresh_output,
        merged_output=merged_output,
        result_dir=result_dir,
        source_base_dir=source_base_dir,
        engine_timeout_seconds=engine_timeout_seconds,
        fast_timeouts=fast_timeouts,
        disable_remediation=disable_remediation,
    )
    retry_reason_counts: Counter[str] = Counter()
    for item in retry_candidates:
        for reason in item.get("retryReasons") or []:
            retry_reason_counts[str(reason)] += 1
    scenario_counts = Counter(str(item.get("scenario") or "unspecified") for item in retry_candidates)
    return {
        "schemaVersion": "aicheck-ocr-100-prelabel-retry-plan-v1",
        "source": str(tasks_path),
        "manifestAudit": str(manifest_audit_path) if manifest_audit_path else None,
        "summary": {
            "tasks": len([task for task in tasks if isinstance(task, dict)]),
            "retryCandidates": len(retry_candidates),
            "reviewBeforeRetry": len(review_first),
            "batchCount": len(batches),
            "batchSize": batch_size,
            "fastTimeouts": bool(fast_timeouts),
            "disableRemediation": bool(disable_remediation),
            "engineTimeoutSeconds": engine_timeout_seconds,
            "retryReasonCounts": dict(sorted(retry_reason_counts.items())),
            "retryScenarioCounts": dict(sorted(scenario_counts.items())),
            "targetScenariosStillMissingCollection": {
                scenario: target
                for scenario, target in OCR_100_SCENARIO_TARGETS.items()
                if scenario not in scenario_counts
            },
        },
        "retryCandidates": retry_candidates,
        "reviewBeforeRetry": review_first,
        "batches": batches,
    }


def load_manifest_audit_items(path: Path | None) -> dict[str, dict[str, Any]]:
    if not path:
        return {}
    payload = json.loads(path.expanduser().read_text(encoding="utf-8"))
    items = payload.get("items") if isinstance(payload, dict) else []
    output: dict[str, dict[str, Any]] = {}
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        case_id = str(item.get("caseId") or "").strip()
        if case_id:
            output[case_id] = item
    return output


def retry_item(task: dict[str, Any], *, audit_items: dict[str, dict[str, Any]], include_mismatches: bool) -> dict[str, Any]:
    case_id = str(task.get("caseId") or task.get("taskId") or "").strip()
    suggested = task.get("suggestedExpected") if isinstance(task.get("suggestedExpected"), dict) else {}
    summary = task.get("prelabelSummary") if isinstance(task.get("prelabelSummary"), dict) else {}
    audit = audit_items.get(case_id, {})
    quality_status = str(suggested.get("qualityStatus") or "")
    prelabel_status = str(task.get("prelabelStatus") or "")
    has_label = isinstance(task.get("labeledExpected"), dict)
    machine_draft = bool(has_label and is_machine_draft_label(task, task.get("labeledExpected")))
    retry_reasons: list[str] = []
    review_reasons: list[str] = []

    if has_label and not machine_draft:
        review_reasons.append("already_human_labeled")
    if machine_draft:
        review_reasons.append("machine_draft_needs_human_confirmation")
    if audit.get("status") == "mismatch":
        review_reasons.append("manifest_mismatch_review_required")
        if include_mismatches:
            retry_reasons.append("manifest_mismatch_included")
    if audit.get("ocrTextAvailable") is False:
        retry_reasons.append("manifest_missing_ocr_text")
    if prelabel_status in {"unavailable", "empty", ""}:
        retry_reasons.append(f"prelabel_status_{prelabel_status or 'missing'}")
    if quality_status == "failed":
        retry_reasons.append("quality_failed")
    if not suggested:
        retry_reasons.append("missing_suggested_expected")
    diagnostics = suggested.get("diagnostics") if isinstance(suggested.get("diagnostics"), list) else []
    diagnostic_codes = [str(item.get("code") or "") for item in diagnostics if isinstance(item, dict)]
    if "NO_LOCAL_OCR_RESULT" in diagnostic_codes:
        retry_reasons.append("no_local_ocr_result")
    if summary.get("source") == "result_dir" and quality_status == "failed":
        retry_reasons.append("stale_failed_result_dir")
    if not any(suggested.get(key) for key in ["fields", "tables", "seals"]) and quality_status in {"failed", ""}:
        retry_reasons.append("no_machine_candidates")

    retry_reasons = sorted(set(retry_reasons))
    review_reasons = sorted(set(review_reasons))
    review_before_retry = bool(review_reasons and "manifest_mismatch_review_required" in review_reasons and not include_mismatches)
    retry_recommended = bool(retry_reasons) and not has_label and not review_before_retry
    return {
        "caseId": case_id,
        "taskId": task.get("taskId"),
        "scenario": task.get("scenario"),
        "profileId": task.get("profileId"),
        "documentType": task.get("documentType"),
        "sourcePath": task.get("sourcePath"),
        "prelabelStatus": prelabel_status,
        "qualityStatus": quality_status,
        "fieldSuggestions": len(suggested.get("fields") or []),
        "tableSuggestions": len(suggested.get("tables") or []),
        "sealSuggestions": len(suggested.get("seals") or []),
        "manifestStatus": audit.get("status"),
        "suggestedScenario": audit.get("suggestedScenario"),
        "retryRecommended": retry_recommended,
        "reviewBeforeRetry": review_before_retry,
        "retryReasons": retry_reasons,
        "reviewReasons": review_reasons,
        "priorityScore": retry_priority_score(task, retry_reasons=retry_reasons, audit=audit),
    }


def retry_priority_score(task: dict[str, Any], *, retry_reasons: list[str], audit: dict[str, Any]) -> float:
    score = 10.0
    scenario = str(task.get("scenario") or "")
    if scenario in OCR_100_SCENARIO_TARGETS:
        score += 5.0
    if "no_local_ocr_result" in retry_reasons or "stale_failed_result_dir" in retry_reasons:
        score += 8.0
    if "manifest_missing_ocr_text" in retry_reasons:
        score += 5.0
    if "no_machine_candidates" in retry_reasons:
        score += 3.0
    if audit.get("status") == "mismatch":
        score -= 6.0
    return max(round(score, 4), 0.0)


def retry_batches(
    items: list[dict[str, Any]],
    *,
    batch_size: int,
    annotation_tasks: str,
    refresh_output: str,
    merged_output: str,
    result_dir: str,
    source_base_dir: str,
    engine_timeout_seconds: float,
    fast_timeouts: bool,
    disable_remediation: bool,
) -> list[dict[str, Any]]:
    batches: list[dict[str, Any]] = []
    for index in range(0, len(items), batch_size):
        chunk = items[index : index + batch_size]
        batch_no = len(batches) + 1
        case_ids = [str(item.get("caseId")) for item in chunk]
        refresh_path = suffixed_path(refresh_output, batch_no)
        merged_path = suffixed_path(merged_output, batch_no)
        prelabel_command = " ".join(
            [
                "python scripts/ocr_100_annotation_prelabel.py",
                shell_quote(annotation_tasks),
                "--output",
                shell_quote(refresh_path),
                "--source-base-dir",
                shell_quote(source_base_dir),
                "--run-ocr",
                "--disable-result-cache",
                "--auto-discover-runtime",
                "--save-result-dir",
                shell_quote(result_dir),
                *(["--retry-fast-timeouts", "--engine-timeout-seconds", shell_quote(engine_timeout_seconds)] if fast_timeouts else []),
                *(["--disable-remediation"] if disable_remediation else []),
                *(f"--case-id {shell_quote(case_id)}" for case_id in case_ids),
            ]
        )
        merge_command = " ".join(
            [
                "python scripts/ocr_100_annotation_merge_prelabels.py",
                shell_quote(annotation_tasks if batch_no == 1 else suffixed_path(merged_output, batch_no - 1)),
                shell_quote(refresh_path),
                "--output",
                shell_quote(merged_path),
            ]
        )
        batches.append(
            {
                "batch": batch_no,
                "caseIds": case_ids,
                "prelabelOutput": refresh_path,
                "mergedOutput": merged_path,
                "prelabelCommand": prelabel_command,
                "mergeCommand": merge_command,
            }
        )
    return batches


def suffixed_path(path: str, batch_no: int) -> str:
    source = Path(path)
    if batch_no <= 1:
        return str(source)
    return str(source.with_name(f"{source.stem}_batch{batch_no}{source.suffix}"))


def shell_quote(value: Any) -> str:
    text = str(value)
    if not text:
        return "''"
    if all(char.isalnum() or char in "-_./:=," for char in text):
        return text
    return "'" + text.replace("'", "'\"'\"'") + "'"


def prelabel_retry_plan_csv(plan: dict[str, Any]) -> str:
    fieldnames = [
        "priorityScore",
        "caseId",
        "scenario",
        "profileId",
        "qualityStatus",
        "manifestStatus",
        "suggestedScenario",
        "retryRecommended",
        "reviewBeforeRetry",
        "retryReasons",
        "reviewReasons",
        "sourcePath",
    ]
    handle = StringIO()
    writer = csv.DictWriter(handle, fieldnames=fieldnames)
    writer.writeheader()
    for item in [*(plan.get("retryCandidates") or []), *(plan.get("reviewBeforeRetry") or [])]:
        writer.writerow(
            {
                key: "; ".join(str(value) for value in item.get(key) or [])
                if key in {"retryReasons", "reviewReasons"}
                else item.get(key)
                for key in fieldnames
            }
        )
    return handle.getvalue()


def prelabel_retry_plan_shell(plan: dict[str, Any]) -> str:
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        "# Generated by ocr_100_prelabel_retry_plan.py. Review caseIds before running.",
    ]
    for batch in plan.get("batches") or []:
        lines.extend(
            [
                "",
                f"# Batch {batch.get('batch')}: {', '.join(batch.get('caseIds') or [])}",
                str(batch.get("prelabelCommand")),
                str(batch.get("mergeCommand")),
            ]
        )
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
