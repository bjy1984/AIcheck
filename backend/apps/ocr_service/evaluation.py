from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

ParseRunner = Callable[[dict[str, Any]], dict[str, Any]]


DEFAULT_WEIGHTS = {
    "fieldRecall": 0.3,
    "fieldValueAccuracy": 0.2,
    "fieldEvidenceRecall": 0.1,
    "fieldBboxHitRate": 0.1,
    "tableRecall": 0.18,
    "tableEvidenceRecall": 0.08,
    "tableBboxHitRate": 0.08,
    "sealRecall": 0.14,
    "sealEvidenceRecall": 0.08,
    "sealBboxHitRate": 0.08,
    "qualityStatusMatch": 0.1,
    "qualityReasonRecall": 0.08,
    "qualityEvidenceCompletenessMatch": 0.06,
}

OCR_100_REQUIRED_SCENARIOS = [
    "piping_table_profile",
    "quality_certificate_profile",
    "ndt_rt_profile",
    "ndt_ut_profile",
    "construction_record_profile",
    "welding_record_profile",
    "qualification_certificate_profile",
    "seal_text_profile",
    "fragment_seal_profile",
    "evidence_profile",
    "quality_gate_profile",
]


def ocr_100_thresholds() -> dict[str, Any]:
    return {
        "minCases": 100,
        "requiredScenarios": OCR_100_REQUIRED_SCENARIOS,
        "averageScore": 0.96,
        "metrics": {
            "fieldRecall": 0.95,
            "fieldValueAccuracy": 0.95,
            "fieldEvidenceRecall": 0.95,
            "fieldBboxHitRate": 0.90,
            "tableRecall": 0.95,
            "tableEvidenceRecall": 0.95,
            "tableBboxHitRate": 0.90,
            "sealRecall": 0.95,
            "sealEvidenceRecall": 0.95,
            "sealBboxHitRate": 0.90,
            "qualityStatusMatch": 0.95,
            "qualityReasonRecall": 0.95,
            "qualityEvidenceCompletenessMatch": 0.95,
        },
        "scenarios": {
            scenario: {"averageScore": 0.94, "minCases": 1}
            for scenario in OCR_100_REQUIRED_SCENARIOS
        },
    }


def merge_thresholds(base: dict[str, Any] | None, overlay: dict[str, Any] | None) -> dict[str, Any]:
    merged = {**(base or {})}
    overlay = overlay or {}
    for key, value in overlay.items():
        if key == "metrics" and isinstance(value, dict):
            merged[key] = merge_numeric_threshold_maps(merged.get(key), value)
        elif key == "scenarios" and isinstance(value, dict):
            merged[key] = merge_scenario_thresholds(merged.get(key), value)
        elif key == "requiredScenarios":
            existing = [str(item) for item in merged.get(key) or []]
            for item in value or []:
                if str(item) not in existing:
                    existing.append(str(item))
            merged[key] = existing
        elif isinstance(value, (int, float)) and isinstance(merged.get(key), (int, float)):
            merged[key] = max(float(merged[key]), float(value))
        else:
            merged[key] = value
    return merged


def merge_numeric_threshold_maps(base: Any, overlay: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base) if isinstance(base, dict) else {}
    for key, value in overlay.items():
        if isinstance(value, (int, float)) and isinstance(merged.get(key), (int, float)):
            merged[key] = max(float(merged[key]), float(value))
        else:
            merged[key] = value
    return merged


def merge_scenario_thresholds(base: Any, overlay: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base) if isinstance(base, dict) else {}
    for scenario, thresholds in overlay.items():
        if isinstance(thresholds, dict):
            merged[str(scenario)] = merge_thresholds(
                merged.get(str(scenario)) if isinstance(merged.get(str(scenario)), dict) else {},
                thresholds,
            )
        else:
            merged[str(scenario)] = thresholds
    return merged


def evaluate_cases(
    cases: list[dict[str, Any]],
    *,
    parse_runner: ParseRunner | None = None,
    thresholds: dict[str, Any] | None = None,
) -> dict[str, Any]:
    case_reports = [evaluate_case(case, parse_runner=parse_runner) for case in cases]
    aggregate_metrics = aggregate_case_metrics(case_reports)
    scenario_reports = aggregate_scenarios(case_reports, thresholds=thresholds)
    finding_counts = aggregate_finding_counts(case_reports)
    threshold_failures = threshold_failures_for_scope(
        "overall",
        {
            "averageScore": round(average([item["score"] for item in case_reports]), 4),
            "cases": len(case_reports),
        },
        aggregate_metrics,
        thresholds or {},
    )
    threshold_failures.extend(required_scenario_failures(thresholds or {}, scenario_reports))
    return {
        "ok": all(item["passed"] for item in case_reports)
        and not threshold_failures
        and all(item["ok"] for item in scenario_reports.values()),
        "summary": {
            "cases": len(case_reports),
            "passed": len([item for item in case_reports if item["passed"]]),
            "failed": len([item for item in case_reports if not item["passed"]]),
            "averageScore": round(average([item["score"] for item in case_reports]), 4),
            "scenarios": {
                name: {
                    "cases": item["cases"],
                    "passed": item["passed"],
                    "failed": item["failed"],
                    "averageScore": item["averageScore"],
                }
                for name, item in scenario_reports.items()
            },
        },
        "metrics": aggregate_metrics,
        "findingCounts": finding_counts,
        "thresholdFailures": threshold_failures,
        "scenarios": scenario_reports,
        "cases": case_reports,
    }


