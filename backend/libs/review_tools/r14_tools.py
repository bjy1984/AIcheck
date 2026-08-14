from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from libs.review_orchestrator.deterministic_tools import check, decimal, normalize_value, result
from libs.review_tools.r13_tools import classify_r13_component_requirements

R14_RULE_VERSION = "r14-component-factory-inspection-tsg-d7006-2020-v1"

_ACCEPTED_CONCLUSIONS = {
    "accepted",
    "approved",
    "compliant",
    "qualified",
    "passed",
    "符合",
    "合格",
    "通过",
}
_NON_LICENSED_COMPONENT_MARKERS = (
    "螺栓",
    "螺母",
    "垫圈",
    "垫片",
    "紧固件",
    "密封件",
)
_INSPECTION_ALIASES = {
    "spectral_analysis": ("spectral", "spectrum", "pmi", "光谱", "材质鉴别"),
    "hardness_test": ("hardness", "硬度"),
    "metallographic_test": ("metallograph", "metallographic", "金相"),
    "nondestructive_testing": ("nondestructive", "ndt", "无损", "射线", "超声", "磁粉", "渗透"),
    "pressure_test": ("pressuretest", "hydrostatic", "hydraulic", "耐压", "液压", "水压", "气压"),
}


def classify_r14_component_applicability(arguments: dict[str, Any]) -> dict[str, Any]:
    design_items = _list_of_dicts(arguments.get("designItems"))
    if not design_items:
        return _insufficient("classify_r14_component_applicability", arguments, "r14_design_items_missing")
    matrix = [_classify_item(item, index) for index, item in enumerate(design_items, 1)]
    checks = [
        check(
            f"component_{index}_r14_applicability_known",
            item["applicabilityKnown"],
            item.get("reasonCodes"),
            "manufacturing_license_supervision_and_type_test_requirements_known",
        )
        for index, item in enumerate(matrix, 1)
    ]
    business_result = "evidence_insufficient" if any(not item["applicabilityKnown"] for item in matrix) else "passed"
    output = result(
        "classify_r14_component_applicability",
        business_result,
        facts={"designItemCount": len(design_items), "applicabilityMatrix": matrix},
        checks=checks,
        rule_version=_rule_version(arguments),
    )
    output["applicabilityMatrix"] = matrix
    if business_result == "evidence_insufficient":
        output["warnings"] = ["one_or_more_r14_component_applicability_unknown"]
    return output


