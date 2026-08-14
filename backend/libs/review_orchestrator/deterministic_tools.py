from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

RESULT_SCHEMA = "deterministic-tool-result-v1"


DETERMINISTIC_TOOL_DESCRIPTORS: list[dict[str, Any]] = [
    {
        "name": "check_all_equal",
        "capability": "比较多个证据来源的标准化值是否一致。",
        "inputSchema": {
            "values": [{"source": "string", "value": "any"}],
            "normalizer": "string?",
            "requiredCount": "integer?",
        },
        "outputSchema": RESULT_SCHEMA,
    },
    {
        "name": "check_date_covers",
        "capability": "判断证照或报告有效期是否覆盖指定业务周期。",
        "inputSchema": {
            "validFrom": "date?",
            "validUntil": "date",
            "periodStart": "date",
            "periodEnd": "date",
        },
        "outputSchema": RESULT_SCHEMA,
    },
    {
        "name": "check_design_license_scope",
        "capability": "按照设计许可级别规则判断许可范围是否覆盖项目管道级别。",
        "inputSchema": {"licenseScopes": ["string"], "requiredPipelineGrades": ["string"]},
        "outputSchema": RESULT_SCHEMA,
    },
    {
        "name": "decode_welder_qualification",
        "capability": "解析焊工资格作业项目代号，输出焊接方法、材料、位置、厚度和管径覆盖。",
        "inputSchema": {"qualificationCodes": ["string"]},
        "outputSchema": RESULT_SCHEMA,
    },
    {
        "name": "check_welder_work_coverage",
        "capability": "判断焊工资格项目是否覆盖实际焊接方法、材料类别、位置、壁厚和管径。",
        "inputSchema": {"qualificationCodes": ["string"], "workItems": ["object"]},
        "outputSchema": RESULT_SCHEMA,
    },
    {
        "name": "check_pressure_gauge_requirements",
        "capability": "检查耐压试验压力表数量、检定有效期、精度、量程、表盘直径记录和最高点安装。",
        "inputSchema": {
            "gauges": ["object"],
            "maxTestPressure": "number",
            "testDate": "date",
            "medium": "string",
            "mediumTemperature": "number",
            "ambientTemperature": "number",
        },
        "outputSchema": RESULT_SCHEMA,
    },
    {
        "name": "check_pressure_test_parameters",
        "capability": "检查液压或气压试验的最低/最高压力、温度许用应力比、保压、气压分级升压和结果。",
        "inputSchema": {
            "method": "liquid|gas",
            "designPressure": "number",
            "testPressure": "number",
            "holdMinutes": "number",
            "testResult": "string",
            "allowableStressAtTestTemperature": "number?",
            "allowableStressAtDesignTemperature": "number?",
            "maximumAllowableTestPressure": "number",
            "pneumaticYieldLimitPressure": "number?",
            "pressureSteps": ["object?"],
        },
        "outputSchema": RESULT_SCHEMA,
    },
    {
        "name": "check_pressure_test_report_consistency",
        "capability": "核对耐压试验报告、试验方案和现场记录的关键参数及结论。",
        "inputSchema": {"report": "object", "observed": "object", "tolerance": "number?"},
        "outputSchema": RESULT_SCHEMA,
    },
    {
        "name": "validate_evidence_grounding",
        "capability": "校验结论事实是否具有页码、坐标、原文和足够置信度的证据引用。",
        "inputSchema": {"facts": ["object"], "evidenceRefs": ["object"], "minConfidence": "number?"},
        "outputSchema": "evidence-gate-result-v1",
    },
]


DETERMINISTIC_TOOL_NAMES = {item["name"] for item in DETERMINISTIC_TOOL_DESCRIPTORS}


def dispatch_deterministic_tool(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    handlers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
        "check_all_equal": check_all_equal,
        "check_date_covers": check_date_covers,
        "check_design_license_scope": check_design_license_scope,
        "decode_welder_qualification": decode_welder_qualification,
        "check_welder_work_coverage": check_welder_work_coverage,
        "check_pressure_gauge_requirements": check_pressure_gauge_requirements,
        "check_pressure_test_parameters": check_pressure_test_parameters,
        "check_pressure_test_report_consistency": check_pressure_test_report_consistency,
        "validate_evidence_grounding": validate_evidence_grounding,
    }
    return handlers[tool_name](arguments)