def evaluate_case(case: dict[str, Any], *, parse_runner: ParseRunner | None = None) -> dict[str, Any]:
    result = parse_result_for_case(case, parse_runner=parse_runner)
    expected = expected_block(case)
    metrics: dict[str, float | None] = {
        "fieldRecall": field_recall(result, expected),
        "fieldValueAccuracy": field_value_accuracy(result, expected),
        "fieldEvidenceRecall": field_evidence_recall(result, expected),
        "fieldBboxHitRate": field_bbox_hit_rate(result, expected),
        "tableRecall": table_recall(result, expected),
        "tableEvidenceRecall": table_evidence_recall(result, expected),
        "tableBboxHitRate": table_bbox_hit_rate(result, expected),
        "sealRecall": seal_recall(result, expected),
        "sealEvidenceRecall": seal_evidence_recall(result, expected),
        "sealBboxHitRate": seal_bbox_hit_rate(result, expected),
        "qualityStatusMatch": quality_status_match(result, expected),
        "qualityReasonRecall": quality_reason_recall(result, expected),
        "qualityEvidenceCompletenessMatch": quality_evidence_completeness_match(result, expected),
    }
    score = weighted_score(metrics, weights=case.get("weights") if isinstance(case.get("weights"), dict) else None)
    min_score = float(case.get("minScore") or expected.get("minScore") or 0.9)
    findings = build_findings(metrics, result, expected, score, min_score)
    details = build_case_details(result, expected)
    return {
        "caseId": str(case.get("caseId") or case.get("id") or case.get("source") or "case"),
        "scenario": scenario_for_case(case, result),
        "profileId": case.get("profileId") or result.get("profileId"),
        "documentType": case.get("documentType") or result.get("documentType"),
        "status": result.get("status"),
        "score": score,
        "minScore": min_score,
        "passed": score >= min_score and not findings,
        "metrics": metrics,
        "details": details,
        "findings": findings,
        "parseResultId": result.get("parseResultId"),
        "qualityStatus": (result.get("quality") or {}).get("status") if isinstance(result.get("quality"), dict) else None,
        "bootstrapGenerated": bool(case.get("bootstrapGenerated")),
        "fixtureDerived": bool(case.get("fixtureDerived")),
        "collectionStatus": case.get("collectionStatus"),
        "sourceCaseId": case.get("sourceCaseId"),
    }


def parse_result_for_case(case: dict[str, Any], *, parse_runner: ParseRunner | None) -> dict[str, Any]:
    inline_result = case.get("result")
    if isinstance(inline_result, dict):
        return inline_result
    result_path = case.get("resultPath")
    if result_path:
        return load_json_file(Path(str(result_path)))
    if parse_runner is not None and case.get("source"):
        return parse_runner(case)
    raise ValueError(f"OCR evaluation case {case.get('caseId') or case.get('id') or '<unknown>'} has no result/resultPath/source.")


def expected_block(case: dict[str, Any]) -> dict[str, Any]:
    expected = case.get("expected") if isinstance(case.get("expected"), dict) else {}
    return {
        **expected,
        "fields": expected.get("fields") or case.get("expectedFields") or [],
        "tables": expected.get("tables") or case.get("expectedTables") or [],
        "seals": expected.get("seals") or case.get("expectedSeals") or [],
        "qualityStatus": expected.get("qualityStatus", case.get("expectedQualityStatus")),
        "qualityReasons": expected.get("qualityReasons") or case.get("expectedQualityReasons") or [],
        "minEvidenceCompleteness": expected.get("minEvidenceCompleteness", case.get("expectedMinEvidenceCompleteness")),
        "maxEvidenceCompleteness": expected.get("maxEvidenceCompleteness", case.get("expectedMaxEvidenceCompleteness")),
    }


def field_recall(result: dict[str, Any], expected: dict[str, Any]) -> float | None:
    expected_fields = [item for item in expected.get("fields") or [] if isinstance(item, dict)]
    if not expected_fields:
        return None
    actual = actual_fields_by_code(result)
    matched = [field for field in expected_fields if field_code(field) in actual]
    return len(matched) / len(expected_fields)