def evaluate_r14_component_design_match(arguments: dict[str, Any]) -> dict[str, Any]:
    design_items = _list_of_dicts(arguments.get("designItems"))
    reports = _list_of_dicts(arguments.get("factoryInspectionReports"))
    if not design_items:
        return _insufficient("evaluate_r14_component_design_match", arguments, "r14_design_items_missing")

    checks: list[dict[str, Any]] = []
    component_results: list[dict[str, Any]] = []
    failed = False
    incomplete = False
    applicable_count = 0
    for index, item in enumerate(design_items, 1):
        classification = _classify_item(item, index)
        if not classification["applicabilityKnown"]:
            incomplete = True
            component_results.append({**classification, "result": "evidence_insufficient"})
            checks.append(check(f"component_{index}_r14_applicability", False, classification["reasonCodes"], "known"))
            continue
        if not classification["r14Applicable"]:
            component_results.append({**classification, "result": "not_applicable"})
            continue
        applicable_count += 1
        matched, ambiguous = _best_matching_records(item, reports)
        if ambiguous:
            incomplete = True
            component_results.append(
                {**classification, "result": "evidence_insufficient", "reasonCodes": ["factory_report_match_ambiguous"]}
            )
            checks.append(check(f"component_{index}_factory_report_unique", False, len(matched), 1))
            continue
        if not matched:
            failed = True
            component_results.append(
                {**classification, "result": "failed", "reasonCodes": ["factory_inspection_report_missing"]}
            )
            checks.append(check(f"component_{index}_factory_report_present", False, None, "matching_report"))
            continue

        report = matched[0]
        report_failed = False
        report_incomplete = False
        for field, aliases in (
            ("grade", ("grade", "componentGrade", "strengthGrade")),
            ("material", ("material", "materialGrade")),
        ):
            expected = _first(item, *aliases)
            actual = _first(report, *aliases)
            if not _present(expected) or not _present(actual):
                report_incomplete = True
                checks.append(
                    check(
                        f"component_{index}_{field}_comparable",
                        False,
                        {"design": expected, "report": actual},
                        "both_values_present",
                    )
                )
                continue
            matches = _same_business_value(expected, actual)
            report_failed = report_failed or not matches
            checks.append(check(f"component_{index}_{field}_match", matches, actual, expected))

        conclusion = _first(report, "conclusion", "inspectionConclusion", "result")
        if not _present(conclusion):
            report_incomplete = True
            checks.append(check(f"component_{index}_factory_report_conclusion_present", False, conclusion, "present"))
        else:
            accepted = _accepted(conclusion)
            report_failed = report_failed or not accepted
            checks.append(check(f"component_{index}_factory_report_conclusion", accepted, conclusion, "accepted"))

        failed = failed or report_failed
        incomplete = incomplete or report_incomplete
        component_results.append(
            {
                **classification,
                "matchedReportId": _record_id(report),
                "result": "failed" if report_failed else "evidence_insufficient" if report_incomplete else "passed",
                "reasonCodes": (
                    ["factory_report_design_mismatch"]
                    if report_failed
                    else ["factory_report_comparison_fields_missing"]
                    if report_incomplete
                    else []
                ),
            }
        )

    business_result = _aggregate_result(failed, incomplete, applicable_count)
    output = result(
        "evaluate_r14_component_design_match",
        business_result,
        facts={
            "designItemCount": len(design_items),
            "factoryInspectionReportCount": len(reports),
            "applicableItemCount": applicable_count,
            "componentResults": component_results,
        },
        checks=checks,
        rule_version=_rule_version(arguments),
    )
    output["componentResults"] = component_results
    return output


def resolve_r14_required_inspection_items(arguments: dict[str, Any]) -> dict[str, Any]:
    design_items = _list_of_dicts(arguments.get("designItems"))
    if not design_items:
        return _insufficient("resolve_r14_required_inspection_items", arguments, "r14_design_items_missing")
    rules = _inspection_rules(arguments.get("productInspectionRules"))
    matrix: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    incomplete = False
    applicable_count = 0
    for index, item in enumerate(design_items, 1):
        classification = _classify_item(item, index)
        if not classification["applicabilityKnown"]:
            incomplete = True
            matrix.append({**classification, "requiredItemsKnown": False, "requiredInspectionItems": []})
            checks.append(check(f"component_{index}_r14_applicability", False, classification["reasonCodes"], "known"))
            continue
        if not classification["r14Applicable"]:
            matrix.append({**classification, "requiredItemsKnown": True, "requiredInspectionItems": []})
            continue
        applicable_count += 1
        required_items, source = _required_inspections(item, rules)
        known = required_items is not None
        incomplete = incomplete or not known
        matrix.append(
            {
                **classification,
                "requiredItemsKnown": known,
                "requiredInspectionItems": sorted(required_items or []),
                "requirementSource": source,
            }
        )
        checks.append(
            check(
                f"component_{index}_required_inspection_items_known",
                known,
                source,
                "design_requirement_or_frozen_product_standard_rule",
            )
        )
    business_result = "evidence_insufficient" if incomplete else "not_applicable" if applicable_count == 0 else "passed"
    output = result(
        "resolve_r14_required_inspection_items",
        business_result,
        facts={"inspectionRequirementMatrix": matrix},
        checks=checks,
        rule_version=_rule_version(arguments),
    )
    output["inspectionRequirementMatrix"] = matrix
    return output