def check_all_equal(arguments: dict[str, Any]) -> dict[str, Any]:
    values = [item for item in arguments.get("values") or [] if isinstance(item, dict)]
    normalizer = str(arguments.get("normalizer") or "text")
    usable = [item for item in values if item.get("value") not in {None, ""}]
    try:
        required_count = int(arguments.get("requiredCount") or 2)
    except (TypeError, ValueError):
        required_count = 2
    if len(usable) < max(2, required_count):
        return result("check_all_equal", "evidence_insufficient", facts={"values": usable}, checks=[])
    normalized = [normalize_value(item.get("value"), normalizer) for item in usable]
    passed = len(set(normalized)) == 1
    return result(
        "check_all_equal",
        "passed" if passed else "failed",
        facts={"values": usable, "normalizedValues": normalized},
        checks=[check("all_values_equal", passed, normalized[0], sorted(set(normalized)))],
    )


def check_date_covers(arguments: dict[str, Any]) -> dict[str, Any]:
    parsed = {key: parse_date(arguments.get(key)) for key in ("validFrom", "validUntil", "periodStart", "periodEnd")}
    required = ("validUntil", "periodStart", "periodEnd")
    if any(parsed[key] is None for key in required):
        return result("check_date_covers", "evidence_insufficient", facts=parsed, checks=[])
    starts_before = parsed["validFrom"] is None or parsed["validFrom"] <= parsed["periodStart"]
    ends_after = parsed["validUntil"] >= parsed["periodEnd"]
    output = result(
        "check_date_covers",
        "passed" if starts_before and ends_after else "failed",
        facts={key: value.isoformat() if value else None for key, value in parsed.items()},
        checks=[
            check("valid_from_covers_period_start", starts_before, parsed["validFrom"], parsed["periodStart"]),
            check("valid_until_covers_period_end", ends_after, parsed["validUntil"], parsed["periodEnd"]),
        ],
    )
    if output["result"] == "failed" and arguments.get("failureAction"):
        output["recommendedActions"] = [
            {
                "action": str(arguments["failureAction"]),
                "externalDocumentCreated": False,
            }
        ]
    return output


def check_design_license_scope(arguments: dict[str, Any]) -> dict[str, Any]:
    scopes = {normalize_grade(item) for item in arguments.get("licenseScopes") or [] if item}
    required = {normalize_grade(item) for item in arguments.get("requiredPipelineGrades") or [] if item}
    if not scopes or not required:
        return result(
            "check_design_license_scope",
            "evidence_insufficient",
            facts={"licenseScopes": sorted(scopes), "requiredPipelineGrades": sorted(required)},
            checks=[],
            rule_version="design-license-scope-cn-v1",
        )
    coverage = {
        "GC1": {"GC1"},
        "GC2": {"GC1", "GC2"},
        "GCD": {"GCD"},
    }
    checks = []
    for grade in sorted(required):
        allowed = coverage.get(grade, {grade})
        checks.append(check(f"scope_covers_{grade}", bool(scopes & allowed), sorted(scopes), sorted(allowed)))
    passed = all(item["passed"] for item in checks)
    return result(
        "check_design_license_scope",
        "passed" if passed else "failed",
        facts={"licenseScopes": sorted(scopes), "requiredPipelineGrades": sorted(required)},
        checks=checks,
        rule_version="design-license-scope-cn-v1",
    )


