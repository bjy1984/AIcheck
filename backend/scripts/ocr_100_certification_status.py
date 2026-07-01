from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.ocr_eval_set import write_text_file


DEFAULT_REPORT_DIR = Path("ocr_eval/reports")


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize OCR 100 certification status from scorecard, sample, and reviewed-label reports.")
    parser.add_argument("--reports-dir", default=str(DEFAULT_REPORT_DIR), help="Base reports directory used to auto-discover missing report paths.")
    parser.add_argument("--scorecard", help="ocr_100_scorecard.json path.")
    parser.add_argument("--closure-plan", help="ocr_100_closure_plan*.json path.")
    parser.add_argument("--intake-verify", help="collection intake verify JSON path.")
    parser.add_argument("--intake-pipeline", help="collection intake pipeline JSON path.")
    parser.add_argument("--reviewed-label-gate", help="reviewed_label_gate.json path.")
    parser.add_argument("--output", help="Optional JSON output path.")
    parser.add_argument("--markdown-output", help="Optional Markdown output path.")
    parser.add_argument("--strict", action="store_true", help="Return non-zero unless scorecard is complete.")
    args = parser.parse_args()

    paths = default_report_paths(
        Path(args.reports_dir),
        scorecard=Path(args.scorecard) if args.scorecard else None,
        closure_plan=Path(args.closure_plan) if args.closure_plan else None,
        intake_verify=Path(args.intake_verify) if args.intake_verify else None,
        intake_pipeline=Path(args.intake_pipeline) if args.intake_pipeline else None,
        reviewed_label_gate=Path(args.reviewed_label_gate) if args.reviewed_label_gate else None,
    )
    report = build_certification_status(paths)
    if args.output:
        write_text_file(Path(args.output), json.dumps(report, ensure_ascii=False, indent=2))
    if args.markdown_output:
        write_text_file(Path(args.markdown_output), certification_status_markdown(report))
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 0 if (report.get("ok") or not args.strict) else 1


def default_report_paths(
    reports_dir: Path,
    *,
    scorecard: Path | None = None,
    closure_plan: Path | None = None,
    intake_verify: Path | None = None,
    intake_pipeline: Path | None = None,
    reviewed_label_gate: Path | None = None,
) -> dict[str, Path | None]:
    reports_dir = reports_dir.expanduser()
    return {
        "scorecard": scorecard or reports_dir / "ocr_100_scorecard.json",
        "closurePlan": closure_plan or latest_match(reports_dir, "ocr_100_closure_plan*.json"),
        "intakeVerify": intake_verify or latest_match(reports_dir, "ocr_100_sample_intake_*/verify_autofilled.json"),
        "intakePipeline": intake_pipeline or latest_match(reports_dir, "ocr_100_sample_intake_*/pipeline.json"),
        "reviewedLabelGate": reviewed_label_gate or latest_match(reports_dir, "reviewed_label_gate*/reviewed_label_gate.json"),
    }


def latest_match(base: Path, pattern: str) -> Path | None:
    matches = [path for path in base.glob(pattern) if path.is_file()]
    if not matches:
        return None
    return max(matches, key=lambda path: path.stat().st_mtime)


