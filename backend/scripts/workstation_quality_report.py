"""Compare three workstation variants on paired, reviewed frozen cases; no model calls."""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any

GROUPS = ("baseline", "workstation", "full")
RESULTS = {"passed", "failed", "evidence_insufficient", "not_applicable"}


def rate(numerator: int, denominator: int) -> dict[str, Any]:
    return {
        "count": numerator,
        "total": denominator,
        "rate": numerator / denominator if denominator else None,
    }


def metrics(cases: list[dict[str, Any]], group: str) -> dict[str, Any]:
    pairs = [(case["gold"]["result"], case["predictions"][group]["result"]) for case in cases]
    failures = [actual for gold, actual in pairs if gold == "failed"]
    compliant = [actual for gold, actual in pairs if gold == "passed"]
    decidable = [actual for gold, actual in pairs if gold in {"passed", "failed"}]
    insufficient = [actual for gold, actual in pairs if gold == "evidence_insufficient"]
    return {
        "exactAgreement": rate(sum(gold == actual for gold, actual in pairs), len(pairs)),
        "unsafePassOnNoncompliance": rate(failures.count("passed"), len(failures)),
        "noncomplianceNotDetected": rate(
            sum(actual != "failed" for actual in failures), len(failures)
        ),
        "falseNoncompliance": rate(compliant.count("failed"), len(compliant)),
        "unnecessaryInsufficiency": rate(decidable.count("evidence_insufficient"), len(decidable)),
        "unsupportedPass": rate(insufficient.count("passed"), len(insufficient)),
        "operationalMeasures": {
            field: {
                "measuredCases": len(
                    values := [
                        case["predictions"][group][field]
                        for case in cases
                        if field in case["predictions"][group]
                    ]
                ),
                "total": sum(values) if values else None,
                "mean": sum(values) / len(values) if values else None,
            }
            for field in ("humanSeconds", "latencySeconds", "costCny")
        },
    }


def paired_measure(cases: list[dict[str, Any]], group: str, field: str) -> dict[str, Any]:
    pairs = [
        (case["predictions"]["baseline"][field], case["predictions"][group][field])
        for case in cases
        if field in case["predictions"]["baseline"] and field in case["predictions"][group]
    ]
    old_total = sum(old for old, _ in pairs)
    new_total = sum(new for _, new in pairs)
    return {
        "pairedCases": len(pairs),
        "meanDelta": (new_total - old_total) / len(pairs) if pairs else None,
        "relativeReduction": (old_total - new_total) / old_total if old_total else None,
    }


def comparison(cases: list[dict[str, Any]], group: str) -> dict[str, Any]:
    baseline = [
        case["predictions"]["baseline"]["result"] == case["gold"]["result"] for case in cases
    ]
    candidate = [case["predictions"][group]["result"] == case["gold"]["result"] for case in cases]
    improved = sum(not old and new for old, new in zip(baseline, candidate, strict=True))
    regressed = sum(old and not new for old, new in zip(baseline, candidate, strict=True))
    old_errors = len(cases) - sum(baseline)
    return {
        "pairedCases": len(cases),
        "improved": improved,
        "regressed": regressed,
        "agreementDelta": (improved - regressed) / len(cases) if cases else None,
        "relativeErrorReduction": (improved - regressed) / old_errors if old_errors else None,
        "pairedOperationalMeasures": {
            field: paired_measure(cases, group, field)
            for field in ("humanSeconds", "latencySeconds", "costCny")
        },
    }