def decode_welder_qualification(arguments: dict[str, Any]) -> dict[str, Any]:
    codes = [str(item).strip() for item in arguments.get("qualificationCodes") or [] if str(item).strip()]
    decoded = [decode_welder_code(item) for item in codes]
    valid = [item for item in decoded if item.get("parseStatus") == "parsed"]
    rule_version, transition_warning = welder_rule_version(arguments)
    if transition_warning:
        return result(
            "decode_welder_qualification",
            "evidence_insufficient",
            facts={"qualificationCodes": codes, "decodedItems": decoded, "reason": transition_warning},
            checks=[],
            rule_version=rule_version,
        )
    return result(
        "decode_welder_qualification",
        "passed" if codes and len(valid) == len(codes) else "evidence_insufficient",
        facts={"qualificationCodes": codes, "decodedItems": decoded},
        checks=[check("all_codes_decoded", bool(codes) and len(valid) == len(codes), len(valid), len(codes))],
        rule_version=rule_version,
    )


def check_welder_work_coverage(arguments: dict[str, Any]) -> dict[str, Any]:
    rule_version, transition_warning = welder_rule_version(arguments)
    if transition_warning:
        return result(
            "check_welder_work_coverage",
            "evidence_insufficient",
            facts={"reason": transition_warning, "reviewDate": arguments.get("reviewDate")},
            checks=[],
            rule_version=rule_version,
        )
    certificates = [item for item in arguments.get("certificates") or [] if isinstance(item, dict)]
    codes = [str(code) for code in arguments.get("qualificationCodes") or []]
    decoded = [decode_welder_code(code) for code in codes] if not certificates else []
    for certificate in certificates:
        for code in certificate.get("qualificationCodes") or certificate.get("qualifiedItems") or []:
            if isinstance(code, dict):
                continue
            item = decode_welder_code(str(code))
            item["certificateNo"] = certificate.get("welderCertificateNo") or certificate.get("certificateNo")
            item["welderName"] = certificate.get("welderName") or certificate.get("name")
            decoded.append(item)
    decoded.extend(item for item in arguments.get("qualifiedItems") or [] if isinstance(item, dict))
    decoded.extend(item for certificate in certificates for item in certificate.get("qualifiedItems") or [] if isinstance(item, dict))
    qualifications = [item for item in decoded if item.get("parseStatus", "parsed") == "parsed"]
    work_items = [item for item in arguments.get("workItems") or [] if isinstance(item, dict)]
    if not qualifications or not work_items:
        return result(
            "check_welder_work_coverage",
            "evidence_insufficient",
            facts={"qualifications": qualifications, "workItems": work_items},
            checks=[],
            rule_version=rule_version,
        )
    work_checks = []
    certificate_failed = False
    certificate_incomplete = False
    work_date = parse_date(arguments.get("workDate") or arguments.get("reviewDate"))
    for index, certificate in enumerate(certificates, 1):
        valid_until = parse_date(certificate.get("validUntil"))
        valid_from = parse_date(certificate.get("validFrom"))
        identity = certificate.get("personIdentityMatched")
        source_verified = certificate.get("originalSeen") is True or certificate.get("verifiedCopy") is True
        if work_date is None or valid_until is None or identity is None or not source_verified:
            certificate_incomplete = True
        if work_date and (valid_until and valid_until < work_date or valid_from and valid_from > work_date) or identity is False:
            certificate_failed = True
        work_checks.extend(
            [
                check(f"certificate_{index}_valid_on_work_date", work_date is not None and valid_until is not None and (valid_from is None or valid_from <= work_date) and valid_until >= work_date, {"validFrom": valid_from, "validUntil": valid_until}, work_date),
                check(f"certificate_{index}_person_identity_matches", identity is True, identity, True),
                check(f"certificate_{index}_original_or_verified_copy", source_verified, source_verified, True),
            ]
        )
    for index, work in enumerate(work_items, 1):
        matched = [item for item in qualifications if qualification_covers_work(item, work)]
        work_checks.append(check(f"work_item_{index}_covered", bool(matched), work, [item.get("code") for item in matched]))
    coverage_passed = all(item["passed"] for item in work_checks[-len(work_items):])
    status = "failed" if certificate_failed or not coverage_passed else "evidence_insufficient" if certificate_incomplete else "passed"
    return result(
        "check_welder_work_coverage",
        status,
        facts={"qualifications": qualifications, "workItems": work_items, "certificates": certificates},
        checks=work_checks,
        rule_version=rule_version,
    )