def build_certification_status(paths: dict[str, Path | None]) -> dict[str, Any]:
    loaded = {name: load_report(path) for name, path in paths.items()}
    scorecard = loaded["scorecard"]["payload"]
    closure = loaded["closurePlan"]["payload"]
    intake = loaded["intakeVerify"]["payload"]
    pipeline = loaded["intakePipeline"]["payload"]
    reviewed_gate = loaded["reviewedLabelGate"]["payload"]

    scorecard_summary = scorecard_summary_from(scorecard)
    closure_summary = summary_from(closure)
    intake_summary = summary_from(intake)
    pipeline_summary = summary_from(pipeline)
    reviewed_summary = summary_from(reviewed_gate)
    missing_reports = [
        {"name": name, "path": str(item.get("path") or ""), "reason": item.get("reason")}
        for name, item in loaded.items()
        if item.get("missing")
    ]

    required_ready = safe_int(closure_summary.get("requiredReadyForEval"), 100)
    ready_for_eval = safe_int(reviewed_summary.get("readyForEval"), safe_int(closure_summary.get("readyForEval"), 0))
    human_labeled = safe_int(reviewed_summary.get("humanLabeled"), safe_int(closure_summary.get("humanLabeled"), 0))
    collection_missing = safe_int(closure_summary.get("collectionMissingCases"), None)
    placeholder_slots = safe_int(intake_summary.get("placeholderSlots"), None)
    filled_slots = safe_int(intake_summary.get("filledSlots"), None)
    score = scorecard_summary.get("score")
    scorecard_ok = scorecard_summary.get("ok") is True
    status = certification_status_for(
        scorecard_ok=scorecard_ok,
        missing_reports=missing_reports,
        collection_missing=collection_missing,
        placeholder_slots=placeholder_slots,
        ready_for_eval=ready_for_eval,
        required_ready=required_ready,
        reviewed_summary=reviewed_summary,
        pipeline_summary=pipeline_summary,
    )
    gates = build_gates(
        scorecard=scorecard,
        scorecard_ok=scorecard_ok,
        collection_missing=collection_missing,
        placeholder_slots=placeholder_slots,
        ready_for_eval=ready_for_eval,
        required_ready=required_ready,
        reviewed_summary=reviewed_summary,
        pipeline_summary=pipeline_summary,
    )
    blockers = certification_blockers(
        scorecard=scorecard,
        missing_reports=missing_reports,
        collection_missing=collection_missing,
        placeholder_slots=placeholder_slots,
        ready_for_eval=ready_for_eval,
        required_ready=required_ready,
        reviewed_gate=reviewed_gate,
    )
    next_actions = next_actions_for(
        status=status,
        intake_summary=intake_summary,
        pipeline_summary=pipeline_summary,
        reviewed_summary=reviewed_summary,
        closure_summary=closure_summary,
    )
    summary = {
        "schemaVersion": "aicheck-ocr-100-certification-status-v1",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "ok": scorecard_ok,
        "score": score,
        "scorecardOk": scorecard_ok,
        "tasks": safe_int(closure_summary.get("tasks"), safe_int(reviewed_summary.get("tasks"), 0)),
        "humanLabeled": human_labeled,
        "readyForEval": ready_for_eval,
        "requiredReadyForEval": required_ready,
        "collectionMissingCases": collection_missing,
        "filledSampleSlots": filled_slots,
        "placeholderSampleSlots": placeholder_slots,
        "missingReportCount": len(missing_reports),
        "blockerCount": len(blockers),
    }
    return {
        "schemaVersion": "aicheck-ocr-100-certification-status-v1",
        "ok": scorecard_ok,
        "summary": summary,
        "reports": {name: report_metadata(name, item) for name, item in loaded.items()},
        "gates": gates,
        "blockers": blockers,
        "nextActions": next_actions,
        "scenarioGaps": scenario_gaps_from(closure, intake),
    }


