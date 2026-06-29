from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.ocr_service.evaluation import compact_evaluation_report, evaluate_cases
from apps.ocr_service.service import ocr_service


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate local OCR results against a JSON release evaluation set.")
    parser.add_argument("eval_set", help="JSON file with a top-level cases array, or a raw array of cases.")
    parser.add_argument("--output", help="Optional JSON report path.")
    parser.add_argument("--summary-output", help="Optional compact JSON summary report path for CI/FDE gates.")
    parser.add_argument("--markdown-output", help="Optional Markdown evidence report path.")
    parser.add_argument(
        "--run-ocr",
        action="store_true",
        help="Run local OCR for cases with source paths. Without this flag, cases must embed result or resultPath.",
    )
    parser.add_argument("--min-average-score", type=float, default=0.9)
    args = parser.parse_args()

    eval_set_path = Path(args.eval_set).resolve()
    payload = json.loads(eval_set_path.read_text(encoding="utf-8"))
    cases = payload.get("cases") if isinstance(payload, dict) else payload
    thresholds = payload.get("thresholds") if isinstance(payload, dict) and isinstance(payload.get("thresholds"), dict) else None
    if not isinstance(cases, list):
        print("OCR eval set must be a JSON array or an object with cases[].", file=sys.stderr)
        return 2
    cases = normalize_case_paths(cases, base_dir=eval_set_path.parent, resolve_sources=args.run_ocr)

    report = evaluate_cases(cases, parse_runner=parse_case_with_ocr if args.run_ocr else None, thresholds=thresholds)
    if args.output:
        write_text_file(Path(args.output), json.dumps(report, ensure_ascii=False, indent=2))
    if args.summary_output:
        write_text_file(
            Path(args.summary_output),
            json.dumps(compact_evaluation_report(report), ensure_ascii=False, indent=2),
        )
    if args.markdown_output:
        write_text_file(
            Path(args.markdown_output),
            markdown_report(report, eval_set_name=eval_set_name(payload, args.eval_set)),
        )
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))

    average_score = float(report.get("summary", {}).get("averageScore") or 0)
    if not report["ok"] or average_score < args.min_average_score:
        print(
            f"OCR evaluation failed: ok={report['ok']} averageScore={average_score:.4f} "
            f"minAverageScore={args.min_average_score:.4f}",
            file=sys.stderr,
        )
        return 1
    return 0


def eval_set_name(payload: Any, fallback: str) -> str:
    if isinstance(payload, dict) and payload.get("name"):
        return str(payload["name"])
    return Path(fallback).stem


def normalize_case_paths(
    cases: list[Any],
    *,
    base_dir: Path,
    resolve_sources: bool = False,
) -> list[Any]:
    return [
        normalize_case_path(case, base_dir=base_dir, resolve_sources=resolve_sources)
        if isinstance(case, dict)
        else case
        for case in cases
    ]


def normalize_case_path(case: dict[str, Any], *, base_dir: Path, resolve_sources: bool) -> dict[str, Any]:
    normalized = dict(case)
    if normalized.get("resultPath"):
        normalized["resultPath"] = resolve_local_reference(normalized["resultPath"], base_dir)
    if resolve_sources and normalized.get("source"):
        normalized["source"] = resolve_local_reference(normalized["source"], base_dir)
    return normalized


def resolve_local_reference(value: Any, base_dir: Path) -> str:
    raw = str(value)
    if not raw or "://" in raw:
        return raw
    path = Path(raw).expanduser()
    if path.is_absolute():
        return str(path)
    return str((base_dir / path).resolve())