def check_pressure_gauge_requirements(arguments: dict[str, Any]) -> dict[str, Any]:
    gauges = [item for item in arguments.get("gauges") or [] if isinstance(item, dict)]
    max_pressure = decimal(arguments.get("maxTestPressure"))
    test_date = parse_date(arguments.get("testDate"))
    medium = str(arguments.get("medium") or "").strip()
    medium_temperature = decimal(arguments.get("mediumTemperature"))
    ambient_temperature = decimal(arguments.get("ambientTemperature"))
    if (
        max_pressure is None
        or max_pressure <= 0
        or test_date is None
        or not gauges
        or not medium
        or medium_temperature is None
        or ambient_temperature is None
    ):
        return result("check_pressure_gauge_requirements", "evidence_insufficient", facts=arguments, checks=[])
    checks = [
        check("gauge_count_at_least_two", len(gauges) >= 2, len(gauges), 2),
        check("at_least_one_gauge_at_highest_point", any(item.get("atHighestPoint") is True for item in gauges), [item.get("atHighestPoint") for item in gauges], True),
        check("test_medium_present", bool(medium), medium, "required"),
        check("medium_temperature_present", medium_temperature is not None, medium_temperature, "required"),
        check("ambient_temperature_present", ambient_temperature is not None, ambient_temperature, "required"),
    ]
    allowed_media = {normalize_value(item, "text") for item in arguments.get("allowedMedia") or [] if item}
    if allowed_media:
        checks.append(check("test_medium_allowed", normalize_value(medium, "text") in allowed_media, medium, sorted(allowed_media)))
    min_medium_temperature = decimal(arguments.get("minMediumTemperature"))
    if min_medium_temperature is not None:
        checks.append(check("medium_temperature_minimum", medium_temperature >= min_medium_temperature, medium_temperature, min_medium_temperature))
    min_ambient_temperature = decimal(arguments.get("minAmbientTemperature"))
    if min_ambient_temperature is not None:
        checks.append(check("ambient_temperature_minimum", ambient_temperature >= min_ambient_temperature, ambient_temperature, min_ambient_temperature))
    for index, gauge in enumerate(gauges, 1):
        valid_until = parse_date(gauge.get("validUntil"))
        accuracy = decimal(gauge.get("accuracyClass"))
        range_max = decimal(gauge.get("rangeMax"))
        dial_diameter = decimal(gauge.get("dialDiameter"))
        ratio = range_max / max_pressure if range_max is not None else None
        checks.extend(
            [
                check(f"gauge_{index}_calibration_valid", valid_until is not None and valid_until >= test_date, valid_until, test_date),
                check(f"gauge_{index}_accuracy", accuracy is not None and accuracy <= Decimal("1.6"), accuracy, "<=1.6"),
                check(f"gauge_{index}_dial_diameter_recorded", dial_diameter is not None and dial_diameter > 0, dial_diameter, "recorded_positive_value"),
                check(
                    f"gauge_{index}_range_ratio",
                    ratio is not None and Decimal("1.5") <= ratio <= Decimal(2),
                    ratio,
                    "1.5..2.0",
                ),
            ]
        )
    return result(
        "check_pressure_gauge_requirements",
        "passed" if all(item["passed"] for item in checks) else "failed",
        facts={
            "gauges": gauges,
            "maxTestPressure": max_pressure,
            "testDate": test_date,
            "medium": medium,
            "mediumTemperature": medium_temperature,
            "ambientTemperature": ambient_temperature,
        },
        checks=checks,
        rule_version="pressure-gauge-requirements-v1",
    )


