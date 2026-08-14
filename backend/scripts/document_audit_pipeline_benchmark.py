from __future__ import annotations

import argparse
import json
import random
import statistics
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

PIPELINES = ("qwen_vl_audit_v1", "paddle_nuextract_deepseek_v1")


def normalize(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).upper()
    return "".join(character for character in text if not character.isspace())


def reviewed(case: dict[str, Any]) -> bool:
    gold = case.get("gold") if isinstance(case.get("gold"), dict) else {}
    reviewers = {str(value) for value in gold.get("reviewers") or [] if value}
    return gold.get("approved") is True and len(reviewers) >= 2


def fields(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    raw = payload.get("documentFields") if isinstance(payload.get("documentFields"), dict) else {}
    return {
        str(code): (value.get("value") if isinstance(value, dict) else value)
        for code, value in raw.items()
    }


def finding_signatures(payload: Any) -> Counter[str]:
    output: Counter[str] = Counter()
    if not isinstance(payload, dict):
        return output
    for finding in payload.get("findings") or []:
        if not isinstance(finding, dict):
            continue
        output[
            "|".join(
                [
                    normalize(finding.get("findingType")),
                    normalize(finding.get("severity")),
                    normalize(finding.get("suggestedAction")),
                ]
            )
        ] += 1
    return output


def standard_refs(payload: Any) -> Counter[str]:
    output: Counter[str] = Counter()
    if not isinstance(payload, dict):
        return output
    for finding in payload.get("findings") or []:
        if isinstance(finding, dict):
            output.update(normalize(value) for value in finding.get("standardRefs") or [] if value)
    return output


def match_counts(expected: Counter[str], actual: Counter[str]) -> tuple[int, int, int]:
    true_positive = sum((expected & actual).values())
    return true_positive, sum(actual.values()) - true_positive, sum(expected.values()) - true_positive


def f1(true_positive: int, false_positive: int, false_negative: int) -> float | None:
    denominator = 2 * true_positive + false_positive + false_negative
    return 2 * true_positive / denominator if denominator else None


def score_case(case: dict[str, Any], pipeline: str) -> dict[str, Any]:
    gold = case.get("gold") if isinstance(case.get("gold"), dict) else {}
    prediction = ((case.get("predictions") or {}).get(pipeline)) if isinstance(case.get("predictions"), dict) else None
    prediction = prediction if isinstance(prediction, dict) else {}
    expected_fields = fields({"documentFields": gold.get("fields") or {}})
    actual_fields = fields(prediction)
    correct = sum(normalize(expected) == normalize(actual_fields.get(code)) for code, expected in expected_fields.items())
    expected_findings = finding_signatures({"findings": gold.get("findings") or []})
    actual_findings = finding_signatures(prediction)
    finding_tp, finding_fp, finding_fn = match_counts(expected_findings, actual_findings)
    expected_standards = standard_refs({"findings": gold.get("findings") or []})
    actual_standards = standard_refs(prediction)
    standard_tp, standard_fp, standard_fn = match_counts(expected_standards, actual_standards)
    validation = prediction.get("validation") if isinstance(prediction.get("validation"), dict) else {}
    return {
        "available": bool(prediction),
        "jsonValid": prediction.get("jsonValid") is not False and isinstance(prediction, dict),
        "fieldCorrect": correct,
        "fieldTotal": len(expected_fields),
        "fieldAccuracy": correct / len(expected_fields) if expected_fields else None,
        "findingTp": finding_tp,
        "findingFp": finding_fp,
        "findingFn": finding_fn,
        "standardTp": standard_tp,
        "standardFp": standard_fp,
        "standardFn": standard_fn,
        "invalidReferenceCount": int(validation.get("invalidReferenceCount") or 0),
        "ungroundedSubstantiveFindingCount": int(validation.get("ungroundedSubstantiveFindingCount") or 0),
        "formalEvidenceReady": bool(prediction.get("formalEvidenceReady")),
        "latencyMs": prediction.get("endToEndTimeMs") or prediction.get("totalTimeMs"),
    }


def aggregate(scores: list[dict[str, Any]]) -> dict[str, Any]:
    available = [item for item in scores if item["available"]]
    field_total = sum(item["fieldTotal"] for item in available)
    field_correct = sum(item["fieldCorrect"] for item in available)
    finding_counts = [sum(item[key] for item in available) for key in ("findingTp", "findingFp", "findingFn")]
    standard_counts = [sum(item[key] for item in available) for key in ("standardTp", "standardFp", "standardFn")]
    latencies = sorted(float(item["latencyMs"]) for item in available if item.get("latencyMs") is not None)
    p95 = latencies[min(len(latencies) - 1, max(0, int(len(latencies) * 0.95) - 1))] if latencies else None
    return {
        "availableCases": len(available),
        "jsonSuccessRate": sum(item["jsonValid"] for item in available) / len(available) if available else None,
        "fieldExactMatch": field_correct / field_total if field_total else None,
        "findingF1": f1(*finding_counts),
        "standardReferenceF1": f1(*standard_counts),
        "invalidReferenceCount": sum(item["invalidReferenceCount"] for item in available),
        "ungroundedSubstantiveFindingCount": sum(
            item["ungroundedSubstantiveFindingCount"] for item in available
        ),
        "formalEvidenceReadyCount": sum(item["formalEvidenceReady"] for item in available),
        "p95LatencyMs": p95,
    }


def paired_bootstrap(left: list[dict[str, Any]], right: list[dict[str, Any]], iterations: int = 2000) -> dict[str, Any]:
    pairs = [
        (a["fieldAccuracy"], b["fieldAccuracy"])
        for a, b in zip(left, right, strict=True)
        if a["fieldAccuracy"] is not None and b["fieldAccuracy"] is not None
    ]
    if not pairs:
        return {"pairedCases": 0, "delta": None, "ci95": None}
    observed = statistics.mean(right_value - left_value for left_value, right_value in pairs)
    randomizer = random.Random(20260711)
    samples = []
    for _ in range(iterations):
        sample = [pairs[randomizer.randrange(len(pairs))] for _ in pairs]
        samples.append(statistics.mean(right_value - left_value for left_value, right_value in sample))
    samples.sort()
    return {
        "pairedCases": len(pairs),
        "delta": observed,
        "ci95": [samples[int(iterations * 0.025)], samples[min(iterations - 1, int(iterations * 0.975))]],
    }


def build_report(manifest: dict[str, Any]) -> dict[str, Any]:
    cases = [item for item in manifest.get("cases") or [] if isinstance(item, dict)]
    reviewed_cases = [item for item in cases if reviewed(item)]
    case_scores = {pipeline: [score_case(case, pipeline) for case in reviewed_cases] for pipeline in PIPELINES}
    metrics = {pipeline: aggregate(scores) for pipeline, scores in case_scores.items()}
    paired = paired_bootstrap(case_scores[PIPELINES[0]], case_scores[PIPELINES[1]])
    baseline = metrics[PIPELINES[0]]
    challenger = metrics[PIPELINES[1]]
    blockers = []
    if len(reviewed_cases) < 30:
        blockers.append("DOUBLE_REVIEWED_GOLD_BELOW_30")
    if len(reviewed_cases) < 150:
        blockers.append("PILOT_CASES_BELOW_150")
    if any(metrics[pipeline]["availableCases"] < len(reviewed_cases) for pipeline in PIPELINES):
        blockers.append("PIPELINE_PREDICTIONS_INCOMPLETE")
    gates = {
        "challengerFieldGainAtLeast2Points": bool(
            challenger["fieldExactMatch"] is not None
            and baseline["fieldExactMatch"] is not None
            and challenger["fieldExactMatch"] - baseline["fieldExactMatch"] >= 0.02
        ),
        "pairedCiLowerAboveZero": bool(paired.get("ci95") and paired["ci95"][0] > 0),
        "challengerFindingF1NonRegression": bool(
            challenger["findingF1"] is not None
            and baseline["findingF1"] is not None
            and challenger["findingF1"] >= baseline["findingF1"]
        ),
        "challengerStandardReferenceF1NonRegression": bool(
            challenger["standardReferenceF1"] is not None
            and baseline["standardReferenceF1"] is not None
            and challenger["standardReferenceF1"] >= baseline["standardReferenceF1"]
        ),
        "invalidReferencesZero": challenger["invalidReferenceCount"] == 0,
        "ungroundedSubstantiveFindingsZero": challenger["ungroundedSubstantiveFindingCount"] == 0,
        "formalEvidenceReadyZero": all(metrics[pipeline]["formalEvidenceReadyCount"] == 0 for pipeline in PIPELINES),
        "bothP95AtMost180s": all(
            metrics[pipeline]["p95LatencyMs"] is not None and metrics[pipeline]["p95LatencyMs"] <= 180_000
            for pipeline in PIPELINES
        ),
    }
    blockers.extend(f"PILOT_GATE_FAILED:{name}" for name, passed in gates.items() if not passed)
    return {
        "schemaVersion": "DocumentAuditPipelineBenchmarkReport@1",
        "status": "pilot_passed" if not blockers else "blocked",
        "accuracyClaimed": bool(reviewed_cases),
        "reviewedGoldCases": len(reviewed_cases),
        "totalManifestCases": len(cases),
        "pipelines": metrics,
        "pairedChallengerVsQwenVl": paired,
        "pilotGates": gates,
        "blockers": blockers,
        "notes": [
            "Only cases approved by two distinct reviewers contribute to accuracy metrics.",
            "Agreement without gold labels is not accuracy and cannot select a production pipeline.",
            "Both pipelines remain advisory-only regardless of benchmark outcome.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare Qwen VL audit with PaddleOCR + NuExtract + DeepSeek.")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = build_report(json.loads(args.manifest.read_text(encoding="utf-8")))
    raw = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(raw + "\n", encoding="utf-8")
    print(raw)
    return 0 if report["status"] == "pilot_passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