def write_text_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def markdown_report(report: dict[str, Any], *, eval_set_name: str = "ocr_eval_set") -> str:
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    lines = [
        f"# OCR Evaluation Report: {eval_set_name}",
        "",
        f"- Status: {'PASS' if report.get('ok') else 'FAIL'}",
        f"- Cases: {summary.get('cases', 0)}",
        f"- Passed: {summary.get('passed', 0)}",
        f"- Failed: {summary.get('failed', 0)}",
        f"- Average score: {format_score(summary.get('averageScore'))}",
        "",
        "## Scenario Scores",
        "",
        "| Scenario | Cases | Passed | Failed | Average Score |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    scenarios = report.get("scenarios") if isinstance(report.get("scenarios"), dict) else {}
    for name, scenario in sorted(scenarios.items()):
        lines.append(
            f"| {name} | {scenario.get('cases', 0)} | {scenario.get('passed', 0)} | "
            f"{scenario.get('failed', 0)} | {format_score(scenario.get('averageScore'))} |"
        )
    if not scenarios:
        lines.append("| default | 0 | 0 | 0 | n/a |")

    lines.extend(["", "## Metrics", "", "| Metric | Score |", "| --- | ---: |"])
    metrics = report.get("metrics") if isinstance(report.get("metrics"), dict) else {}
    for metric, value in sorted(metrics.items()):
        lines.append(f"| {metric} | {format_score(value)} |")

    finding_counts = report.get("findingCounts") if isinstance(report.get("findingCounts"), dict) else {}
    lines.extend(["", "## Finding Summary", ""])
    if finding_counts:
        lines.extend(["| Finding | Count |", "| --- | ---: |"])
        for code, count in sorted(finding_counts.items(), key=lambda item: (-int(item[1] or 0), item[0])):
            lines.append(f"| {code} | {count} |")
    else:
        lines.append("No findings.")

    threshold_failures = report.get("thresholdFailures") or []
    scenario_threshold_failures = [
        failure
        for scenario in scenarios.values()
        for failure in (scenario.get("thresholdFailures") or [])
        if isinstance(failure, dict)
    ]
    lines.extend(["", "## Threshold Failures", ""])
    if threshold_failures or scenario_threshold_failures:
        lines.extend(["| Scope | Metric | Actual | Minimum |", "| --- | --- | ---: | ---: |"])
        for failure in [*threshold_failures, *scenario_threshold_failures]:
            lines.append(
                f"| {failure.get('scope')} | {failure.get('metric')} | "
                f"{format_score(failure.get('actual'))} | {format_score(failure.get('minimum'))} |"
            )
    else:
        lines.append("No threshold failures.")

    failed_cases = [case for case in report.get("cases") or [] if isinstance(case, dict) and not case.get("passed")]
    lines.extend(["", "## Failed Cases", ""])
    if failed_cases:
        for case in failed_cases:
            lines.extend(case_markdown(case))
    else:
        lines.append("No failed cases.")
    lines.append("")
    return "\n".join(lines)


def case_markdown(case: dict[str, Any]) -> list[str]:
    lines = [
        f"### {case.get('caseId')}",
        "",
        f"- Scenario: {case.get('scenario')}",
        f"- Score: {format_score(case.get('score'))}",
        f"- Quality status: {case.get('qualityStatus')}",
    ]
    findings = case.get("findings") or []
    if findings:
        lines.append("- Findings: " + ", ".join(str(item.get("code") if isinstance(item, dict) else item) for item in findings))
    details = case.get("details") if isinstance(case.get("details"), dict) else {}
    for section in ("fields", "tables", "seals"):
        items = [item for item in details.get(section) or [] if isinstance(item, dict) and item.get("status") != "matched"]
        if not items:
            continue
        lines.extend(["", f"#### {section.title()}"])
        for item in items:
            label = item.get("fieldCode") or item.get("expectedBusinessSchema") or item.get("expectedSealType") or item.get("expectedNameContains")
            lines.append(
                f"- {label}: {item.get('status')}; bestIoU={format_score(item.get('bestIou'))}; "
                f"candidates={len(item.get('candidates') or [])}"
            )
    quality = details.get("quality") if isinstance(details.get("quality"), dict) else {}
    if (
        quality.get("status") and quality.get("status") != "matched"
    ) or quality.get("evidenceCompletenessStatus") == "range_mismatch":
        lines.extend(["", "#### Quality"])
        lines.append(
            f"- expected={quality.get('expectedStatus')} actual={quality.get('actualStatus')} "
            f"missingReasons={','.join(quality.get('missingReasons') or [])}"
        )
        if quality.get("evidenceCompletenessStatus") == "range_mismatch":
            lines.append(
                f"- evidenceCompleteness actual={format_score(quality.get('actualEvidenceCompleteness'))} "
                f"min={format_score(quality.get('expectedMinEvidenceCompleteness'))} "
                f"max={format_score(quality.get('expectedMaxEvidenceCompleteness'))}"
            )
    lines.append("")
    return lines


def format_score(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{float(value):.4f}"
    except (TypeError, ValueError):
        return str(value)


def parse_case_with_ocr(case: dict[str, Any]) -> dict[str, Any]:
    source = str(case.get("source") or "")
    if not source:
        raise ValueError(f"OCR eval case {case.get('caseId') or '<unknown>'} has no source.")
    source_path = Path(source)
    return ocr_service.parse_document(
        source,
        file_name=str(case.get("fileName") or source_path.name),
        profile_id=case.get("profileId"),
        document_type=case.get("documentType"),
        document_version_id=case.get("documentVersionId"),
        business_pack_id=case.get("businessPackId"),
        options=case.get("options") if isinstance(case.get("options"), dict) else {},
    )


if __name__ == "__main__":
    raise SystemExit(main())