def field_value_accuracy(result: dict[str, Any], expected: dict[str, Any]) -> float | None:
    expected_fields = [
        item for item in expected.get("fields") or [] if isinstance(item, dict) and item.get("value") is not None
    ]
    if not expected_fields:
        return None
    actual = actual_fields_by_code(result)
    matches = []
    for field in expected_fields:
        candidates = actual.get(field_code(field), [])
        expected_value = normalize_value(field.get("value"))
        if not expected_value:
            continue
        matches.append(any(field_value_matches(candidate.get("fieldValue"), expected_value, field) for candidate in candidates))
    return len([item for item in matches if item]) / len(expected_fields) if expected_fields else None


def field_evidence_recall(result: dict[str, Any], expected: dict[str, Any]) -> float | None:
    expected_fields = [item for item in expected.get("fields") or [] if isinstance(item, dict)]
    if not expected_fields:
        return None
    actual = actual_fields_by_code(result)
    evidence_matches = []
    for field in expected_fields:
        candidates = actual.get(field_code(field), [])
        evidence_matches.append(any(candidate.get("bbox") or candidate.get("polygon") for candidate in candidates))
    return len([item for item in evidence_matches if item]) / len(expected_fields)


def field_bbox_hit_rate(result: dict[str, Any], expected: dict[str, Any]) -> float | None:
    expected_fields = [
        item
        for item in expected.get("fields") or []
        if isinstance(item, dict) and evidence_box(item) is not None
    ]
    if not expected_fields:
        return None
    actual = actual_fields_by_code(result)
    hits = []
    for expected_field in expected_fields:
        candidates = actual.get(field_code(expected_field), [])
        if expected_field.get("value") is not None:
            expected_value = normalize_value(expected_field.get("value"))
            candidates = [
                candidate
                for candidate in candidates
                if field_value_matches(candidate.get("fieldValue"), expected_value, expected_field)
            ]
        hits.append(any(bbox_matches(candidate, expected_field) for candidate in candidates))
    return len([hit for hit in hits if hit]) / len(expected_fields)


def table_recall(result: dict[str, Any], expected: dict[str, Any]) -> float | None:
    expected_tables = [item for item in expected.get("tables") or [] if isinstance(item, dict)]
    if not expected_tables:
        return None
    tables = [item for item in result.get("tables") or [] if isinstance(item, dict)]
    matched = [table for table in expected_tables if any(table_matches(actual, table) for actual in tables)]
    return len(matched) / len(expected_tables)


def table_evidence_recall(result: dict[str, Any], expected: dict[str, Any]) -> float | None:
    expected_tables = [item for item in expected.get("tables") or [] if isinstance(item, dict)]
    if not expected_tables:
        return None
    tables = [item for item in result.get("tables") or [] if isinstance(item, dict)]
    hits = [
        any(table_matches(actual, expected_table) and evidence_box(actual) is not None for actual in tables)
        for expected_table in expected_tables
    ]
    return len([hit for hit in hits if hit]) / len(expected_tables)


def table_bbox_hit_rate(result: dict[str, Any], expected: dict[str, Any]) -> float | None:
    expected_tables = [
        item
        for item in expected.get("tables") or []
        if isinstance(item, dict) and evidence_box(item) is not None
    ]
    if not expected_tables:
        return None
    tables = [item for item in result.get("tables") or [] if isinstance(item, dict)]
    hits = [
        any(table_matches(actual, expected_table) and bbox_matches(actual, expected_table) for actual in tables)
        for expected_table in expected_tables
    ]
    return len([hit for hit in hits if hit]) / len(expected_tables)


def seal_recall(result: dict[str, Any], expected: dict[str, Any]) -> float | None:
    expected_seals = [item for item in expected.get("seals") or [] if isinstance(item, dict)]
    if not expected_seals:
        return None
    seals = [item for item in result.get("seals") or [] if isinstance(item, dict)]
    matched = [seal for seal in expected_seals if any(seal_matches(actual, seal) for actual in seals)]
    return len(matched) / len(expected_seals)


def seal_evidence_recall(result: dict[str, Any], expected: dict[str, Any]) -> float | None:
    expected_seals = [item for item in expected.get("seals") or [] if isinstance(item, dict)]
    if not expected_seals:
        return None
    seals = [item for item in result.get("seals") or [] if isinstance(item, dict)]
    hits = [
        any(seal_matches(actual, expected_seal) and evidence_box(actual) is not None for actual in seals)
        for expected_seal in expected_seals
    ]
    return len([hit for hit in hits if hit]) / len(expected_seals)


def seal_bbox_hit_rate(result: dict[str, Any], expected: dict[str, Any]) -> float | None:
    expected_seals = [
        item
        for item in expected.get("seals") or []
        if isinstance(item, dict) and evidence_box(item) is not None
    ]
    if not expected_seals:
        return None
    seals = [item for item in result.get("seals") or [] if isinstance(item, dict)]
    hits = [
        any(seal_matches(actual, expected_seal) and bbox_matches(actual, expected_seal) for actual in seals)
        for expected_seal in expected_seals
    ]
    return len([hit for hit in hits if hit]) / len(expected_seals)