def load_report(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {"missing": True, "path": None, "reason": "not_found", "payload": {}}
    resolved = path.expanduser()
    if not resolved.exists():
        return {"missing": True, "path": str(resolved), "reason": "not_found", "payload": {}}
    try:
        return {"missing": False, "path": str(resolved), "payload": json.loads(resolved.read_text(encoding="utf-8"))}
    except json.JSONDecodeError as exc:
        return {"missing": True, "path": str(resolved), "reason": f"invalid_json:{exc}", "payload": {}}


def report_metadata(name: str, item: dict[str, Any]) -> dict[str, Any]:
    payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
    return {
        "name": name,
        "path": item.get("path"),
        "missing": bool(item.get("missing")),
        "schemaVersion": payload.get("schemaVersion"),
        "ok": payload.get("ok"),
    }


def summary_from(payload: Any) -> dict[str, Any]:
    return payload.get("summary") if isinstance(payload, dict) and isinstance(payload.get("summary"), dict) else {}


def scorecard_summary_from(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    return {
        "ok": payload.get("ok"),
        "score": payload.get("score"),
        "blockers": payload.get("blockers") or [],
    }


def certification_status_for(
    *,
    scorecard_ok: bool,
    missing_reports: list[dict[str, Any]],
    collection_missing: int | None,
    placeholder_slots: int | None,
    ready_for_eval: int,
    required_ready: int,
    reviewed_summary: dict[str, Any],
    pipeline_summary: dict[str, Any],
) -> str:
    if scorecard_ok:
        return "complete"
    if missing_reports:
        return "needs_evidence_reports"
    if positive(collection_missing) or positive(placeholder_slots):
        return "needs_sample_files"
    if pipeline_summary.get("readyToExecute") is True and not reviewed_summary:
        return "ready_to_ingest_and_label"
    if ready_for_eval < required_ready:
        return "needs_human_labels"
    if not reviewed_summary.get("evalSetWritten"):
        return "needs_release_eval_export"
    return "needs_scorecard_rerun"


def build_gates(
    *,
    scorecard: dict[str, Any],
    scorecard_ok: bool,
    collection_missing: int | None,
    placeholder_slots: int | None,
    ready_for_eval: int,
    required_ready: int,
    reviewed_summary: dict[str, Any],
    pipeline_summary: dict[str, Any],
) -> list[dict[str, Any]]:
    gates: list[dict[str, Any]] = []
    section_statuses = {
        str(section.get("name")): str(section.get("status"))
        for section in scorecard.get("sections") or []
        if isinstance(section, dict)
    } if isinstance(scorecard, dict) else {}
    for name in ["runtime", "sample-probes", "observability", "evaluation"]:
        gates.append(
            {
                "gate": f"scorecard.{name}",
                "status": section_statuses.get(name, "unknown"),
                "complete": section_statuses.get(name) == "pass",
            }
        )
    gates.extend(
        [
            {
                "gate": "sample_collection",
                "status": "pass" if not positive(collection_missing) and not positive(placeholder_slots) else "fail",
                "complete": not positive(collection_missing) and not positive(placeholder_slots),
                "evidence": {"collectionMissingCases": collection_missing, "placeholderSlots": placeholder_slots},
            },
            {
                "gate": "intake_pipeline",
                "status": "pass" if pipeline_summary.get("readyToExecute") else "fail",
                "complete": bool(pipeline_summary.get("readyToExecute")),
                "evidence": {"readyToExecute": pipeline_summary.get("readyToExecute")},
            },
            {
                "gate": "human_reviewed_release_set",
                "status": "pass" if ready_for_eval >= required_ready else "fail",
                "complete": ready_for_eval >= required_ready,
                "evidence": {"readyForEval": ready_for_eval, "requiredReadyForEval": required_ready},
            },
            {
                "gate": "reviewed_label_gate",
                "status": "pass" if reviewed_summary.get("ready") else "fail",
                "complete": bool(reviewed_summary.get("ready")),
                "evidence": {
                    "readinessOk": reviewed_summary.get("readinessOk"),
                    "evalSetWritten": reviewed_summary.get("evalSetWritten"),
                },
            },
            {"gate": "scorecard", "status": "pass" if scorecard_ok else "fail", "complete": scorecard_ok},
        ]
    )
    return gates


def certification_blockers(
    *,
    scorecard: dict[str, Any],
    missing_reports: list[dict[str, Any]],
    collection_missing: int | None,
    placeholder_slots: int | None,
    ready_for_eval: int,
    required_ready: int,
    reviewed_gate: dict[str, Any],
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    for item in missing_reports:
        blockers.append({"code": "REPORT_MISSING", "message": f"{item.get('name')} report is missing.", "detail": item})
    if missing_reports:
        return blockers
    if positive(collection_missing):
        blockers.append({"code": "SAMPLE_COLLECTION_INCOMPLETE", "message": f"{collection_missing} real sample collection slot(s) are still missing."})
    if positive(placeholder_slots):
        blockers.append({"code": "SAMPLE_MANIFEST_PLACEHOLDERS", "message": f"{placeholder_slots} sample manifest slot(s) still use placeholder file names."})
    if ready_for_eval < required_ready:
        blockers.append({"code": "HUMAN_GOLD_SET_INCOMPLETE", "message": f"{ready_for_eval}/{required_ready} cases are ready for evaluation."})
    if isinstance(reviewed_gate, dict):
        for failure in reviewed_gate.get("failures") or []:
            if isinstance(failure, dict):
                blockers.append({"code": str(failure.get("code") or "REVIEWED_LABEL_GATE_FAILURE"), "message": str(failure.get("message") or "")})
    if isinstance(scorecard, dict):
        for blocker in scorecard.get("blockers") or []:
            blockers.append({"code": "SCORECARD_BLOCKER", "message": str(blocker)})
    return blockers


def next_actions_for(
    *,
    status: str,
    intake_summary: dict[str, Any],
    pipeline_summary: dict[str, Any],
    reviewed_summary: dict[str, Any],
    closure_summary: dict[str, Any],
) -> list[str]:
    if status == "complete":
        return ["OCR 100 scorecard is complete; keep the release eval set under regression control."]
    if status == "needs_evidence_reports":
        return ["Regenerate scorecard, closure plan, intake verification, pipeline, and reviewed-label gate reports."]
    if status == "needs_sample_files":
        intake_dir = intake_summary.get("intakeDir") or pipeline_summary.get("intakeDir") or "ocr_eval/reports/ocr_100_sample_intake_*/"
        return [
            f"Put real customer/field OCR samples into {intake_dir}/samples/<scenario>/.",
            "Run the intake autofill and verify commands, then run pipelineExecute when strict verification passes.",
        ]
    if status == "ready_to_ingest_and_label":
        return ["Run pipelineExecute to build the annotation pack, then send it to Label Studio for human review."]
    if status == "needs_human_labels":
        return [
            "Human-review machine suggestions in Label Studio, replace placeholders, and add positive-area evidence boxes.",
            "Export Label Studio annotations and run ocr_100_reviewed_label_gate.py.",
        ]
    if status == "needs_release_eval_export":
        return ["Run reviewedLabelGate to export ocr_100_labeled_release_set.json."]
    return ["Rerun ocr_100_scorecard.py against the reviewed release eval set and sample probe summaries."]


def scenario_gaps_from(closure: Any, intake: Any) -> list[dict[str, Any]]:
    closure_plan = closure.get("scenarioPlan") if isinstance(closure, dict) and isinstance(closure.get("scenarioPlan"), dict) else {}
    intake_scenarios = summary_from(intake).get("scenarioSummary") if isinstance(summary_from(intake).get("scenarioSummary"), dict) else {}
    scenarios = sorted({*closure_plan.keys(), *intake_scenarios.keys()})
    output: list[dict[str, Any]] = []
    for scenario in scenarios:
        closure_item = closure_plan.get(scenario) if isinstance(closure_plan.get(scenario), dict) else {}
        intake_item = intake_scenarios.get(scenario) if isinstance(intake_scenarios.get(scenario), dict) else {}
        output.append(
            {
                "scenario": scenario,
                "targetCases": closure_item.get("targetCases"),
                "queuedCases": closure_item.get("queuedCases"),
                "readyForEval": closure_item.get("readyForEval"),
                "collectionMissingCases": closure_item.get("collectionMissingCases"),
                "slots": intake_item.get("slots"),
                "filled": intake_item.get("filled"),
                "placeholders": intake_item.get("placeholders"),
                "collectionHint": closure_item.get("collectionHint"),
            }
        )
    return output


def certification_status_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    lines = [
        "# OCR 100 Certification Status",
        "",
        f"- Status: {summary.get('status')}",
        f"- Score: {summary.get('score')}",
        f"- Scorecard OK: {summary.get('scorecardOk')}",
        f"- Ready for eval: {summary.get('readyForEval')} / {summary.get('requiredReadyForEval')}",
        f"- Missing sample cases: {summary.get('collectionMissingCases')}",
        f"- Placeholder sample slots: {summary.get('placeholderSampleSlots')}",
        "",
        "## Gates",
        "",
        "| Gate | Status | Complete | Evidence |",
        "| --- | --- | --- | --- |",
    ]
    for gate in report.get("gates") or []:
        if isinstance(gate, dict):
            evidence = json.dumps(gate.get("evidence") or {}, ensure_ascii=False)
            lines.append(f"| {gate.get('gate')} | {gate.get('status')} | {gate.get('complete')} | `{evidence}` |")
    lines.extend(["", "## Blockers", ""])
    blockers = report.get("blockers") if isinstance(report.get("blockers"), list) else []
    if blockers:
        lines.extend(["| Code | Message |", "| --- | --- |"])
        for item in blockers:
            if isinstance(item, dict):
                lines.append(f"| {item.get('code')} | {item.get('message')} |")
    else:
        lines.append("No blockers.")
    lines.extend(["", "## Scenario Gaps", "", "| Scenario | Target | Queued | Ready | Missing Collection | Filled Slots | Placeholders |", "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"])
    for item in report.get("scenarioGaps") or []:
        if isinstance(item, dict):
            lines.append(
                f"| {item.get('scenario')} | {item.get('targetCases', '')} | {item.get('queuedCases', '')} | "
                f"{item.get('readyForEval', '')} | {item.get('collectionMissingCases', '')} | {item.get('filled', '')} | {item.get('placeholders', '')} |"
            )
    lines.extend(["", "## Next Actions", ""])
    for action in report.get("nextActions") or []:
        lines.append(f"- {action}")
    lines.append("")
    return "\n".join(lines)


def safe_int(value: Any, default: int | None = 0) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def positive(value: int | None) -> bool:
    return value is not None and value > 0


if __name__ == "__main__":
    raise SystemExit(main())