def evaluate_r14_special_report_coverage(arguments: dict[str, Any]) -> dict[str, Any]:
    design_items = _list_of_dicts(arguments.get("designItems"))
    reports = _list_of_dicts(arguments.get("specialInspectionReports"))
    if not design_items:
        return _insufficient("evaluate_r14_special_report_coverage", arguments, "r14_design_items_missing")
    rules = _inspection_rules(arguments.get("productInspectionRules"))
    checks: list[dict[str, Any]] = []
    coverage_matrix: list[dict[str, Any]] = []
    failed = False
    incomplete = False
    applicable_count = 0
    for index, item in enumerate(design_items, 1):
        classification = _classify_item(item, index)
        if not classification["applicabilityKnown"]:
            incomplete = True
            coverage_matrix.append({**classification, "result": "evidence_insufficient"})
            continue
        if not classification["r14Applicable"]:
            coverage_matrix.append({**classification, "result": "not_applicable"})
            continue
        applicable_count += 1
        required_items, source = _required_inspections(item, rules)
        if required_items is None:
            incomplete = True
            coverage_matrix.append(
                {
                    **classification,
                    "result": "evidence_insufficient",
                    "reasonCodes": ["required_inspection_items_unknown"],
                    "requirementSource": source,
                }
            )
            checks.append(check(f"component_{index}_required_inspection_items_known", False, source, "configured"))
            continue

        matching_reports, ambiguous = _best_matching_records(item, reports, allow_multiple=True)
        if ambiguous:
            incomplete = True
            coverage_matrix.append(
                {**classification, "result": "evidence_insufficient", "reasonCodes": ["special_report_link_ambiguous"]}
            )
            continue
        component_failed = False
        component_incomplete = False
        matched_ids: list[str] = []
        for inspection_type in sorted(required_items):
            typed = [report for report in matching_reports if inspection_type in _report_inspection_types(report)]
            if not typed:
                component_failed = True
                checks.append(check(f"component_{index}_{inspection_type}_report_present", False, None, "matching_report"))
                continue
            accepted_report = False
            unresolved_report = False
            for report in typed:
                matched_ids.append(_record_id(report))
                conclusion = _first(report, "conclusion", "testConclusion", "inspectionConclusion", "result")
                if not _present(conclusion):
                    unresolved_report = True
                elif _accepted(conclusion):
                    accepted_report = True
            component_failed = component_failed or not accepted_report and not unresolved_report
            component_incomplete = component_incomplete or not accepted_report and unresolved_report
            checks.append(
                check(
                    f"component_{index}_{inspection_type}_report_accepted",
                    accepted_report,
                    [_first(report, "conclusion", "result") for report in typed],
                    "accepted",
                )
            )

        # Any submitted special report linked to the component must not contain an explicit failed conclusion.
        for report in matching_reports:
            conclusion = _first(report, "conclusion", "testConclusion", "inspectionConclusion", "result")
            if _present(conclusion) and not _accepted(conclusion):
                component_failed = True
                checks.append(
                    check(
                        f"component_{index}_submitted_report_{_safe_code(_record_id(report))}_conclusion",
                        False,
                        conclusion,
                        "accepted",
                    )
                )

        failed = failed or component_failed
        incomplete = incomplete or component_incomplete
        coverage_matrix.append(
            {
                **classification,
                "requiredInspectionItems": sorted(required_items),
                "matchedReportIds": sorted(set(matched_ids)),
                "result": "failed" if component_failed else "evidence_insufficient" if component_incomplete else "passed",
                "requirementSource": source,
            }
        )

    business_result = _aggregate_result(failed, incomplete, applicable_count)
    output = result(
        "evaluate_r14_special_report_coverage",
        business_result,
        facts={"specialInspectionReportCount": len(reports), "coverageMatrix": coverage_matrix},
        checks=checks,
        rule_version=_rule_version(arguments),
    )
    output["coverageMatrix"] = coverage_matrix
    return output


