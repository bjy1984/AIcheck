from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.ocr_100_annotation_sprint import build_annotation_sprint_plan
from scripts.ocr_100_corpus import OCR_100_SCENARIO_TARGETS, SCENARIO_COLLECTION_HINTS
from scripts.ocr_eval_set import write_text_file


def main() -> int:
    parser = argparse.ArgumentParser(description="Build an OCR 100 closure plan from scorecard, annotation, and collection evidence.")
    parser.add_argument("annotation_tasks", help="prelabelled/labeled annotation tasks JSON or annotation pack directory.")
    parser.add_argument("--scorecard", help="Optional ocr_100_scorecard.json path.")
    parser.add_argument("--manifest-audit", help="Optional scan manifest audit JSON path.")
    parser.add_argument("--retry-plan", help="Optional prelabel retry plan JSON path.")
    parser.add_argument("--limit", type=int, default=30, help="Maximum current-labeling work items to include.")
    parser.add_argument("--output", help="Optional JSON output path.")
    parser.add_argument("--markdown-output", help="Optional Markdown output path.")
    args = parser.parse_args()

    plan = build_ocr_100_closure_plan(
        Path(args.annotation_tasks),
        scorecard_path=Path(args.scorecard) if args.scorecard else None,
        manifest_audit_path=Path(args.manifest_audit) if args.manifest_audit else None,
        retry_plan_path=Path(args.retry_plan) if args.retry_plan else None,
        limit=int(args.limit),
    )
    if args.output:
        write_text_file(Path(args.output), json.dumps(plan, ensure_ascii=False, indent=2))
    if args.markdown_output:
        write_text_file(Path(args.markdown_output), closure_plan_markdown(plan))
    print(json.dumps(plan["summary"], ensure_ascii=False, indent=2))
    return 0 if plan["summary"].get("scorecardOk") else 1


def build_ocr_100_closure_plan(
    annotation_tasks: Path,
    *,
    scorecard_path: Path | None = None,
    manifest_audit_path: Path | None = None,
    retry_plan_path: Path | None = None,
    limit: int = 30,
) -> dict[str, Any]:
    sprint = build_annotation_sprint_plan(annotation_tasks, limit=limit)
    scorecard = read_json(scorecard_path) if scorecard_path else {}
    manifest_audit = read_json(manifest_audit_path) if manifest_audit_path else {}
    retry_plan = read_json(retry_plan_path) if retry_plan_path else {}
    scenario_plan = sprint.get("scenarioPlan") if isinstance(sprint.get("scenarioPlan"), dict) else {}
    scorecard_sections = scorecard_section_status(scorecard)
    retry_candidates = safe_int(retry_plan.get("retryCandidates"))
    missing_ocr_text = safe_int(manifest_audit.get("missingOcrText"))
    total_collection_missing = sum(safe_int(item.get("collectionMissingCases")) for item in scenario_plan.values() if isinstance(item, dict))
    total_missing_ready = sum(safe_int(item.get("missingReadyCases")) for item in scenario_plan.values() if isinstance(item, dict))
    ready_for_eval = safe_int(sprint.get("summary", {}).get("readyForEval"))
    human_labeled = safe_int(sprint.get("summary", {}).get("humanLabeled"))
    task_count = safe_int(sprint.get("summary", {}).get("tasks"))
    closure_status = closure_status_for(
        scorecard=scorecard,
        retry_candidates=retry_candidates,
        missing_ocr_text=missing_ocr_text,
        ready_for_eval=ready_for_eval,
        total_missing_ready=total_missing_ready,
        total_collection_missing=total_collection_missing,
    )
    return {
        "schemaVersion": "aicheck-ocr-100-closure-plan-v1",
        "source": {
            "annotationTasks": sprint.get("source"),
            "scorecard": str(scorecard_path) if scorecard_path else None,
            "manifestAudit": str(manifest_audit_path) if manifest_audit_path else None,
            "retryPlan": str(retry_plan_path) if retry_plan_path else None,
        },
        "summary": {
            "status": closure_status,
            "score": scorecard.get("score"),
            "scorecardOk": bool(scorecard.get("ok")),
            "scorecardBlockers": scorecard.get("blockers") or [],
            "scorecardSections": scorecard_sections,
            "tasks": task_count,
            "humanLabeled": human_labeled,
            "readyForEval": ready_for_eval,
            "requiredReadyForEval": sum(OCR_100_SCENARIO_TARGETS.values()),
            "missingReadyCases": total_missing_ready,
            "collectionMissingCases": total_collection_missing,
            "retryCandidates": retry_candidates,
            "missingOcrText": missing_ocr_text,
            "automationReady": retry_candidates == 0 and missing_ocr_text == 0,
        },
        "gates": gate_items(
            scorecard=scorecard,
            scorecard_sections=scorecard_sections,
            ready_for_eval=ready_for_eval,
            missing_ready=total_missing_ready,
            collection_missing=total_collection_missing,
            retry_candidates=retry_candidates,
            missing_ocr_text=missing_ocr_text,
        ),
        "scenarioPlan": scenario_closure_items(scenario_plan),
        "labelingSprint": sprint.get("workItems") or [],
        "commands": recommended_commands(annotation_tasks),
        "nextActions": next_actions_for(
            retry_candidates=retry_candidates,
            missing_ocr_text=missing_ocr_text,
            total_collection_missing=total_collection_missing,
            ready_for_eval=ready_for_eval,
            task_count=task_count,
        ),
    }