def check_pressure_test_parameters(arguments: dict[str, Any]) -> dict[str, Any]:
    method = str(arguments.get("method") or "").strip().lower()
    design_pressure = decimal(arguments.get("designPressure"))
    test_pressure = decimal(arguments.get("testPressure"))
    hold_minutes = decimal(arguments.get("holdMinutes"))
    test_result = str(arguments.get("testResult") or "").strip().lower()
    maximum_allowable = decimal(arguments.get("maximumAllowableTestPressure"))
    if (
        method not in {"liquid", "gas"}
        or None in {design_pressure, test_pressure, hold_minutes, maximum_allowable}
        or design_pressure <= 0
        or test_pressure <= 0
        or maximum_allowable <= 0
        or not test_result
    ):
        return result("check_pressure_test_parameters", "evidence_insufficient", facts=arguments, checks=[])
    checks = [check("test_pressure_within_component_limit", test_pressure <= maximum_allowable, test_pressure, maximum_allowable)]
    if method == "liquid":
        stress_at_test = decimal(arguments.get("allowableStressAtTestTemperature"))
        stress_at_design = decimal(arguments.get("allowableStressAtDesignTemperature"))
        if stress_at_test is None or stress_at_design is None or stress_at_test <= 0 or stress_at_design <= 0:
            return result(
                "check_pressure_test_parameters",
                "evidence_insufficient",
                facts=arguments,
                checks=[],
                rule_version="pressure-test-parameters-gbt20801-v2",
            )
        required_pressure = Decimal("1.5") * design_pressure * stress_at_test / stress_at_design
        checks.append(check("liquid_minimum_test_pressure", test_pressure >= required_pressure, test_pressure, required_pressure))
    else:
        yield_limit_pressure = decimal(arguments.get("pneumaticYieldLimitPressure"))
        pressure_steps = [item for item in arguments.get("pressureSteps") or [] if isinstance(item, dict)]
        if yield_limit_pressure is None or yield_limit_pressure <= 0 or not pressure_steps:
            return result(
                "check_pressure_test_parameters",
                "evidence_insufficient",
                facts=arguments,
                checks=[],
                rule_version="pressure-test-parameters-gbt20801-v2",
            )
        upper_limit = min(design_pressure * Decimal("1.33"), yield_limit_pressure, maximum_allowable)
        checks.extend(
            [
                check("gas_minimum_test_pressure", test_pressure >= design_pressure * Decimal("1.1"), test_pressure, design_pressure * Decimal("1.1")),
                check("gas_maximum_test_pressure", test_pressure <= upper_limit, test_pressure, upper_limit),
                *pneumatic_step_checks(pressure_steps, test_pressure),
            ]
        )
    checks.extend(
        [
            check("pressure_hold_at_least_10_minutes", hold_minutes >= Decimal(10), hold_minutes, 10),
            check("test_result_accepted", test_result in {"passed", "qualified", "合格", "无泄漏", "no_leak"}, test_result, "accepted"),
        ]
    )
    return result(
        "check_pressure_test_parameters",
        "passed" if all(item["passed"] for item in checks) else "failed",
        facts={
            "method": method,
            "designPressure": design_pressure,
            "testPressure": test_pressure,
            "holdMinutes": hold_minutes,
            "testResult": test_result,
        },
        checks=checks,
        rule_version="pressure-test-parameters-gbt20801-v2",
    )


def pneumatic_step_checks(steps: list[dict[str, Any]], test_pressure: Decimal) -> list[dict[str, Any]]:
    parsed = [(decimal(item.get("pressure")), decimal(item.get("holdMinutes"))) for item in steps]
    if any(pressure is None or hold is None for pressure, hold in parsed):
        return [check("gas_pressure_steps_complete", False, steps, "pressure+holdMinutes")]
    pressures = [pressure for pressure, _ in parsed]
    checks = [
        check("gas_first_step_50_percent", abs(pressures[0] - test_pressure * Decimal("0.5")) <= test_pressure * Decimal("0.01"), pressures[0], test_pressure * Decimal("0.5")),
        check("gas_first_step_hold_at_least_3_minutes", parsed[0][1] >= Decimal(3), parsed[0][1], 3),
        check("gas_last_step_reaches_test_pressure", abs(pressures[-1] - test_pressure) <= test_pressure * Decimal("0.001"), pressures[-1], test_pressure),
    ]
    for index, ((previous, _), (current, hold)) in enumerate(zip(parsed, parsed[1:]), 2):
        increment = (current - previous) / test_pressure
        checks.extend(
            [
                check(f"gas_step_{index}_increasing", current > previous, current, f">{previous}"),
                check(f"gas_step_{index}_increment_at_most_10_percent", increment <= Decimal("0.101"), increment, "<=0.10"),
                check(f"gas_step_{index}_hold_at_least_3_minutes", hold >= Decimal(3), hold, 3),
            ]
        )
    return checks