def evaluate_r14_pressure_compatibility(arguments: dict[str, Any]) -> dict[str, Any]:
    design_items = _list_of_dicts(arguments.get("designItems"))
    pipeline_rows = _list_of_dicts(arguments.get("pipelineCharacteristics"))
    factory_reports = _list_of_dicts(arguments.get("factoryInspectionReports"))
    special_reports = _list_of_dicts(arguments.get("specialInspectionReports"))
    if not design_items:
        return _insufficient("evaluate_r14_pressure_compatibility", arguments, "r14_design_items_missing")

    checks: list[dict[str, Any]] = []
    pressure_matrix: list[dict[str, Any]] = []
    failed = False
    incomplete = False
    applicable_count = 0
    for index, item in enumerate(design_items, 1):
        classification = _classify_item(item, index)
        if not classification["applicabilityKnown"]:
            incomplete = True
            pressure_matrix.append({**classification, "result": "evidence_insufficient"})
            continue
        if not classification["r14Applicable"]:
            pressure_matrix.append({**classification, "result": "not_applicable"})
            continue
        applicable_count += 1
        pipeline_matches = _matching_pipeline_rows(item, pipeline_rows)
        factory_matches, factory_ambiguous = _best_matching_records(item, factory_reports)
        component_failed = False
        component_incomplete = False
        reasons: list[str] = []
        if len(pipeline_matches) != 1:
            component_incomplete = True
            reasons.append("pipeline_characteristic_match_missing" if not pipeline_matches else "pipeline_characteristic_match_ambiguous")
            checks.append(check(f"component_{index}_pipeline_characteristic_unique", False, len(pipeline_matches), 1))
            pipeline = {}
        else:
            pipeline = pipeline_matches[0]

        required_pressure = _first(pipeline, "pressureClass", "designPressureMPa", "nominalPressureMPa")
        design_pressure = _first(item, "pressureClass", "nominalPressureMPa", "ratedPressureClass")
        if not _present(required_pressure) or not _present(design_pressure):
            component_incomplete = True
            reasons.append("design_or_pipeline_pressure_missing")
            checks.append(
                check(
                    f"component_{index}_design_pressure_comparable",
                    False,
                    {"pipeline": required_pressure, "materialTable": design_pressure},
                    "both_values_present",
                )
            )
        else:
            covered = _pressure_covers(design_pressure, required_pressure)
            if covered is None:
                component_incomplete = True
                reasons.append("pressure_class_conversion_unsupported")
            elif not covered:
                component_failed = True
                reasons.append("material_table_pressure_not_covering_pipeline")
            checks.append(check(f"component_{index}_material_pressure_covers_pipeline", covered is True, design_pressure, required_pressure))

        if factory_ambiguous:
            component_incomplete = True
            reasons.append("factory_report_match_ambiguous")
        elif not factory_matches:
            component_failed = True
            reasons.append("factory_inspection_report_missing")
        else:
            report = factory_matches[0]
            report_pressure = _first(report, "pressureClass", "nominalPressureMPa", "ratedPressureClass")
            if not _present(required_pressure) or not _present(report_pressure):
                component_incomplete = True
                reasons.append("factory_report_pressure_missing")
                checks.append(check(f"component_{index}_factory_report_pressure_present", False, report_pressure, "present"))
            else:
                covered = _pressure_covers(report_pressure, required_pressure)
                if covered is None:
                    component_incomplete = True
                    reasons.append("factory_report_pressure_conversion_unsupported")
                elif not covered:
                    component_failed = True
                    reasons.append("factory_report_pressure_not_covering_pipeline")
                checks.append(check(f"component_{index}_factory_pressure_covers_pipeline", covered is True, report_pressure, required_pressure))

        linked_special, special_ambiguous = _best_matching_records(item, special_reports, allow_multiple=True)
        if special_ambiguous:
            component_incomplete = True
            reasons.append("special_report_link_ambiguous")
        for report in linked_special:
            report_pressure = _first(report, "pressureClass", "nominalPressureMPa")
            if _present(report_pressure) and _present(required_pressure):
                covered = _pressure_covers(report_pressure, required_pressure)
                if covered is None:
                    component_incomplete = True
                    reasons.append("special_report_pressure_conversion_unsupported")
                elif not covered:
                    component_failed = True
                    reasons.append("special_report_pressure_not_covering_pipeline")
                checks.append(
                    check(
                        f"component_{index}_special_report_{_safe_code(_record_id(report))}_pressure",
                        covered is True,
                        report_pressure,
                        required_pressure,
                    )
                )
            if "pressure_test" not in _report_inspection_types(report):
                continue
            minimum_test_pressure = _first(item, "minimumTestPressureMPa") or _first(pipeline, "minimumTestPressureMPa")
            actual_test_pressure = _first(report, "testPressureMPa", "actualTestPressureMPa")
            if _present(minimum_test_pressure):
                actual = decimal(actual_test_pressure)
                minimum = decimal(minimum_test_pressure)
                if actual is None or minimum is None:
                    component_incomplete = True
                    reasons.append("pressure_test_value_missing")
                elif actual < minimum:
                    component_failed = True
                    reasons.append("pressure_test_value_below_minimum")
                checks.append(
                    check(
                        f"component_{index}_pressure_test_minimum",
                        actual is not None and minimum is not None and actual >= minimum,
                        actual_test_pressure,
                        minimum_test_pressure,
                    )
                )

        failed = failed or component_failed
        incomplete = incomplete or component_incomplete
        pressure_matrix.append(
            {
                **classification,
                "pipelineCharacteristicId": _record_id(pipeline) if pipeline else None,
                "requiredPressure": required_pressure,
                "designPressureClass": design_pressure,
                "result": "failed" if component_failed else "evidence_insufficient" if component_incomplete else "passed",
                "reasonCodes": sorted(set(reasons)),
            }
        )

    business_result = _aggregate_result(failed, incomplete, applicable_count)
    output = result(
        "evaluate_r14_pressure_compatibility",
        business_result,
        facts={"pressureCompatibilityMatrix": pressure_matrix},
        checks=checks,
        rule_version=_rule_version(arguments),
    )
    output["pressureCompatibilityMatrix"] = pressure_matrix
    return output


