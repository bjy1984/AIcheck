from __future__ import annotations

from typing import Any

from apps.ocr_service.evaluation import OCR_100_REQUIRED_SCENARIOS, ocr_100_thresholds

OCR_100_REQUIRED_ENGINES = [
    "paddle_ocr_subprocess",
    "pp_structure_v3",
    "paddlex_seal_recognition",
    "paddleocr_vl_1_6",
    "docling_local",
]


def build_ocr_100_scorecard(
    *,
    evaluation_report: dict[str, Any],
    runtime_doctor: dict[str, Any] | None = None,
    sample_summaries: list[dict[str, Any]] | None = None,
    runtime_profile: str = "local",
) -> dict[str, Any]:
    sections = [
        runtime_section(runtime_doctor, runtime_profile=runtime_profile),
        evaluation_section(evaluation_report),
        sample_section(sample_summaries or []),
        observability_section(evaluation_report),
    ]
    score = round(sum(float(section["score"]) for section in sections), 2)
    blockers = [
        blocker
        for section in sections
        for blocker in section.get("blockers", [])
    ]
    return {
        "schemaVersion": "aicheck-ocr-100-scorecard-v1",
        "targetScore": 100,
        "runtimeProfile": runtime_profile,
        "score": score,
        "ok": score >= 100 and not blockers,
        "sections": sections,
        "blockers": blockers,
    }


def runtime_section(runtime_doctor: dict[str, Any] | None, *, runtime_profile: str = "local") -> dict[str, Any]:
    if not isinstance(runtime_doctor, dict):
        return section("runtime", 0, 25, ["runtime doctor report is missing"])
    if runtime_profile == "official":
        services = runtime_doctor.get("serviceReadiness") if isinstance(runtime_doctor.get("serviceReadiness"), dict) else {}
        ocr = services.get("ocr") if isinstance(services.get("ocr"), dict) else runtime_doctor.get("ocr")
        ocr = ocr if isinstance(ocr, dict) else runtime_doctor
        telemetry = runtime_doctor.get("officialOcrTelemetry")
        telemetry = telemetry if isinstance(telemetry, dict) else {}
        capacity = ocr.get("capacityControl") if isinstance(ocr.get("capacityControl"), dict) else {}
        circuit = ocr.get("circuitBreaker") if isinstance(ocr.get("circuitBreaker"), dict) else {}
        capabilities = {
            "provider configured": ocr.get("configured") is True and ocr.get("providerMode") == "official",
            "live inference observed": bool(telemetry.get("lastSuccessfulInferenceAt") or ocr.get("lastSuccessfulInferenceAt")),
            "distributed control ready": capacity.get("distributed") is True and capacity.get("ready") is True,
            "local heavy fallback disabled": ocr.get("localHeavyFallbackEnabled") is False,
            "silent fallback disabled": ocr.get("silentFallbackEnabled") is False,
        }
        blockers = [label for label, passed in capabilities.items() if not passed]
        return section("runtime", 5 * len([item for item in capabilities.values() if item]), 25, blockers)
    checks = runtime_doctor.get("checks") if isinstance(runtime_doctor.get("checks"), list) else []
    checks_by_name = {
        str(check.get("name")): check
        for check in checks
        if isinstance(check, dict)
    }
    points = 0.0
    blockers: list[str] = []
    for engine in OCR_100_REQUIRED_ENGINES:
        check = checks_by_name.get(f"engine.{engine}")
        if check and check.get("status") == "pass":
            points += 3
        else:
            blockers.append(f"required OCR engine unavailable: {engine}")
    for policy in ["policy.offline-only", "policy.network-disabled", "policy.placeholder-disabled"]:
        check = checks_by_name.get(policy)
        if check and check.get("status") == "pass":
            points += 2
        else:
            blockers.append(f"OCR runtime policy failed: {policy}")
    if not [check for check in checks if isinstance(check, dict) and check.get("status") == "fail"]:
        points += 4
    else:
        blockers.append("runtime doctor has failed checks")
    return section("runtime", points, 25, blockers)