def read_json(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    payload = json.loads(path.expanduser().resolve().read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def scorecard_section_status(scorecard: dict[str, Any]) -> dict[str, str]:
    output: dict[str, str] = {}
    for section in scorecard.get("sections") or []:
        if not isinstance(section, dict):
            continue
        name = str(section.get("name") or "")
        if name:
            output[name] = str(section.get("status") or "unknown")
    return output


def closure_status_for(
    *,
    scorecard: dict[str, Any],
    retry_candidates: int,
    missing_ocr_text: int,
    ready_for_eval: int,
    total_missing_ready: int,
    total_collection_missing: int,
) -> str:
    if scorecard.get("ok") is True:
        return "complete"
    if retry_candidates > 0 or missing_ocr_text > 0:
        return "needs_ocr_retry"
    if total_collection_missing > 0:
        return "needs_sample_collection"
    if total_missing_ready > 0 or ready_for_eval < sum(OCR_100_SCENARIO_TARGETS.values()):
        return "needs_human_annotation"
    return "needs_scorecard_rerun"


def gate_items(
    *,
    scorecard: dict[str, Any],
    scorecard_sections: dict[str, str],
    ready_for_eval: int,
    missing_ready: int,
    collection_missing: int,
    retry_candidates: int,
    missing_ocr_text: int,
) -> list[dict[str, Any]]:
    required_cases = sum(OCR_100_SCENARIO_TARGETS.values())
    return [
        {
            "gate": "runtime",
            "status": scorecard_sections.get("runtime", "unknown"),
            "complete": scorecard_sections.get("runtime") == "pass",
            "evidence": "ocr_100_scorecard.sections.runtime",
        },
        {
            "gate": "sample_probes",
            "status": scorecard_sections.get("sample-probes", "unknown"),
            "complete": scorecard_sections.get("sample-probes") == "pass",
            "evidence": "ocr_100_scorecard.sections.sample-probes",
        },
        {
            "gate": "observability",
            "status": scorecard_sections.get("observability", "unknown"),
            "complete": scorecard_sections.get("observability") == "pass",
            "evidence": "ocr_100_scorecard.sections.observability",
        },
        {
            "gate": "automation_retry",
            "status": "pass" if retry_candidates == 0 and missing_ocr_text == 0 else "fail",
            "complete": retry_candidates == 0 and missing_ocr_text == 0,
            "evidence": {"retryCandidates": retry_candidates, "missingOcrText": missing_ocr_text},
        },
        {
            "gate": "human_labeled_release_set",
            "status": "pass" if ready_for_eval >= required_cases and missing_ready == 0 else "fail",
            "complete": ready_for_eval >= required_cases and missing_ready == 0,
            "evidence": {"readyForEval": ready_for_eval, "requiredReadyForEval": required_cases, "missingReadyCases": missing_ready},
        },
        {
            "gate": "sample_collection",
            "status": "pass" if collection_missing == 0 else "fail",
            "complete": collection_missing == 0,
            "evidence": {"collectionMissingCases": collection_missing},
        },
        {
            "gate": "scorecard",
            "status": "pass" if scorecard.get("ok") is True else "fail",
            "complete": scorecard.get("ok") is True,
            "evidence": {"score": scorecard.get("score"), "blockers": scorecard.get("blockers") or []},
        },
    ]


def scenario_closure_items(scenario_plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for scenario, target in OCR_100_SCENARIO_TARGETS.items():
        item = scenario_plan.get(scenario) if isinstance(scenario_plan.get(scenario), dict) else {}
        output[scenario] = {
            "targetCases": target,
            "queuedCases": safe_int(item.get("queuedCases")),
            "readyForEval": safe_int(item.get("readyForEval")),
            "missingReadyCases": safe_int(item.get("missingReadyCases"), default=target),
            "collectionMissingCases": safe_int(item.get("collectionMissingCases"), default=target),
            "reviewBacklogCases": safe_int(item.get("reviewBacklogCases")),
            "collectionHint": item.get("collectionHint") or SCENARIO_COLLECTION_HINTS.get(scenario, ""),
        }
    return output


def recommended_commands(annotation_tasks: Path) -> dict[str, str]:
    task_arg = str(annotation_tasks)
    return {
        "labelStudioExport": f"python scripts/ocr_100_label_studio_export.py {task_arg} --output-dir ocr_eval/reports/scan_label_studio",
        "importReviewedLabels": "python scripts/ocr_100_label_studio_import.py ocr_eval/reports/scan_label_studio/label_studio_tasks.json <label-studio-export.json> --output ocr_eval/reports/scan_annotation_pack/labeled_tasks.json",
        "readiness": f"python scripts/ocr_annotation_readiness.py {task_arg} --strict",
        "exportEvalSet": f"python scripts/ocr_100_annotation_export.py {task_arg} --output ocr_eval/reports/ocr_100_labeled_release_set.json",
        "scorecard": "python scripts/ocr_100_scorecard.py --eval-set ocr_eval/reports/ocr_100_labeled_release_set.json --sample-summary ocr_eval/reports/img6509_sample_probe_summary.json --auto-discover-runtime",
    }


def next_actions_for(
    *,
    retry_candidates: int,
    missing_ocr_text: int,
    total_collection_missing: int,
    ready_for_eval: int,
    task_count: int,
) -> list[str]:
    actions: list[str] = []
    if retry_candidates > 0 or missing_ocr_text > 0:
        actions.append("Run the generated prelabel retry plan until retryCandidates=0 and missingOcrText=0.")
    if task_count > ready_for_eval:
        actions.append("Human-review existing machine suggestions, correct labels/bboxes, then set collectionStatus=ready_for_eval with separate labeler/reviewer.")
    if total_collection_missing > 0:
        actions.append("Collect/import additional real samples for scenarios with collectionMissingCases > 0.")
    actions.append("Export the reviewed eval set and rerun ocr_100_scorecard.py.")
    return actions


def closure_plan_markdown(plan: dict[str, Any]) -> str:
    summary = plan.get("summary", {})
    lines = [
        "# OCR 100 Closure Plan",
        "",
        f"- Status: {summary.get('status')}",
        f"- Score: {summary.get('score')}",
        f"- Scorecard OK: {summary.get('scorecardOk')}",
        f"- Automation ready: {summary.get('automationReady')}",
        f"- Ready for eval: {summary.get('readyForEval')} / {summary.get('requiredReadyForEval')}",
        f"- Missing ready cases: {summary.get('missingReadyCases')}",
        f"- Collection missing cases: {summary.get('collectionMissingCases')}",
        f"- Retry candidates: {summary.get('retryCandidates')}",
        f"- Missing OCR text: {summary.get('missingOcrText')}",
        "",
        "## Gates",
        "",
        "| Gate | Status | Complete | Evidence |",
        "| --- | --- | --- | --- |",
    ]
    for gate in plan.get("gates") or []:
        lines.append(
            f"| {gate.get('gate')} | {gate.get('status')} | {gate.get('complete')} | "
            f"{json.dumps(gate.get('evidence'), ensure_ascii=False)} |"
        )
    lines.extend(["", "## Scenario Closure", "", "| Scenario | Target | Queued | Ready | Need Ready | Need Collection | Hint |", "| --- | ---: | ---: | ---: | ---: | ---: | --- |"])
    for scenario, item in (plan.get("scenarioPlan") or {}).items():
        lines.append(
            f"| {scenario} | {item.get('targetCases')} | {item.get('queuedCases')} | {item.get('readyForEval')} | "
            f"{item.get('missingReadyCases')} | {item.get('collectionMissingCases')} | {item.get('collectionHint')} |"
        )
    lines.extend(["", "## Top Labeling Sprint", "", "| Priority | Case | Scenario | Suggested | Blockers |", "| ---: | --- | --- | --- | --- |"])
    for item in plan.get("labelingSprint") or []:
        suggested = item.get("suggestedCounts") or {}
        suggested_text = ",".join(f"{key}:{value}" for key, value in suggested.items())
        blockers = ", ".join(item.get("blockers") or [])
        lines.append(f"| {item.get('priorityScore')} | {item.get('caseId')} | {item.get('scenario')} | {suggested_text} | {blockers} |")
    lines.extend(["", "## Commands", ""])
    for key, command in (plan.get("commands") or {}).items():
        lines.extend([f"### {key}", "", f"```bash\n{command}\n```", ""])
    lines.extend(["## Next Actions", ""])
    for action in plan.get("nextActions") or []:
        lines.append(f"- {action}")
    lines.append("")
    return "\n".join(lines)


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


if __name__ == "__main__":
    raise SystemExit(main())