def _classify_item(item: dict[str, Any], index: int) -> dict[str, Any]:
    explicit_license = _boolean(_first(item, "requiresManufacturingLicense", "manufacturingLicenseRequired"))
    component_type = str(_first(item, "componentType", "productName") or "").strip()
    if explicit_license is None and any(marker in component_type for marker in _NON_LICENSED_COMPONENT_MARKERS):
        explicit_license = False
    r13 = classify_r13_component_requirements({"designItems": [item]})
    requirement_matrix = r13.get("requirementMatrix") if isinstance(r13.get("requirementMatrix"), list) else []
    r13_item = requirement_matrix[0] if requirement_matrix else {}
    supervision_known = r13_item.get("supervisionRequirementKnown") is True
    type_test_known = r13_item.get("typeTestRequirementKnown") is True
    known = explicit_license is not None and supervision_known and type_test_known
    requires_supervision = r13_item.get("requiresManufacturingSupervision") is True
    requires_type_test = r13_item.get("requiresTypeTest") is True
    applicable = known and not explicit_license and not requires_supervision and not requires_type_test
    reasons: list[str] = []
    if explicit_license is None:
        reasons.append("manufacturing_license_requirement_unknown")
    if not supervision_known:
        reasons.append("manufacturing_supervision_requirement_unknown")
    if not type_test_known:
        reasons.append("type_test_requirement_unknown")
    if explicit_license is True:
        reasons.append("route_to_r12")
    if requires_supervision or requires_type_test:
        reasons.append("route_to_r13")
    return {
        "componentItemId": str(item.get("componentItemId") or f"R14-ITEM-{index}"),
        "componentType": component_type,
        "applicabilityKnown": known,
        "r14Applicable": applicable,
        "requiresManufacturingLicense": explicit_license,
        "requiresManufacturingSupervision": r13_item.get("requiresManufacturingSupervision"),
        "requiresTypeTest": r13_item.get("requiresTypeTest"),
        "reasonCodes": reasons,
    }