def quality_status_match(result: dict[str, Any], expected: dict[str, Any]) -> float | None:
    expected_status = expected.get("qualityStatus")
    if not expected_status:
        return None
    quality = result.get("quality") if isinstance(result.get("quality"), dict) else {}
    return 1.0 if quality.get("status") == expected_status else 0.0


def quality_reason_recall(result: dict[str, Any], expected: dict[str, Any]) -> float | None:
    expected_reasons = [str(item) for item in expected.get("qualityReasons") or []]
    if not expected_reasons:
        return None
    quality = result.get("quality") if isinstance(result.get("quality"), dict) else {}
    actual_reasons = {str(item) for item in quality.get("reasons") or []}
    matched = [reason for reason in expected_reasons if reason in actual_reasons]
    return len(matched) / len(expected_reasons)


def quality_evidence_completeness_match(result: dict[str, Any], expected: dict[str, Any]) -> float | None:
    minimum = expected.get("minEvidenceCompleteness")
    maximum = expected.get("maxEvidenceCompleteness")
    if minimum is None and maximum is None:
        return None
    quality = result.get("quality") if isinstance(result.get("quality"), dict) else {}
    if "evidenceCompleteness" not in quality:
        return 0.0
    try:
        value = float(quality.get("evidenceCompleteness") or 0.0)
    except (TypeError, ValueError):
        return 0.0
    if minimum is not None and value < float(minimum):
        return 0.0
    if maximum is not None and value > float(maximum):
        return 0.0
    return 1.0


def weighted_score(metrics: dict[str, float | None], *, weights: dict[str, Any] | None = None) -> float:
    active_weights = {**DEFAULT_WEIGHTS, **(weights or {})}
    total_weight = 0.0
    total = 0.0
    for key, value in metrics.items():
        if value is None:
            continue
        weight = float(active_weights.get(key) or 0.0)
        if weight <= 0:
            continue
        total_weight += weight
        total += max(0.0, min(float(value), 1.0)) * weight
    return round(total / total_weight, 4) if total_weight else 0.0


def aggregate_case_metrics(case_reports: list[dict[str, Any]]) -> dict[str, float | None]:
    keys = sorted({key for report in case_reports for key in report.get("metrics", {})})
    return {
        key: round(average([value for report in case_reports if (value := report.get("metrics", {}).get(key)) is not None]), 4)
        if any(report.get("metrics", {}).get(key) is not None for report in case_reports)
        else None
        for key in keys
    }