def build_report(manifest: dict[str, Any]) -> dict[str, Any]:
    if manifest.get("schemaVersion") != "workstation-quality-cases-v1":
        raise ValueError("quality_schema_invalid")
    cases = manifest.get("cases")
    if not isinstance(cases, list):
        raise TypeError("quality_cases_must_be_list")
    eligible, excluded, seen, inputs = [], [], set(), set()
    for case in cases:
        if (
            not isinstance(case, dict)
            or not isinstance(case.get("caseId"), str)
            or not case["caseId"].strip()
        ):
            raise ValueError("quality_case_identity_missing")
        identity = case["caseId"]
        if identity in seen:
            raise ValueError("quality_duplicate_case")
        seen.add(identity)
        rule, digest = case.get("ruleId"), case.get("inputSha256")
        if not isinstance(rule, str) or not re.fullmatch(r"R(?:0[1-9]|[1-6][0-9])", rule):
            raise ValueError("quality_rule_invalid")
        if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise ValueError("quality_input_hash_invalid")
        key = rule, digest
        if key in inputs:
            raise ValueError("quality_duplicate_frozen_case")
        inputs.add(key)
        gold = case.get("gold") or {}
        if not isinstance(gold, dict):
            raise TypeError("quality_gold_must_be_object")
        reviewers = gold.get("reviewers") or []
        approved = (
            gold.get("approved") is True
            and gold.get("result") in RESULTS
            and isinstance(reviewers, list)
            and len({name.strip() for name in reviewers if isinstance(name, str) and name.strip()})
            >= 2
        )
        reason = None if approved else "gold_not_double_reviewed"
        predictions = case.get("predictions") or {}
        if not isinstance(predictions, dict):
            raise TypeError("quality_predictions_must_be_object")
        settings = []
        for group in GROUPS:
            prediction = predictions.get(group)
            if not isinstance(prediction, dict):
                reason = reason or "three_group_predictions_incomplete"
                continue
            for field in ("humanSeconds", "latencySeconds", "costCny"):
                if field in prediction and (
                    type(prediction[field]) not in (int, float)
                    or not math.isfinite(prediction[field])
                    or prediction[field] < 0
                ):
                    raise ValueError("quality_operational_measure_invalid")
            if prediction.get("result") not in RESULTS | {
                "execution_error",
                "human_review_required",
            }:
                raise ValueError("quality_prediction_result_invalid")
            if prediction.get("inputSha256") != digest:
                reason = reason or "prediction_input_mismatch"
            if not all(
                isinstance(prediction.get(field), str) and prediction[field].strip()
                for field in ("model", "modelSettingsSha256", "implementationVersion")
            ):
                reason = reason or "prediction_configuration_missing"
            else:
                settings.append((prediction["model"], prediction["modelSettingsSha256"]))
        if len(set(settings)) > 1:
            reason = reason or "model_or_settings_mismatch"
        if reason:
            excluded.append({"caseId": identity, "reason": reason})
        else:
            eligible.append(case)
    return {
        "schemaVersion": "workstation-quality-report-v1",
        "totalCases": len(cases),
        "pairedReviewedCases": len(eligible),
        "excludedCases": excluded,
        "groups": {group: metrics(eligible, group) for group in GROUPS},
        "comparisonsToBaseline": {group: comparison(eligible, group) for group in GROUPS[1:]},
        "byRule": {
            rule: {
                group: metrics([case for case in eligible if case["ruleId"] == rule], group)
                for group in GROUPS
            }
            for rule in sorted({case["ruleId"] for case in eligible})
        },
        "publicationApproved": False,
        "limitations": [
            "Reviewer declarations and input hashes require independent provenance verification.",
            "Paired metrics exclude incomplete or unmatched cases; inspect exclusion counts.",
            "Execution errors and human review remain in denominators, never silently dropped.",
            "No statistical significance, population accuracy, citation support or causal benefit is established.",
            "Operational means with different measured-case coverage are not paired savings estimates.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build_report(json.loads(args.manifest.read_bytes()))
    with args.output.open("x") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
    print(
        json.dumps(
            {
                "pairedReviewedCases": report["pairedReviewedCases"],
                "excludedCases": len(report["excludedCases"]),
            }
        )
    )
    return 0 if report["pairedReviewedCases"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