def evaluation_section(report: dict[str, Any]) -> dict[str, Any]:
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    metrics = report.get("metrics") if isinstance(report.get("metrics"), dict) else {}
    scenarios = report.get("scenarios") if isinstance(report.get("scenarios"), dict) else {}
    thresholds = ocr_100_thresholds()
    points = 0.0
    blockers: list[str] = []
    if report.get("ok"):
        points += 5
    else:
        blockers.append("evaluation report is not ok under configured thresholds")
    derived_cases = [
        case
        for case in report.get("cases") or []
        if isinstance(case, dict)
        and (
            case.get("bootstrapGenerated")
            or case.get("fixtureDerived")
            or str(case.get("collectionStatus") or "") == "needs_real_sample_replacement"
        )
    ]
    if derived_cases:
        blockers.append(f"evaluation set contains {len(derived_cases)} bootstrap/fixture-derived cases that must be replaced with real labelled samples")
    if safe_float(summary.get("averageScore")) >= 0.96:
        points += 8
    else:
        blockers.append("evaluation averageScore is below 0.96")
    if safe_int(summary.get("cases")) >= 100:
        points += 8
    else:
        blockers.append("evaluation set has fewer than 100 cases")
    missing_scenarios = [scenario for scenario in OCR_100_REQUIRED_SCENARIOS if scenario not in scenarios]
    if not missing_scenarios:
        points += 8
    else:
        blockers.append("evaluation set is missing scenarios: " + ", ".join(missing_scenarios))
    metric_thresholds = thresholds["metrics"]
    passed_metrics = [
        metric
        for metric, minimum in metric_thresholds.items()
        if metrics.get(metric) is not None and safe_float(metrics.get(metric)) >= float(minimum)
    ]
    points += 16 * (len(passed_metrics) / (len(metric_thresholds) or 1))
    failed_metrics = sorted(set(metric_thresholds) - set(passed_metrics))
    if failed_metrics:
        blockers.append("evaluation metrics below OCR 100 thresholds: " + ", ".join(failed_metrics))
    return section("evaluation", points, 45, blockers)


def sample_section(summaries: list[dict[str, Any]]) -> dict[str, Any]:
    if not summaries:
        return section("sample-probes", 0, 20, ["real sample probe summaries are missing"])
    blockers: list[str] = []
    points = 0.0
    all_gate_passed = all(bool(summary.get("gatePassed")) for summary in summaries)
    if all_gate_passed:
        points += 5
    else:
        blockers.append("one or more sample probes failed gates")
    auto_usable = all(summary.get("qualityStatus") == "auto_usable" for summary in summaries)
    if auto_usable:
        points += 3
    else:
        blockers.append("one or more sample probes are not auto_usable")
    no_missing_expected_seal_types = all(safe_int(summary.get("missingExpectedSealTypeCount")) == 0 for summary in summaries)
    if no_missing_expected_seal_types:
        points += 3
    else:
        blockers.append("one or more sample probes miss expected seal types")
    gates = [
        ("fields", 5),
        ("formalTables", 1),
        ("businessRows", 5),
        ("readableSeals", 1),
        ("fragmentSeals", 1),
    ]
    for key, minimum in gates:
        if all(safe_int(summary.get(key)) >= minimum for summary in summaries):
            points += 1.5
        else:
            blockers.append(f"sample probe {key} is below {minimum}")
    if all(safe_float(summary.get("evidenceCompleteness")) >= 0.95 for summary in summaries):
        points += 1.5
    else:
        blockers.append("sample probe evidenceCompleteness is below 0.95")
    return section("sample-probes", points, 20, blockers)


def observability_section(report: dict[str, Any]) -> dict[str, Any]:
    points = 0.0
    blockers: list[str] = []
    for key in ["summary", "metrics", "findingCounts", "thresholdFailures", "scenarios", "cases"]:
        if key in report:
            points += 10 / 6
        else:
            blockers.append(f"evaluation report is missing {key}")
    return section("observability", points, 10, blockers)


def section(name: str, score: float, max_score: float, blockers: list[str]) -> dict[str, Any]:
    score = round(min(max(score, 0.0), max_score), 2)
    return {
        "name": name,
        "score": score,
        "maxScore": max_score,
        "status": "pass" if score >= max_score and not blockers else "fail",
        "blockers": blockers,
    }


def safe_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def safe_int(value: Any) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0