def check_pressure_test_report_consistency(arguments: dict[str, Any]) -> dict[str, Any]:
    report = arguments.get("report") if isinstance(arguments.get("report"), dict) else {}
    observed = arguments.get("observed") if isinstance(arguments.get("observed"), dict) else {}
    tolerance = decimal(arguments.get("tolerance")) or Decimal("0.001")
    required_fields = ("standardRef", "method", "testPressure", "holdMinutes", "testResult")
    if any(report.get(key) in {None, ""} for key in required_fields):
        return result(
            "check_pressure_test_report_consistency",
            "evidence_insufficient",
            facts={"report": report, "observed": observed},
            checks=[],
        )
    checks = [check("report_standard_present", bool(str(report.get("standardRef")).strip()), report.get("standardRef"), "required")]
    normalized_result = normalize_value(report.get("testResult"), "text")
    checks.append(
        check(
            "report_result_accepted",
            normalized_result in {"passed", "qualified", "合格", "无泄漏", "no_leak"},
            normalized_result,
            "accepted",
        )
    )
    for key in ("method", "testPressure", "holdMinutes", "testResult"):
        if observed.get(key) in {None, ""}:
            continue
        if key in {"testPressure", "holdMinutes"}:
            left, right = decimal(report.get(key)), decimal(observed.get(key))
            equal = left is not None and right is not None and abs(left - right) <= tolerance
        else:
            left, right = normalize_value(report.get(key), "text"), normalize_value(observed.get(key), "text")
            equal = left == right
        checks.append(check(f"report_{key}_matches", equal, left, right))
    return result(
        "check_pressure_test_report_consistency",
        "passed" if all(item["passed"] for item in checks) else "failed",
        facts={"report": report, "observed": observed, "tolerance": tolerance},
        checks=checks,
        rule_version="pressure-test-report-consistency-v1",
    )


def validate_evidence_grounding(arguments: dict[str, Any]) -> dict[str, Any]:
    facts = [item for item in arguments.get("facts") or [] if isinstance(item, dict)]
    refs = [item for item in arguments.get("evidenceRefs") or [] if isinstance(item, dict)]
    minimum = decimal(arguments.get("minConfidence")) or Decimal("0.75")
    ref_ids = {str(item.get("evidenceRefId") or item.get("id")) for item in refs if item.get("evidenceRefId") or item.get("id")}
    checks = []
    for index, fact in enumerate(facts, 1):
        fact_refs = {str(item) for item in fact.get("evidenceRefIds") or []}
        confidence = decimal(fact.get("confidence"))
        located = bool(fact_refs) and fact_refs <= ref_ids
        locator_complete = all(
            item.get("pageNo") is not None and (item.get("bbox") is not None or item.get("quotedText"))
            for item in refs
            if str(item.get("evidenceRefId") or item.get("id")) in fact_refs
        )
        checks.extend(
            [
                check(f"fact_{index}_references_exist", located, sorted(fact_refs), sorted(ref_ids)),
                check(f"fact_{index}_locator_complete", located and locator_complete, fact_refs, "page+bbox|quotedText"),
                check(f"fact_{index}_confidence", confidence is not None and confidence >= minimum, confidence, minimum),
                check(f"fact_{index}_not_conflicted", not bool(fact.get("conflicted")), fact.get("conflicted"), False),
            ]
        )
    status = "evidence_insufficient" if not facts or not refs or not all(item["passed"] for item in checks) else "passed"
    return result(
        "validate_evidence_grounding",
        status,
        facts={"factCount": len(facts), "evidenceRefCount": len(refs), "minConfidence": minimum},
        checks=checks,
        output_schema="evidence-gate-result-v1",
    )