def _required_inspections(
    item: dict[str, Any],
    rules: dict[str, set[str]],
) -> tuple[set[str] | None, str]:
    explicit = _inspection_values(
        _first(item, "requiredInspectionItems", "specialInspectionItems", "inspectionRequirements")
    )
    if explicit:
        return explicit, "design_requirement"
    requirements = item.get("inspectionRequirements")
    if isinstance(requirements, dict):
        selected = {_normalize_inspection_type(key) for key, value in requirements.items() if _boolean(value) is True}
        selected.discard(None)
        if selected or requirements:
            return {str(value) for value in selected}, "design_requirement"
    if _boolean(item.get("specialInspectionRequired")) is False:
        return set(), "design_explicit_not_required"
    standard = _normalize_standard(_first(item, "standardRef", "standardNo", "productStandard"))
    if standard and standard in rules:
        return set(rules[standard]), f"frozen_product_standard_rule:{standard}"
    return None, "product_standard_rule_missing"


def _inspection_rules(value: Any) -> dict[str, set[str]]:
    if not isinstance(value, dict):
        return {}
    output: dict[str, set[str]] = {}
    for key, rule in value.items():
        items = rule.get("requiredItems") if isinstance(rule, dict) else rule
        output[_normalize_standard(key)] = _inspection_values(items)
    return output


