from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.ocr_service.evaluation import evaluate_cases, merge_thresholds, ocr_100_thresholds
from apps.ocr_service.readiness import build_ocr_100_scorecard
from apps.ocr_service.service import ocr_service
from scripts.ocr_eval_set import normalize_case_paths, parse_case_with_ocr, write_text_file


def main() -> int:
    parser = argparse.ArgumentParser(description="Build an objective AIcheck OCR 100 readiness scorecard.")
    parser.add_argument("--eval-set", required=True, help="Evaluation set JSON with cases[].")
    parser.add_argument("--eval-report", help="Optional precomputed full evaluation report JSON.")
    parser.add_argument("--runtime-doctor-json", help="Optional runtime doctor JSON. Defaults to live ocr_service doctor.")
    parser.add_argument("--sample-summary", action="append", default=[], help="Sample probe summary JSON. Repeatable.")
    parser.add_argument("--sample-summary-dir", action="append", default=[], help="Directory containing sample probe summary JSON files. Repeatable.")
    parser.add_argument("--auto-discover-runtime", action="store_true", help="Apply runtime-doctor recommended local OCR Python and model paths before live doctor.")
    parser.add_argument("--run-ocr", action="store_true", help="Run OCR for eval cases with source paths.")
    parser.add_argument("--output", help="Optional scorecard JSON output path.")
    args = parser.parse_args()

    applied_runtime = apply_auto_discovered_runtime() if args.auto_discover_runtime else {}
    eval_set_path = Path(args.eval_set).resolve()
    eval_payload = load_json(eval_set_path)
    evaluation_report = load_json(Path(args.eval_report)) if args.eval_report else evaluate_eval_set(
        eval_payload,
        eval_set_path=eval_set_path,
        run_ocr=bool(args.run_ocr),
    )
    runtime_doctor = load_json(Path(args.runtime_doctor_json)) if args.runtime_doctor_json else ocr_service.runtime_doctor_payload()
    if applied_runtime:
        runtime_doctor["appliedAutoDiscoveredRuntime"] = applied_runtime
    sample_summaries = load_sample_summaries(args.sample_summary, args.sample_summary_dir)
    scorecard = build_ocr_100_scorecard(
        evaluation_report=evaluation_report,
        runtime_doctor=runtime_doctor,
        sample_summaries=sample_summaries,
    )
    if args.output:
        write_text_file(Path(args.output), json.dumps(scorecard, ensure_ascii=False, indent=2))
    print(json.dumps(scorecard, ensure_ascii=False, indent=2))
    return 0 if scorecard.get("ok") else 1


def evaluate_eval_set(payload: Any, *, eval_set_path: Path, run_ocr: bool) -> dict[str, Any]:
    cases = payload.get("cases") if isinstance(payload, dict) else payload
    if not isinstance(cases, list):
        raise ValueError("OCR scorecard eval set must be a JSON array or an object with cases[].")
    thresholds = payload.get("thresholds") if isinstance(payload, dict) and isinstance(payload.get("thresholds"), dict) else {}
    thresholds = merge_thresholds(thresholds, ocr_100_thresholds())
    normalized_cases = normalize_case_paths(cases, base_dir=eval_set_path.parent, resolve_sources=run_ocr)
    return evaluate_cases(
        normalized_cases,
        parse_runner=parse_case_with_ocr if run_ocr else None,
        thresholds=thresholds,
    )


def apply_auto_discovered_runtime() -> dict[str, str]:
    from apps.ocr_service.runtime_doctor import discover_runtime_candidates, recommended_env

    recommended = recommended_env(discover_runtime_candidates())
    applied: dict[str, str] = {}
    for key, value in recommended.items():
        if os.getenv(key) or not value:
            continue
        os.environ[key] = value
        applied[key] = value
    return applied


def load_sample_summaries(paths: list[str], directories: list[str]) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for path in paths:
        payloads.extend(expand_sample_summary(load_json(Path(path))))
    for directory in directories:
        for path in sorted(Path(directory).glob("*.json")):
            payloads.extend(expand_sample_summary(load_json(path)))
    return payloads


def expand_sample_summary(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict) and isinstance(payload.get("items"), list):
        return [item for item in payload["items"] if isinstance(item, dict)]
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return [payload] if isinstance(payload, dict) else []


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