def decode_welder_code(code: str) -> dict[str, Any]:
    normalized = normalize_roman(unicodedata.normalize("NFKC", code)).replace("—", "-").replace("－", "-")
    parts = normalized.split("-")
    if len(parts) < 4 or "/" not in parts[3]:
        return {"code": code, "parseStatus": "unsupported", "reason": "unrecognized_code_shape"}
    thickness_code, diameter_code = parts[3].split("/", 1)
    thickness_value = decimal(re.sub(r"[^0-9.]", "", thickness_code))
    diameter_value = decimal(re.sub(r"[^0-9.]", "", diameter_code))
    if thickness_value is None or thickness_value <= 0 or diameter_value is None or diameter_value <= 0:
        return {"code": code, "parseStatus": "unsupported", "reason": "coverage_code_not_in_profile"}
    thickness = (Decimal(0), thickness_value * 2 if thickness_value < 12 else None)
    diameter = (
        diameter_value
        if diameter_value < 25
        else Decimal(25)
        if diameter_value < 76
        else Decimal(76),
        None,
    )
    return {
        "code": code,
        "parseStatus": "parsed",
        "weldingMethod": parts[0].upper(),
        "materialCategory": parts[1].upper(),
        "position": parts[2].upper(),
        "thicknessMin": thickness[0],
        "thicknessMax": thickness[1],
        "diameterMin": diameter[0],
        "diameterMax": diameter[1],
        "fillerMetal": parts[4].upper() if len(parts) > 4 else None,
        "processFactors": [factor.upper() for item in parts[5:] for factor in item.split("/") if factor],
    }


def qualification_covers_work(qualification: dict[str, Any], work: dict[str, Any]) -> bool:
    qualification_certificate = normalize_value(qualification.get("certificateNo"), "text")
    work_certificate = normalize_value(work.get("welderCertificateNo") or work.get("certificateNo"), "text")
    if work_certificate and qualification_certificate and work_certificate != qualification_certificate:
        return False
    qualification_name = normalize_value(qualification.get("welderName"), "text")
    work_name = normalize_value(work.get("welderName"), "text")
    if work_name and qualification_name and work_name != qualification_name:
        return False
    if welding_method_code(qualification.get("weldingMethod")) != welding_method_code(work.get("weldingMethod")):
        return False
    qualified_material = normalize_roman(str(qualification.get("materialCategory") or "")).upper()
    actual_material = normalize_roman(str(work.get("materialCategory") or material_category_for_grade(work.get("materialGrade")) or "")).upper()
    material_coverage = {
        "FEI": {"FEI"},
        "FEII": {"FEI", "FEII"},
        "FEIII": {"FEI", "FEII", "FEIII"},
        "FEIV": {"FEIV"},
        "FEV": {"FEI", "FEII", "FEIII", "FEV"},
        "FEVI": {"FEI", "FEII", "FEIII", "FEV", "FEVI"},
    }
    if actual_material not in material_coverage.get(qualified_material, {qualified_material}):
        return False
    qualified_position = welding_position_code(qualification.get("position"))
    actual_position = welding_position_code(work.get("position"))
    covered_positions = {
        "1G": {"1G"},
        "2G": {"1G", "2G"},
        "3G": {"3G"},
        "4G": {"4G"},
        "5G": {"1G", "5G"},
        "6G": {"1G", "2G", "3G", "4G", "5G", "6G"},
    }.get(qualified_position, {qualified_position})
    if actual_position not in covered_positions:
        return False
    thickness = decimal(work.get("thickness"))
    diameter = decimal(work.get("diameter"))
    if thickness is None or diameter is None:
        return False
    if not within(thickness, decimal(qualification.get("thicknessMin")), decimal(qualification.get("thicknessMax"))):
        return False
    if not within(diameter, decimal(qualification.get("diameterMin")), decimal(qualification.get("diameterMax"))):
        return False
    actual_filler = normalize_value(work.get("fillerMetal"), "text")
    qualified_filler = normalize_value(qualification.get("fillerMetal"), "text")
    if actual_filler and qualified_filler and actual_filler != qualified_filler:
        return False
    actual_factors = {normalize_value(item, "text") for item in work.get("processFactors") or []}
    qualified_factors = {normalize_value(item, "text") for item in qualification.get("processFactors") or []}
    return not actual_factors or actual_factors <= qualified_factors


