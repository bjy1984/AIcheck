"""Prepare new 16+17 Jev cases and compare independent inspector labels.

The old 33-case source file is missing. This produces a new, explicitly named
candidate set from version-bound shadow runs; it never fabricates labels or
approves a confidence threshold. Inputs and outputs contain no OCR text.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import stat
from collections import Counter
from pathlib import Path
from typing import Any

CHOICES = {"passed", "failed", "evidence_insufficient", "not_applicable", "human_review_required"}
LABEL_CHOICES = CHOICES | {"uncertain"}
THRESHOLDS = (0.60, 0.68, 0.70, 0.72, 0.80, 0.90)


def candidates_from_state(state: dict[str, Any]) -> dict[str, Any]:
    """Use only completed, pinned Jev opinions and recorded current decisions."""
    results_by_run: dict[str, dict[str, str]] = {}
    for result in state.get("rule_check_results") or []:
        if not isinstance(result, dict):
            continue
        run_id = str(result.get("reviewRunId") or "")
        current = results_by_run.setdefault(run_id, {})
        for atomic in result.get("atomicCheckResults") or []:
            if isinstance(atomic, dict) and atomic.get("atomicCheckId") and atomic.get("result") in CHOICES:
                current[str(atomic["atomicCheckId"])] = str(atomic["result"])
    candidates = []
    seen = set()
    for run in state.get("review_runs") or []:
        if not isinstance(run, dict):
            continue
        shadow = run.get("jevSecondOpinions") or {}
        run_id = str(run.get("reviewRunId") or run.get("id") or "")
        input_hash = str(run.get("inputHash") or "")
        # R19 compares against a Qwen semantic judgment, not the deterministic
        # rule engine. Keep it out of the 16+17 rule-engine calibration sample.
        if (shadow.get("status") != "completed" or shadow.get("model") != "jev-1.13.0"
                or shadow.get("comparisonSource") not in {None, "rule_engine"}
                or not run_id or not input_hash):
            continue
        for opinion in shadow.get("atomic") or []:
            if not isinstance(opinion, dict):
                continue
            atomic_id = str(opinion.get("atomicCheckId") or "")
            choice, confidence = opinion.get("choice"), opinion.get("confidence")
            current = results_by_run.get(run_id, {}).get(atomic_id)
            key = (run_id, atomic_id)
            if (not atomic_id or key in seen or choice not in CHOICES or current not in CHOICES
                    or type(confidence) not in {int, float} or not math.isfinite(confidence)
                    or not 0 <= confidence <= 1):
                continue
            seen.add(key)
            candidates.append({"caseId": f"{run_id}/{atomic_id}", "reviewRunId": run_id,
                               "projectId": run.get("projectId"), "nodeId": run.get("nodeId"),
                               "atomicCheckId": atomic_id, "inputHash": input_hash,
                               "documentVersionIds": opinion.get("sourceDocumentVersionIds") or [],
                               "currentResult": current, "jevChoice": choice,
                               "confidence": float(confidence),
                               "suggestedSupportPage": opinion.get("suggestedSupportPage"),
                               "comparisonSource": shadow.get("comparisonSource") or "rule_engine"})
    disagreement = sorted((row for row in candidates if row["jevChoice"] != row["currentResult"]),
                          key=lambda row: (-row["confidence"], row["caseId"]))[:16]
    chosen = {row["caseId"] for row in disagreement}
    passed = sorted((row for row in candidates if row["jevChoice"] == "passed"
                     and row["caseId"] not in chosen),
                    key=lambda row: (row["confidence"], row["caseId"]))[:17]
    rows = [{**row, "samplingStratum": "disagreement"} for row in disagreement]
    rows.extend({**row, "samplingStratum": "jev_passed"} for row in passed)
    return {"schemaVersion": "jev-atomic-inspector-candidates-v1",
            "status": "ready_for_inspector" if len(disagreement) == 16 and len(passed) == 17
            else "insufficient_candidate_pool", "availableCount": len(candidates),
            "selectedDisagreementCount": len(disagreement), "selectedJevPassedCount": len(passed),
            "candidates": rows}


def evaluate_labels(candidates: list[dict[str, Any]], labels: list[dict[str, Any]]) -> dict[str, Any]:
    by_id = {row["caseId"]: row for row in candidates}
    if len(by_id) != len(candidates):
        raise ValueError("duplicate_candidate_case")
    seen = set()
    compared = []
    stale = provisional = uncertain = 0
    for label in labels:
        case_id = str(label.get("caseId") or "")
        if case_id in seen or case_id not in by_id:
            raise ValueError("duplicate_or_unknown_label_case")
        seen.add(case_id)
        candidate = by_id[case_id]
        if label.get("inputHash") != candidate["inputHash"]:
            stale += 1
            continue
        if label.get("labelSource") != "inspector" or not str(label.get("annotatedBy") or "").strip():
            provisional += 1
            continue
        answer = label.get("choice")
        if answer not in LABEL_CHOICES:
            raise ValueError("invalid_inspector_label")
        if answer == "uncertain":
            uncertain += 1
            continue
        compared.append({**candidate, "inspectorChoice": answer})
    confusion = Counter((row["inspectorChoice"], row["jevChoice"]) for row in compared)
    false_passes = [row["caseId"] for row in compared
                    if row["jevChoice"] == "passed" and row["inspectorChoice"] != "passed"]
    def score(field: str) -> dict[str, Any]:
        matches = sum(row[field] == row["inspectorChoice"] for row in compared)
        return {"correct": matches, "total": len(compared),
                "accuracy": round(matches / len(compared), 4) if compared else None}
    return {"schemaVersion": "jev-atomic-inspector-evaluation-v1",
            "status": "ready_for_review" if compared else "no_comparable_inspector_labels",
            "candidateCount": len(candidates), "inspectorComparedCount": len(compared),
            "labelsMissing": len(candidates) - len(seen), "staleInputHashCount": stale,
            "provisionalCount": provisional, "inspectorUncertainCount": uncertain,
            "jev": score("jevChoice"), "current": score("currentResult"),
            "falsePassCaseIds": sorted(false_passes),
            "confusion": [{"inspectorChoice": gold, "jevChoice": predicted, "count": count}
                          for (gold, predicted), count in sorted(confusion.items())],
            "thresholdSweep": [{"threshold": threshold,
                                "jevPassedCount": sum(row["jevChoice"] == "passed"
                                                      and row["confidence"] >= threshold for row in compared),
                                "falsePassCount": sum(row["jevChoice"] == "passed"
                                                      and row["confidence"] >= threshold
                                                      and row["inspectorChoice"] != "passed" for row in compared)}
                               for threshold in THRESHOLDS],
            "releaseThresholdApproved": False}


def _private_json(path: Path) -> Any:
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise ValueError("private_evaluation_file_permissions_required")
    return json.loads(path.read_text(encoding="utf-8"))


def _write_private(path: Path, value: Any) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(value, output, ensure_ascii=False, indent=2)
            output.write("\n")
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True, type=Path,
                        help="Private JSON with review_runs and rule_check_results; no OCR")
    parser.add_argument("--labels", type=Path, help="Private independent inspector labels JSON")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        state = _private_json(args.snapshot)
        prepared = candidates_from_state(state)
        report = (evaluate_labels(prepared["candidates"], _private_json(args.labels))
                  if args.labels else prepared)
        _write_private(args.output, report)
    except (OSError, TypeError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps({key: value for key, value in report.items()
                      if key not in {"candidates", "falsePassCaseIds", "confusion", "thresholdSweep"}},
                     ensure_ascii=False, indent=2))
    return 0 if report["status"] in {"ready_for_inspector", "ready_for_review"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