def _inspection_values(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        raw = [item for item in re.split(r"[,，、;；/\s]+", value) if item]
    elif isinstance(value, (list, tuple, set)):
        raw = list(value)
    else:
        raw = []
    output = {_normalize_inspection_type(item) for item in raw}
    output.discard(None)
    return {str(item) for item in output}


def _report_inspection_types(report: dict[str, Any]) -> set[str]:
    values: list[Any] = []
    for key in ("reportType", "inspectionType", "inspectionTypes", "testItems", "inspectionItems", "documentType"):
        value = report.get(key)
        if isinstance(value, (list, tuple, set)):
            values.extend(value)
        elif _present(value):
            values.append(value)
    output: set[str] = set()
    for value in values:
        normalized = _normalize_inspection_type(value)
        if normalized:
            output.add(normalized)
        compact = _compact(value)
        for inspection_type, aliases in _INSPECTION_ALIASES.items():
            if any(_compact(alias) in compact for alias in aliases):
                output.add(inspection_type)
    return output


def _normalize_inspection_type(value: Any) -> str | None:
    compact = _compact(value)
    if not compact:
        return None
    for inspection_type, aliases in _INSPECTION_ALIASES.items():
        if compact == _compact(inspection_type) or any(_compact(alias) in compact for alias in aliases):
            return inspection_type
    return None


def _best_matching_records(
    item: dict[str, Any],
    records: list[dict[str, Any]],
    *,
    allow_multiple: bool = False,
) -> tuple[list[dict[str, Any]], bool]:
    scored = [(record, _record_match_score(item, record)) for record in records]
    scored = [(record, score) for record, score in scored if score > 0]
    if not scored:
        return [], False
    highest = max(score for _, score in scored)
    matches = [record for record, score in scored if score == highest]
    if allow_multiple:
        threshold = max(3, highest - 1)
        return [record for record, score in scored if score >= threshold], False
    return matches, len(matches) != 1


def _record_match_score(item: dict[str, Any], record: dict[str, Any]) -> int:
    score = 0
    comparable = 0
    for aliases, weight in (
        (("lineNo", "pipelineId"), 5),
        (("batchNo", "lotNo", "heatNo"), 5),
        (("componentType", "productName"), 4),
        (("specification",), 3),
        (("material", "materialGrade"), 2),
    ):
        left = _first(item, *aliases)
        right = _first(record, *aliases)
        if not _present(left) or not _present(right):
            continue
        comparable += 1
        if _same_business_value(left, right):
            score += weight
        elif weight >= 4:
            return 0
    return score if comparable and score >= 3 else 0


def _matching_pipeline_rows(item: dict[str, Any], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    line_no = _first(item, "lineNo", "pipelineId")
    if _present(line_no):
        return [row for row in rows if _same_business_value(line_no, _first(row, "lineNo", "pipelineId"))]
    return rows if len(rows) == 1 else []


def _pressure_covers(actual: Any, required: Any) -> bool | None:
    actual_number = _pressure_mpa(actual)
    required_number = _pressure_mpa(required)
    if actual_number is not None and required_number is not None:
        return actual_number >= required_number
    actual_text = _compact(actual)
    required_text = _compact(required)
    if actual_text and required_text and actual_text == required_text:
        return True
    return None


def _pressure_mpa(value: Any) -> Decimal | None:
    number = decimal(value)
    text = str(value or "").strip()
    compact = text.upper().replace(" ", "")
    pn_match = re.search(r"\bPN\s*(\d+(?:\.\d+)?)\b", compact)
    if pn_match:
        pn = Decimal(pn_match.group(1))
        return pn / Decimal(10) if pn >= 10 else pn
    mpa_match = re.search(r"(-?\d+(?:\.\d+)?)\s*MPA", compact)
    if mpa_match:
        return Decimal(mpa_match.group(1))
    if compact.startswith("CLASS") or compact.startswith("CL"):
        return None
    return number


def _aggregate_result(failed: bool, incomplete: bool, applicable_count: int) -> str:
    if failed:
        return "failed"
    if incomplete:
        return "evidence_insufficient"
    if applicable_count == 0:
        return "not_applicable"
    return "passed"


def _accepted(value: Any) -> bool:
    normalized = normalize_value(value, "text")
    return normalized in {normalize_value(item, "text") for item in _ACCEPTED_CONCLUSIONS}


def _same_business_value(left: Any, right: Any) -> bool:
    left_value = normalize_value(left, "text")
    right_value = normalize_value(right, "text")
    return bool(left_value and right_value and (left_value == right_value or left_value in right_value or right_value in left_value))


def _first(value: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        candidate = value.get(key)
        if _present(candidate):
            return candidate
    return None


def _record_id(record: dict[str, Any]) -> str:
    return str(
        _first(record, "reportId", "recordId", "certificateId", "pipelineCharacteristicId", "documentVersionId")
        or "unknown"
    )


def _boolean(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    normalized = normalize_value(value, "text")
    if normalized in {"true", "yes", "required", "是", "需要", "适用", "1"}:
        return True
    if normalized in {"false", "no", "notrequired", "否", "不需要", "不适用", "0"}:
        return False
    return None


def _normalize_standard(value: Any) -> str:
    return re.sub(r"[^0-9A-Z]", "", str(value or "").upper())


def _compact(value: Any) -> str:
    return re.sub(r"[\s\W_]+", "", str(value or "").lower(), flags=re.UNICODE)


def _safe_code(value: Any) -> str:
    normalized = re.sub(r"[^0-9A-Za-z_]+", "_", str(value or "")).strip("_")
    return normalized or "item"


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _present(value: Any) -> bool:
    if value is None or value == "":
        return False
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def _rule_version(arguments: dict[str, Any]) -> str:
    return str(arguments.get("ruleVersion") or R14_RULE_VERSION)


def _insufficient(tool_name: str, arguments: dict[str, Any], reason: str) -> dict[str, Any]:
    output = result(
        tool_name,
        "evidence_insufficient",
        facts={"input": arguments, "reason": reason},
        checks=[],
        rule_version=_rule_version(arguments),
    )
    output["warnings"] = [reason]
    return output