def material_category_for_grade(value: Any) -> str | None:
    grade = re.sub(r"[^A-Z0-9]", "", str(value or "").upper())
    if grade in {"20", "10", "Q235B", "Q235C", "Q235D", "Q245R"}:
        return "FeI"
    if grade in {"16MN", "Q345R", "Q345B", "Q345C", "Q345D", "L245", "L290", "L360"}:
        return "FeII"
    return None


def welding_method_code(value: Any) -> str:
    text = normalize_value(value, "text").upper()
    aliases = {
        "钨极氩弧焊": "GTAW", "氩弧焊": "GTAW", "TIG": "GTAW",
        "焊条电弧焊": "SMAW", "手工电弧焊": "SMAW",
        "熔化极气体保护焊": "GMAW", "气体保护焊": "GMAW", "MIG": "GMAW", "MAG": "GMAW",
        "药芯焊丝电弧焊": "FCAW", "埋弧焊": "SAW", "等离子弧焊": "PAW",
    }
    return aliases.get(text, re.sub(r"[^A-Z0-9]", "", text))


def welding_position_code(value: Any) -> str:
    text = normalize_value(value, "text").upper()
    aliases = {
        "平焊": "1G", "横焊": "2G", "立焊": "3G", "仰焊": "4G",
        "水平固定": "5G", "45°固定": "6G", "45度固定": "6G", "全位置": "6G",
    }
    return aliases.get(text, re.sub(r"[^A-Z0-9]", "", text))


def welder_rule_version(arguments: dict[str, Any]) -> tuple[str, str | None]:
    review_date = parse_date(arguments.get("reviewDate") or arguments.get("workDate")) or date.today()
    if review_date >= date(2026, 8, 1):
        version = "welder-qualification-tsg-z6002-2026-transition-v1"
        if arguments.get("ruleProfile2026Verified") is not True:
            return version, "tsg_z6002_2026_effective_profile_not_verified"
        return version, None
    return "welder-qualification-tsg-z6002-2010-v2", None


def within(value: Decimal, minimum: Decimal | None, maximum: Decimal | None) -> bool:
    return (minimum is None or value >= minimum) and (maximum is None or value <= maximum)


def normalize_value(value: Any, mode: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip().lower()
    if mode == "organization_name":
        return re.sub(r"[\s·,，。()（）\-]", "", text)
    return re.sub(r"\s+", " ", text)


def normalize_grade(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def normalize_roman(value: str) -> str:
    return value.translate(str.maketrans({"Ⅰ": "I", "Ⅱ": "II", "Ⅲ": "III", "Ⅳ": "IV", "Ⅴ": "V", "Ⅵ": "VI"}))


def parse_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip().replace("年", "-").replace("月", "-").replace("日", "").replace(".", "-").replace("/", "-")
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def check(code: str, passed: bool, actual: Any, expected: Any) -> dict[str, Any]:
    item = {"code": code, "passed": bool(passed), "actual": json_value(actual), "expected": json_value(expected)}
    # 业务口径：字段缺失（事实没抽到）不是「不符合」，而是「证据不足」。
    # expected == "present" 的检查项是存在性检查；未通过即为缺失，标记供聚合层区分。
    if not passed and expected == "present":
        item["missing"] = True
    return item


def result(
    tool_name: str,
    status: str,
    *,
    facts: dict[str, Any],
    checks: list[dict[str, Any]],
    rule_version: str = "common-deterministic-rules-v1",
    output_schema: str = RESULT_SCHEMA,
) -> dict[str, Any]:
    return {
        "toolName": tool_name,
        "toolVersion": "1.0.0",
        "outputSchema": output_schema,
        "status": "succeeded",
        "result": status,
        "ruleVersion": rule_version,
        "facts": json_value(facts),
        "checks": json_value(checks),
        "summary": {
            "checkCount": len(checks),
            "passedCount": sum(1 for item in checks if item.get("passed")),
            "failedCount": sum(1 for item in checks if not item.get("passed")),
        },
    }


def json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_value(item) for item in value]
    return value