def aggregate_scenarios(
    case_reports: list[dict[str, Any]],
    *,
    thresholds: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for report in case_reports:
        grouped.setdefault(str(report.get("scenario") or "default"), []).append(report)
    scenario_thresholds = (thresholds or {}).get("scenarios") if isinstance((thresholds or {}).get("scenarios"), dict) else {}
    summaries: dict[str, dict[str, Any]] = {}
    for scenario, reports in sorted(grouped.items()):
        metrics = aggregate_case_metrics(reports)
        finding_counts = aggregate_finding_counts(reports)
        summary = {
            "cases": len(reports),
            "passed": len([item for item in reports if item["passed"]]),
            "failed": len([item for item in reports if not item["passed"]]),
            "averageScore": round(average([item["score"] for item in reports]), 4),
        }
        threshold_block = scenario_thresholds.get(scenario) if isinstance(scenario_thresholds, dict) else None
        failures = threshold_failures_for_scope(scenario, summary, metrics, threshold_block or {})
        summaries[scenario] = {
            **summary,
            "ok": summary["failed"] == 0 and not failures,
            "metrics": metrics,
            "findingCounts": finding_counts,
            "thresholdFailures": failures,
        }
    return summaries


def aggregate_finding_counts(case_reports: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for report in case_reports:
        for finding in report.get("findings") or []:
            code = str(finding.get("code") if isinstance(finding, dict) else finding)
            counts[code] = counts.get(code, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def compact_evaluation_report(report: dict[str, Any]) -> dict[str, Any]:
    scenarios = report.get("scenarios") if isinstance(report.get("scenarios"), dict) else {}
    failed_cases = [
        compact_case_summary(case)
        for case in report.get("cases") or []
        if isinstance(case, dict) and not case.get("passed")
    ]
    return {
        "ok": bool(report.get("ok")),
        "summary": report.get("summary") if isinstance(report.get("summary"), dict) else {},
        "metrics": report.get("metrics") if isinstance(report.get("metrics"), dict) else {},
        "findingCounts": report.get("findingCounts") if isinstance(report.get("findingCounts"), dict) else {},
        "thresholdFailures": report.get("thresholdFailures") or [],
        "scenarioMetrics": {
            str(name): compact_scenario_summary(scenario)
            for name, scenario in sorted(scenarios.items())
            if isinstance(scenario, dict)
        },
        "failedCases": failed_cases,
    }


def compact_scenario_summary(scenario: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": bool(scenario.get("ok")),
        "cases": int(scenario.get("cases") or 0),
        "passed": int(scenario.get("passed") or 0),
        "failed": int(scenario.get("failed") or 0),
        "averageScore": scenario.get("averageScore"),
        "findingCounts": scenario.get("findingCounts") if isinstance(scenario.get("findingCounts"), dict) else {},
        "thresholdFailures": scenario.get("thresholdFailures") or [],
    }


def compact_case_summary(case: dict[str, Any]) -> dict[str, Any]:
    return {
        "caseId": case.get("caseId"),
        "scenario": case.get("scenario"),
        "score": case.get("score"),
        "minScore": case.get("minScore"),
        "qualityStatus": case.get("qualityStatus"),
        "findings": [
            item.get("code") if isinstance(item, dict) else str(item)
            for item in case.get("findings") or []
        ],
    }


def threshold_failures_for_scope(
    scope: str,
    summary: dict[str, Any],
    metrics: dict[str, float | None],
    thresholds: dict[str, Any],
) -> list[dict[str, Any]]:
    if not isinstance(thresholds, dict) or not thresholds:
        return []
    failures: list[dict[str, Any]] = []
    min_average = thresholds.get("averageScore")
    if min_average is not None and float(summary.get("averageScore") or 0) < float(min_average):
        failures.append(
            {
                "scope": scope,
                "metric": "averageScore",
                "actual": float(summary.get("averageScore") or 0),
                "minimum": float(min_average),
            }
        )
    min_cases = thresholds.get("minCases")
    if min_cases is not None and int(summary.get("cases") or 0) < int(min_cases):
        failures.append(
            {
                "scope": scope,
                "metric": "cases",
                "actual": int(summary.get("cases") or 0),
                "minimum": int(min_cases),
            }
        )
    metric_thresholds = thresholds.get("metrics") if isinstance(thresholds.get("metrics"), dict) else {}
    for metric, minimum in metric_thresholds.items():
        actual = metrics.get(str(metric))
        if actual is None:
            failures.append({"scope": scope, "metric": str(metric), "actual": None, "minimum": float(minimum)})
        elif float(actual) < float(minimum):
            failures.append({"scope": scope, "metric": str(metric), "actual": float(actual), "minimum": float(minimum)})
    return failures


def required_scenario_failures(
    thresholds: dict[str, Any],
    scenario_reports: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    required = [str(item) for item in thresholds.get("requiredScenarios") or []]
    missing = [scenario for scenario in required if scenario not in scenario_reports]
    return [
        {
            "scope": "overall",
            "metric": f"scenario.{scenario}",
            "actual": 0,
            "minimum": 1,
        }
        for scenario in missing
    ]


def build_findings(
    metrics: dict[str, float | None],
    result: dict[str, Any],
    expected: dict[str, Any],
    score: float,
    min_score: float,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    if score < min_score:
        findings.append({"code": "OCR_EVAL_SCORE_BELOW_THRESHOLD", "message": f"score is below {min_score:.2f}"})
    if metrics.get("fieldRecall") is not None and metrics["fieldRecall"] < 1:
        findings.append({"code": "OCR_EVAL_FIELD_MISSING", "message": "one or more expected fields were not found"})
    if metrics.get("fieldValueAccuracy") is not None and metrics["fieldValueAccuracy"] < 1:
        findings.append({"code": "OCR_EVAL_FIELD_VALUE_MISMATCH", "message": "one or more expected field values did not match"})
    if metrics.get("fieldEvidenceRecall") is not None and metrics["fieldEvidenceRecall"] < 1:
        findings.append({"code": "OCR_EVAL_FIELD_EVIDENCE_MISSING", "message": "one or more expected fields have no bbox or polygon evidence"})
    if metrics.get("fieldBboxHitRate") is not None and metrics["fieldBboxHitRate"] < 1:
        findings.append({"code": "OCR_EVAL_FIELD_BBOX_MISMATCH", "message": "one or more expected field boxes did not match"})
    if metrics.get("tableRecall") is not None and metrics["tableRecall"] < 1:
        findings.append({"code": "OCR_EVAL_TABLE_MISSING", "message": "one or more expected tables were not found"})
    if metrics.get("tableEvidenceRecall") is not None and metrics["tableEvidenceRecall"] < 1:
        findings.append({"code": "OCR_EVAL_TABLE_EVIDENCE_MISSING", "message": "one or more expected tables have no bbox or polygon evidence"})
    if metrics.get("tableBboxHitRate") is not None and metrics["tableBboxHitRate"] < 1:
        findings.append({"code": "OCR_EVAL_TABLE_BBOX_MISMATCH", "message": "one or more expected table boxes did not match"})
    if metrics.get("sealRecall") is not None and metrics["sealRecall"] < 1:
        findings.append({"code": "OCR_EVAL_SEAL_MISSING", "message": "one or more expected seals were not found"})
    if metrics.get("sealEvidenceRecall") is not None and metrics["sealEvidenceRecall"] < 1:
        findings.append({"code": "OCR_EVAL_SEAL_EVIDENCE_MISSING", "message": "one or more expected seals have no bbox or polygon evidence"})
    if metrics.get("sealBboxHitRate") is not None and metrics["sealBboxHitRate"] < 1:
        findings.append({"code": "OCR_EVAL_SEAL_BBOX_MISMATCH", "message": "one or more expected seal boxes did not match"})
    if metrics.get("qualityStatusMatch") == 0:
        quality = result.get("quality") if isinstance(result.get("quality"), dict) else {}
        findings.append(
            {
                "code": "OCR_EVAL_QUALITY_STATUS_MISMATCH",
                "message": f"expected quality status {expected.get('qualityStatus')}, got {quality.get('status')}",
            }
        )
    if metrics.get("qualityReasonRecall") is not None and metrics["qualityReasonRecall"] < 1:
        findings.append({"code": "OCR_EVAL_QUALITY_REASON_MISSING", "message": "one or more expected quality reasons were not found"})
    if metrics.get("qualityEvidenceCompletenessMatch") == 0:
        findings.append({"code": "OCR_EVAL_QUALITY_EVIDENCE_COMPLETENESS_MISMATCH", "message": "quality.evidenceCompleteness is outside the expected range"})
    return findings


def build_case_details(result: dict[str, Any], expected: dict[str, Any]) -> dict[str, Any]:
    return {
        "fields": field_details(result, expected),
        "tables": table_details(result, expected),
        "seals": seal_details(result, expected),
        "quality": quality_details(result, expected),
    }


def field_details(result: dict[str, Any], expected: dict[str, Any]) -> list[dict[str, Any]]:
    actual = actual_fields_by_code(result)
    details = []
    for expected_field in [item for item in expected.get("fields") or [] if isinstance(item, dict)]:
        code = field_code(expected_field)
        candidates = actual.get(code, [])
        expected_value = normalize_value(expected_field.get("value")) if expected_field.get("value") is not None else ""
        value_candidates = (
            [candidate for candidate in candidates if field_value_matches(candidate.get("fieldValue"), expected_value, expected_field)]
            if expected_value
            else candidates
        )
        bbox_candidates = [candidate for candidate in value_candidates if bbox_matches(candidate, expected_field)]
        evidence_candidates = [candidate for candidate in value_candidates if evidence_box(candidate) is not None]
        if not candidates:
            status = "missing"
        elif expected_value and not value_candidates:
            status = "value_mismatch"
        elif not evidence_candidates:
            status = "evidence_missing"
        elif evidence_box(expected_field) is not None and not bbox_candidates:
            status = "bbox_mismatch"
        else:
            status = "matched"
        details.append(
            {
                "fieldCode": code,
                "expectedValue": expected_field.get("value"),
                "expectedBbox": evidence_box(expected_field),
                "bboxIouThreshold": bbox_threshold(expected_field),
                "status": status,
                "bestIou": best_iou(candidates, expected_field),
                "candidates": [
                    candidate_summary(candidate, expected=expected_field, value_key="fieldValue")
                    for candidate in candidates
                ],
            }
        )
    return details


def table_details(result: dict[str, Any], expected: dict[str, Any]) -> list[dict[str, Any]]:
    tables = [item for item in result.get("tables") or [] if isinstance(item, dict)]
    details = []
    for expected_table in [item for item in expected.get("tables") or [] if isinstance(item, dict)]:
        semantic_candidates = [table for table in tables if table_matches(table, expected_table)]
        bbox_candidates = [table for table in semantic_candidates if bbox_matches(table, expected_table)]
        evidence_candidates = [table for table in semantic_candidates if evidence_box(table) is not None]
        if not semantic_candidates:
            status = "missing"
        elif not evidence_candidates:
            status = "evidence_missing"
        elif evidence_box(expected_table) is not None and not bbox_candidates:
            status = "bbox_mismatch"
        else:
            status = "matched"
        details.append(
            {
                "expectedBusinessSchema": expected_table.get("businessSchema"),
                "expectedBbox": evidence_box(expected_table),
                "bboxIouThreshold": bbox_threshold(expected_table),
                "requiredBusinessKeys": expected_table.get("requiredBusinessKeys") or [],
                "status": status,
                "bestIou": best_iou(tables, expected_table),
                "candidates": [candidate_summary(table, expected=expected_table, value_key="tableId") for table in tables],
            }
        )
    return details


def seal_details(result: dict[str, Any], expected: dict[str, Any]) -> list[dict[str, Any]]:
    seals = [item for item in result.get("seals") or [] if isinstance(item, dict)]
    details = []
    for expected_seal in [item for item in expected.get("seals") or [] if isinstance(item, dict)]:
        semantic_candidates = [seal for seal in seals if seal_matches(seal, expected_seal)]
        bbox_candidates = [seal for seal in semantic_candidates if bbox_matches(seal, expected_seal)]
        evidence_candidates = [seal for seal in semantic_candidates if evidence_box(seal) is not None]
        if not semantic_candidates:
            status = "missing"
        elif not evidence_candidates:
            status = "evidence_missing"
        elif evidence_box(expected_seal) is not None and not bbox_candidates:
            status = "bbox_mismatch"
        else:
            status = "matched"
        details.append(
            {
                "expectedSealType": expected_seal.get("sealType"),
                "expectedNameContains": expected_seal.get("nameContains"),
                "expectedSourceEngine": expected_seal.get("sourceEngine"),
                "expectedQualityFlags": expected_seal.get("qualityFlags") or [],
                "expectedFields": expected_seal.get("fields") or [],
                "expectedBbox": evidence_box(expected_seal),
                "bboxIouThreshold": bbox_threshold(expected_seal),
                "status": status,
                "bestIou": best_iou(seals, expected_seal),
                "candidates": [candidate_summary(seal, expected=expected_seal, value_key="sealName") for seal in seals],
            }
        )
    return details


def quality_details(result: dict[str, Any], expected: dict[str, Any]) -> dict[str, Any]:
    quality = result.get("quality") if isinstance(result.get("quality"), dict) else {}
    expected_status = expected.get("qualityStatus")
    expected_reasons = [str(item) for item in expected.get("qualityReasons") or []]
    actual_reasons = [str(item) for item in quality.get("reasons") or []]
    missing_reasons = [reason for reason in expected_reasons if reason not in set(actual_reasons)]
    completeness_match = quality_evidence_completeness_match(result, expected)
    return {
        "expectedStatus": expected_status,
        "actualStatus": quality.get("status"),
        "status": "matched" if not expected_status or quality.get("status") == expected_status else "status_mismatch",
        "expectedReasons": expected_reasons,
        "actualReasons": actual_reasons,
        "missingReasons": missing_reasons,
        "expectedMinEvidenceCompleteness": expected.get("minEvidenceCompleteness"),
        "expectedMaxEvidenceCompleteness": expected.get("maxEvidenceCompleteness"),
        "actualEvidenceCompleteness": quality.get("evidenceCompleteness"),
        "evidenceCompletenessStatus": "matched" if completeness_match in {None, 1.0} else "range_mismatch",
    }


def candidate_summary(candidate: dict[str, Any], *, expected: dict[str, Any], value_key: str) -> dict[str, Any]:
    return {
        "id": candidate.get("fieldCode") or candidate.get("tableId") or candidate.get("sealId"),
        "value": candidate.get(value_key),
        "confidence": candidate.get("confidence") or candidate.get("structureConfidence") or candidate.get("ocrConfidence") or candidate.get("visualConfidence"),
        "bbox": evidence_box(candidate),
        "iou": bbox_iou(evidence_box(candidate), evidence_box(expected)) if evidence_box(candidate) and evidence_box(expected) else None,
        "sourceEngine": candidate.get("sourceEngine"),
        "qualityFlags": candidate.get("qualityFlags") or [],
        "fieldCodes": [
            str(field.get("fieldCode") or field.get("fieldName") or "")
            for field in candidate.get("fields") or []
            if isinstance(field, dict)
        ],
    }


def best_iou(candidates: list[dict[str, Any]], expected: dict[str, Any]) -> float | None:
    expected_box = evidence_box(expected)
    if expected_box is None:
        return None
    scores = [
        bbox_iou(actual_box, expected_box)
        for candidate in candidates
        if (actual_box := evidence_box(candidate)) is not None
    ]
    return round(max(scores), 4) if scores else 0.0


def actual_fields_by_code(result: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for field in result.get("fields") or []:
        if not isinstance(field, dict):
            continue
        code = field_code(field)
        if code:
            grouped.setdefault(code, []).append(field)
    return grouped


def table_matches(actual: dict[str, Any], expected: dict[str, Any]) -> bool:
    if expected.get("tableId") and actual.get("tableId") != expected.get("tableId"):
        return False
    if expected.get("businessSchema") and actual.get("businessSchema") != expected.get("businessSchema"):
        return False
    if int(actual.get("rows") or 0) < int(expected.get("minRows") or 0):
        return False
    if int(actual.get("columns") or 0) < int(expected.get("minColumns") or 0):
        return False
    required_keys = [str(item) for item in expected.get("requiredBusinessKeys") or []]
    if required_keys:
        rows = actual.get("businessRows") or actual.get("normalizedRows") or []
        present_keys = {key for row in rows if isinstance(row, dict) for key, value in row.items() if value not in {None, ""}}
        if not set(required_keys) <= present_keys:
            return False
    return True


def seal_matches(actual: dict[str, Any], expected: dict[str, Any]) -> bool:
    if expected.get("sealType") and actual.get("sealType") != expected.get("sealType"):
        return False
    source_engine = expected.get("sourceEngine")
    if source_engine and actual.get("sourceEngine") != source_engine:
        return False
    source_engines = [str(item) for item in expected.get("sourceEngines") or []]
    if source_engines and str(actual.get("sourceEngine") or "") not in source_engines:
        return False
    name_contains = normalize_value(expected.get("nameContains"))
    if name_contains and name_contains not in normalize_value(actual.get("sealName")):
        return False
    min_confidence = expected.get("minConfidence")
    if min_confidence is not None and float(actual.get("ocrConfidence") or actual.get("visualConfidence") or 0) < float(min_confidence):
        return False
    required_flags = {str(item) for item in expected.get("qualityFlags") or []}
    if required_flags and not required_flags <= {str(item) for item in actual.get("qualityFlags") or []}:
        return False
    return seal_fields_match(actual, expected)


def seal_fields_match(actual: dict[str, Any], expected: dict[str, Any]) -> bool:
    expected_fields = [item for item in expected.get("fields") or [] if isinstance(item, dict)]
    if not expected_fields:
        return True
    actual_fields = {
        str(field.get("fieldCode") or field.get("fieldName") or ""): field
        for field in actual.get("fields") or []
        if isinstance(field, dict)
    }
    for expected_field in expected_fields:
        code = str(expected_field.get("fieldCode") or expected_field.get("fieldName") or "")
        if not code or code not in actual_fields:
            return False
        expected_value = normalize_value(expected_field.get("value"))
        if expected_value:
            actual_value = normalize_value(actual_fields[code].get("fieldValue"))
            if expected_field.get("contains"):
                if expected_value not in actual_value:
                    return False
            elif actual_value != expected_value:
                return False
        min_confidence = expected_field.get("minConfidence")
        if min_confidence is not None:
            try:
                actual_confidence = float(actual_fields[code].get("confidence") or 0)
            except (TypeError, ValueError):
                return False
            if actual_confidence < float(min_confidence):
                return False
    return True


def field_value_matches(actual_value: Any, expected_value: str, expected_field: dict[str, Any]) -> bool:
    actual = normalize_value(actual_value)
    if expected_field.get("contains"):
        return expected_value in actual
    return actual == expected_value


def field_code(field: dict[str, Any]) -> str:
    return str(field.get("fieldCode") or field.get("code") or field.get("fieldName") or field.get("name") or "")


def bbox_matches(actual: dict[str, Any], expected: dict[str, Any]) -> bool:
    actual_box = evidence_box(actual)
    expected_box = evidence_box(expected)
    if actual_box is None or expected_box is None:
        return False
    return bbox_iou(actual_box, expected_box) >= bbox_threshold(expected)


def bbox_threshold(expected: dict[str, Any]) -> float:
    return float(expected.get("bboxIouThreshold") or expected.get("iouThreshold") or 0.5)


def evidence_box(item: dict[str, Any]) -> list[float] | None:
    return flat_box(item.get("bbox")) or flat_box(item.get("polygon"))


def flat_box(raw: Any) -> list[float] | None:
    if not isinstance(raw, list) or not raw:
        return None
    if len(raw) == 4 and all(isinstance(value, (int, float)) for value in raw):
        x0, y0, x1, y1 = [float(value) for value in raw]
        return [min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)]
    points = []
    for point in raw:
        if isinstance(point, (list, tuple)) and len(point) >= 2:
            try:
                points.append((float(point[0]), float(point[1])))
            except (TypeError, ValueError):
                continue
    if not points:
        return None
    return [min(x for x, _ in points), min(y for _, y in points), max(x for x, _ in points), max(y for _, y in points)]


def bbox_iou(left: list[float], right: list[float]) -> float:
    lx0, ly0, lx1, ly1 = left
    rx0, ry0, rx1, ry1 = right
    inter_x0 = max(lx0, rx0)
    inter_y0 = max(ly0, ry0)
    inter_x1 = min(lx1, rx1)
    inter_y1 = min(ly1, ry1)
    if inter_x1 <= inter_x0 or inter_y1 <= inter_y0:
        return 0.0
    intersection = (inter_x1 - inter_x0) * (inter_y1 - inter_y0)
    left_area = max((lx1 - lx0) * (ly1 - ly0), 0.0)
    right_area = max((rx1 - rx0) * (ry1 - ry0), 0.0)
    union = left_area + right_area - intersection
    return intersection / union if union > 0 else 0.0


def scenario_for_case(case: dict[str, Any], result: dict[str, Any]) -> str:
    return str(
        case.get("scenario")
        or case.get("category")
        or case.get("documentType")
        or result.get("documentType")
        or case.get("profileId")
        or result.get("profileId")
        or "default"
    )


def normalize_value(value: Any) -> str:
    return "".join(str(value or "").split()).lower()


def load_json_file(path: Path) -> dict[str, Any]:
    return __import__("json").loads(path.read_text(encoding="utf-8"))


def average(values: list[float]) -> float:
    clean = [float(value) for value in values if value is not None]
    return sum(clean) / len(clean) if clean else 0.0
