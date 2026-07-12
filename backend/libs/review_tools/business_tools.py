from __future__ import annotations

from decimal import Decimal
from typing import Any, Callable

from libs.review_orchestrator.deterministic_tools import (
    check,
    decimal,
    normalize_value,
    parse_date,
    result,
)


COMMON_TOOL_NAMES = (
    "check_required",
    "check_scope_coverage",
    "check_cross_document_match",
    "check_signature_completeness",
    "check_numeric_range",
    "check_conditional_requirement",
    "check_sampling_requirement",
    "check_document_set_completeness",
    "check_standard_version_active",
    "check_traceability",
)

DOMAIN_TOOL_NAMES = (
    "check_ndt_personnel_coverage",
    "check_wps_pqr_coverage",
    "evaluate_alternative_standard",
    "evaluate_blowing_cleaning",
    "evaluate_component_manufacturer_scope",
    "evaluate_construction_plan",
    "evaluate_corrosion_protection",
    "evaluate_design_approval_level",
    "evaluate_design_special_requirements",
    "evaluate_foreign_component",
    "evaluate_heat_treatment",
    "evaluate_heat_treatment_instruments",
    "evaluate_installation_license_scope",
    "evaluate_leak_test",
    "evaluate_material_component",
    "evaluate_ndt_nonconformance",
    "evaluate_ndt_organization_scope",
    "evaluate_ndt_process",
    "evaluate_ndt_quality_system",
    "evaluate_pipe_fit_up",
    "evaluate_pipeline_installation",
    "evaluate_pressure_test",
    "evaluate_rt_film",
    "evaluate_safety_accessory",
    "evaluate_stress_analysis",
    "evaluate_valve_test",
    "evaluate_weld_appearance",
    "evaluate_weld_repair",
    "evaluate_welding_consumable",
    "evaluate_welding_consumable_control",
    "evaluate_welding_process",
)


BUSINESS_TOOL_DESCRIPTORS: list[dict[str, Any]] = [
    {
        "name": name,
        "capability": "执行结构化、确定性业务规则；事实或规则参数不足时禁止判定符合。",
        "inputSchema": {
            "facts": "object?",
            "requiredFields": ["string?"],
            "ruleChecks": ["object?"],
            "profile": "string?",
            "applicable": "boolean?",
        },
        "outputSchema": "deterministic-tool-result-v1",
    }
    for name in (*COMMON_TOOL_NAMES, *DOMAIN_TOOL_NAMES)
]

BUSINESS_TOOL_NAMES = {item["name"] for item in BUSINESS_TOOL_DESCRIPTORS}


def dispatch_business_tool(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    handlers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
        "check_required": check_required,
        "check_scope_coverage": check_scope_coverage,
        "check_cross_document_match": check_cross_document_match,
        "check_signature_completeness": check_signature_completeness,
        "check_numeric_range": check_numeric_range,
        "check_conditional_requirement": check_conditional_requirement,
        "check_sampling_requirement": check_sampling_requirement,
        "check_document_set_completeness": check_document_set_completeness,
        "check_standard_version_active": check_standard_version_active,
        "check_traceability": check_traceability,
        "check_ndt_personnel_coverage": check_ndt_personnel_coverage,
        "check_wps_pqr_coverage": check_wps_pqr_coverage,
        "evaluate_installation_license_scope": evaluate_installation_license_scope,
        "evaluate_ndt_organization_scope": evaluate_ndt_organization_scope,
        "evaluate_design_approval_level": evaluate_design_approval_level,
        "evaluate_rt_film": evaluate_rt_film,
        "evaluate_pressure_test": evaluate_pressure_test,
        "evaluate_valve_test": evaluate_valve_test,
    }
    handler = handlers.get(tool_name)
    if handler:
        return handler(arguments)
    return evaluate_rule_profile(tool_name, arguments)


def check_required(arguments: dict[str, Any]) -> dict[str, Any]:
    facts = fact_container(arguments)
    required_fields = string_list(arguments.get("requiredFields"))
    if not required_fields:
        return insufficient("check_required", arguments, "requiredFields_not_configured")
    checks = [
        check(f"required_{safe_code(path)}", is_present(read_path(facts, path)), read_path(facts, path), "present")
        for path in required_fields
    ]
    return checked_result("check_required", facts, checks)


def check_scope_coverage(arguments: dict[str, Any]) -> dict[str, Any]:
    granted = normalized_set(arguments.get("grantedScopes") or arguments.get("actualScopes"))
    required = normalized_set(arguments.get("requiredScopes"))
    coverage_map = {
        normalize_value(key, "text"): normalized_set(value)
        for key, value in dict_value(arguments.get("coverageMap")).items()
    }
    if not granted or not required:
        return insufficient("check_scope_coverage", arguments, "scope_facts_missing")
    checks = []
    for scope in sorted(required):
        accepted = {scope} | coverage_map.get(scope, set())
        checks.append(check(f"scope_{safe_code(scope)}", bool(granted & accepted), sorted(granted), sorted(accepted)))
    return checked_result("check_scope_coverage", {"grantedScopes": sorted(granted), "requiredScopes": sorted(required)}, checks)


def check_cross_document_match(arguments: dict[str, Any]) -> dict[str, Any]:
    comparisons = list_of_dicts(arguments.get("comparisons"))
    if not comparisons:
        return insufficient("check_cross_document_match", arguments, "comparisons_missing")
    checks = []
    for index, item in enumerate(comparisons, 1):
        values = [value for value in item.get("values") or [] if value not in {None, ""}]
        mode = str(item.get("normalizer") or "text")
        tolerance = decimal(item.get("tolerance"))
        if len(values) < int(item.get("requiredCount") or 2):
            checks.append(check(f"comparison_{index}_has_values", False, len(values), item.get("requiredCount") or 2))
            continue
        if tolerance is not None:
            numbers = [decimal(value) for value in values]
            passed = all(value is not None for value in numbers) and max(numbers) - min(numbers) <= tolerance
            actual: Any = numbers
        else:
            actual = [normalize_value(value, mode) for value in values]
            passed = len(set(actual)) == 1
        checks.append(check(str(item.get("code") or f"comparison_{index}"), passed, actual, "all_equal"))
    return checked_result("check_cross_document_match", {"comparisons": comparisons}, checks)


def check_signature_completeness(arguments: dict[str, Any]) -> dict[str, Any]:
    actual = normalized_set(arguments.get("actualRoles") or arguments.get("signatureRoles"))
    required = normalized_set(arguments.get("requiredRoles"))
    if not required:
        return insufficient("check_signature_completeness", arguments, "required_signature_roles_missing")
    checks = [check(f"signature_{safe_code(role)}", role in actual, sorted(actual), role) for role in sorted(required)]
    return checked_result("check_signature_completeness", {"actualRoles": sorted(actual), "requiredRoles": sorted(required)}, checks)


def check_numeric_range(arguments: dict[str, Any]) -> dict[str, Any]:
    ranges = list_of_dicts(arguments.get("ranges") or arguments.get("checks"))
    if not ranges:
        return insufficient("check_numeric_range", arguments, "numeric_ranges_missing")
    checks = []
    for index, item in enumerate(ranges, 1):
        value = decimal(item.get("value"))
        minimum = decimal(item.get("min"))
        maximum = decimal(item.get("max"))
        if value is None or minimum is None and maximum is None:
            checks.append(check(str(item.get("code") or f"range_{index}"), False, value, "configured_range"))
            continue
        min_ok = minimum is None or (value >= minimum if item.get("includeMin", True) else value > minimum)
        max_ok = maximum is None or (value <= maximum if item.get("includeMax", True) else value < maximum)
        checks.append(check(str(item.get("code") or f"range_{index}"), min_ok and max_ok, value, {"min": minimum, "max": maximum}))
    return checked_result("check_numeric_range", {"ranges": ranges}, checks)


def check_conditional_requirement(arguments: dict[str, Any]) -> dict[str, Any]:
    if "condition" not in arguments:
        return insufficient("check_conditional_requirement", arguments, "condition_missing")
    condition = arguments.get("condition")
    if not isinstance(condition, bool):
        return insufficient("check_conditional_requirement", arguments, "condition_not_boolean")
    if not condition:
        return result("check_conditional_requirement", "not_applicable", facts=arguments, checks=[])
    facts = fact_container(arguments)
    required_fields = string_list(arguments.get("requiredFields"))
    if not required_fields:
        return insufficient("check_conditional_requirement", arguments, "conditional_required_fields_missing")
    checks = [check(f"required_{safe_code(path)}", is_present(read_path(facts, path)), read_path(facts, path), "present") for path in required_fields]
    return checked_result("check_conditional_requirement", facts, checks)


def check_sampling_requirement(arguments: dict[str, Any]) -> dict[str, Any]:
    population = integer(arguments.get("populationCount"))
    sampled = integer(arguments.get("sampledCount"))
    ratio = decimal(arguments.get("requiredRatio"))
    minimum = integer(arguments.get("minimumCount"))
    if population is None or sampled is None or population < 0 or sampled < 0 or ratio is None and minimum is None:
        return insufficient("check_sampling_requirement", arguments, "sampling_parameters_missing")
    required_by_ratio = ceiling(Decimal(population) * ratio) if ratio is not None else 0
    required_count = max(required_by_ratio, minimum or 0)
    checks = [
        check("sample_not_larger_than_population", sampled <= population, sampled, population),
        check("sample_count_satisfies_requirement", sampled >= required_count, sampled, required_count),
    ]
    if arguments.get("selectedIds") is not None:
        selected = string_list(arguments.get("selectedIds"))
        checks.append(check("selected_ids_match_sample_count", len(set(selected)) == sampled, len(set(selected)), sampled))
    return checked_result("check_sampling_requirement", {**arguments, "requiredCount": required_count}, checks)


def check_document_set_completeness(arguments: dict[str, Any]) -> dict[str, Any]:
    required = normalized_set(arguments.get("requiredDocumentTypes"))
    uploaded = normalized_set(arguments.get("uploadedDocumentTypes"))
    parseable = normalized_set(arguments.get("parseableDocumentTypes") or arguments.get("uploadedDocumentTypes"))
    if not required:
        return insufficient("check_document_set_completeness", arguments, "required_document_types_missing")
    checks = []
    for document_type in sorted(required):
        checks.append(check(f"uploaded_{safe_code(document_type)}", document_type in uploaded, sorted(uploaded), document_type))
        checks.append(check(f"parseable_{safe_code(document_type)}", document_type in parseable, sorted(parseable), document_type))
    return checked_result(
        "check_document_set_completeness",
        {"requiredDocumentTypes": sorted(required), "uploadedDocumentTypes": sorted(uploaded), "parseableDocumentTypes": sorted(parseable)},
        checks,
    )


def check_standard_version_active(arguments: dict[str, Any]) -> dict[str, Any]:
    references = list_of_dicts(arguments.get("standardReferences"))
    review_date = parse_date(arguments.get("reviewDate"))
    if not references or review_date is None:
        return insufficient("check_standard_version_active", arguments, "standard_version_facts_missing")
    checks = []
    for index, item in enumerate(references, 1):
        effective = parse_date(item.get("effectiveFrom"))
        withdrawn = parse_date(item.get("withdrawnOn"))
        status = normalize_value(item.get("status"), "text")
        active_status = status not in {"withdrawn", "废止", "obsolete", "replaced"}
        active_period = (effective is None or effective <= review_date) and (withdrawn is None or review_date < withdrawn)
        checks.append(check(str(item.get("standardRef") or f"standard_{index}"), active_status and active_period, item, review_date))
    return checked_result("check_standard_version_active", {"standardReferences": references, "reviewDate": review_date}, checks)


def check_traceability(arguments: dict[str, Any]) -> dict[str, Any]:
    items = list_of_dicts(arguments.get("items"))
    if not items:
        return insufficient("check_traceability", arguments, "traceability_items_missing")
    checks = []
    for index, item in enumerate(items, 1):
        original = item.get("originalMark")
        transferred = item.get("transferredMark")
        batch = item.get("batchNo")
        record = item.get("transferRecord") or item.get("record")
        checks.extend(
            [
                check(f"item_{index}_original_mark", is_present(original), original, "present"),
                check(f"item_{index}_transferred_mark", is_present(transferred), transferred, "present"),
                check(f"item_{index}_batch", is_present(batch), batch, "present"),
                check(f"item_{index}_record", is_present(record), record, "present"),
            ]
        )
        if isinstance(record, dict) and record.get("batchNo") is not None:
            checks.append(check(f"item_{index}_batch_matches", normalize_value(batch, "text") == normalize_value(record.get("batchNo"), "text"), batch, record.get("batchNo")))
    return checked_result("check_traceability", {"items": items}, checks)


def check_ndt_personnel_coverage(arguments: dict[str, Any]) -> dict[str, Any]:
    personnel = list_of_dicts(arguments.get("personnel"))
    work_items = list_of_dicts(arguments.get("workItems"))
    if not personnel or not work_items:
        return insufficient("check_ndt_personnel_coverage", arguments, "personnel_or_work_items_missing")
    checks = []
    for index, work in enumerate(work_items, 1):
        method = normalize_value(work.get("method"), "text")
        required_level = integer(work.get("requiredLevel")) or 1
        matched = [
            person
            for person in personnel
            if person_is_current(person, arguments.get("workDate"))
            and method in normalized_set(person.get("methods"))
            and (integer(person.get("level")) or 0) >= required_level
        ]
        checks.append(check(f"work_{index}_covered", bool(matched), [item.get("personId") for item in matched], {"method": method, "level": required_level}))
    return checked_result("check_ndt_personnel_coverage", {"personnel": personnel, "workItems": work_items}, checks)


def check_wps_pqr_coverage(arguments: dict[str, Any]) -> dict[str, Any]:
    pqr = list_of_dicts(arguments.get("qualifiedRanges") or arguments.get("pqrItems"))
    work_items = list_of_dicts(arguments.get("workItems"))
    if not pqr or not work_items:
        return insufficient("check_wps_pqr_coverage", arguments, "pqr_or_work_items_missing")
    checks = []
    for index, work in enumerate(work_items, 1):
        matched = [item for item in pqr if coverage_item_matches(item, work)]
        checks.append(check(f"work_{index}_covered", bool(matched), work, [item.get("id") for item in matched]))
    return checked_result("check_wps_pqr_coverage", {"qualifiedRanges": pqr, "workItems": work_items}, checks)


def evaluate_installation_license_scope(arguments: dict[str, Any]) -> dict[str, Any]:
    scopes = normalized_set(arguments.get("licenseScopes"))
    grades = normalized_set(arguments.get("requiredPipelineGrades"))
    if not scopes or not grades:
        return insufficient("evaluate_installation_license_scope", arguments, "license_scope_facts_missing")
    aliases = {"gc1": {"gc1"}, "gc2": {"gc1", "gc2", "gcd", "a级锅炉安装资质"}, "gcd": {"gcd", "a级锅炉安装资质"}}
    checks = [check(f"grade_{safe_code(grade)}", bool(scopes & aliases.get(grade, {grade})), sorted(scopes), sorted(aliases.get(grade, {grade}))) for grade in sorted(grades)]
    dates = date_coverage_checks(arguments)
    if dates is None:
        return insufficient("evaluate_installation_license_scope", arguments, "license_or_construction_dates_missing")
    return checked_result("evaluate_installation_license_scope", arguments, [*checks, *dates], "installation-license-scope-cn-v1")


def evaluate_ndt_organization_scope(arguments: dict[str, Any]) -> dict[str, Any]:
    license_name = arguments.get("licenseOrganizationName")
    plan_name = arguments.get("planOrganizationName")
    methods = normalized_set(arguments.get("licensedMethods"))
    required = normalized_set(arguments.get("requiredMethods"))
    if not license_name or not plan_name or not methods or not required:
        return insufficient("evaluate_ndt_organization_scope", arguments, "ndt_organization_facts_missing")
    checks = [
        check("organization_name_matches", normalize_value(license_name, "organization_name") == normalize_value(plan_name, "organization_name"), license_name, plan_name),
        *[check(f"method_{safe_code(method)}", method in methods, sorted(methods), method) for method in sorted(required)],
    ]
    dates = date_coverage_checks(arguments)
    if dates is None:
        return insufficient("evaluate_ndt_organization_scope", arguments, "license_or_construction_dates_missing")
    return checked_result("evaluate_ndt_organization_scope", arguments, [*checks, *dates], "ndt-organization-scope-cn-v1")


def evaluate_design_approval_level(arguments: dict[str, Any]) -> dict[str, Any]:
    documents = list_of_dicts(arguments.get("documents"))
    if not documents:
        return insufficient("evaluate_design_approval_level", arguments, "design_documents_missing")
    checks = []
    for index, document in enumerate(documents, 1):
        actual = normalized_set(document.get("signatureRoles"))
        required = normalized_set(document.get("requiredRoles") or arguments.get("requiredRoles"))
        if not required:
            return insufficient("evaluate_design_approval_level", arguments, "required_signature_roles_missing")
        for role in sorted(required):
            checks.append(check(f"document_{index}_{safe_code(role)}", role in actual, sorted(actual), role))
        if document.get("bodyUploaded") is not None:
            checks.append(check(f"document_{index}_body_uploaded", document.get("bodyUploaded") is True, document.get("bodyUploaded"), True))
    return checked_result("evaluate_design_approval_level", {"documents": documents}, checks)


def evaluate_rt_film(arguments: dict[str, Any]) -> dict[str, Any]:
    films = list_of_dicts(arguments.get("films"))
    report_weld_ids = set(string_list(arguments.get("reportWeldIds")))
    if not films:
        return insufficient("evaluate_rt_film", arguments, "film_inventory_missing")
    checks = []
    for index, film in enumerate(films, 1):
        weld_id = str(film.get("weldId") or "")
        checks.extend(
            [
                check(f"film_{index}_weld_id", bool(weld_id), weld_id, "present"),
                check(f"film_{index}_image_quality", film.get("imageQualityAccepted") is True, film.get("imageQualityAccepted"), True),
            ]
        )
        if report_weld_ids:
            checks.append(check(f"film_{index}_report_link", weld_id in report_weld_ids, weld_id, sorted(report_weld_ids)))
    sample_args = arguments.get("sampling")
    if isinstance(sample_args, dict):
        sample_result = check_sampling_requirement(sample_args)
        if sample_result.get("result") == "evidence_insufficient":
            return insufficient("evaluate_rt_film", arguments, "sampling_parameters_incomplete")
        checks.extend(sample_result.get("checks") or [])
    return checked_result("evaluate_rt_film", {"films": films, "reportWeldIds": sorted(report_weld_ids)}, checks)


def evaluate_pressure_test(arguments: dict[str, Any]) -> dict[str, Any]:
    required = ["timing", "medium", "pressurizationRate", "instrumentRequirements", "safetyMeasures", "acceptanceCriteria"]
    facts = fact_container(arguments)
    checks = [check(f"plan_{safe_code(path)}", is_present(read_path(facts, path)), read_path(facts, path), "present") for path in required]
    roles = normalized_set(arguments.get("signatureRoles") or facts.get("signatureRoles"))
    required_roles = normalized_set(arguments.get("requiredRoles"))
    if not required_roles:
        return insufficient("evaluate_pressure_test", arguments, "pressure_plan_required_roles_missing")
    checks.extend(check(f"signature_{safe_code(role)}", role in roles, sorted(roles), role) for role in sorted(required_roles))
    return checked_result("evaluate_pressure_test", arguments, checks)


def evaluate_valve_test(arguments: dict[str, Any]) -> dict[str, Any]:
    grade = normalize_value(arguments.get("pipelineGrade"), "text")
    population = integer(arguments.get("lotSize"))
    tested = integer(arguments.get("testedCount"))
    if not grade or population is None or tested is None:
        return insufficient("evaluate_valve_test", arguments, "valve_sampling_facts_missing")
    if arguments.get("factoryWitnessExemption") is True:
        exemption_checks = [
            check("factory_test_each_valve", arguments.get("factoryTestedEach") is True, arguments.get("factoryTestedEach"), True),
            check("owner_approved_exemption", arguments.get("ownerApprovedExemption") is True, arguments.get("ownerApprovedExemption"), True),
            check("factory_records_traceable", arguments.get("factoryRecordsTraceable") is True, arguments.get("factoryRecordsTraceable"), True),
        ]
        return checked_result("evaluate_valve_test", arguments, exemption_checks, "valve-test-gbt20801-v1")
    ratios = {"gc1": Decimal("1"), "gc2": Decimal("0.10"), "gc3": Decimal("0.05")}
    ratio = ratios.get(grade)
    if ratio is None:
        return insufficient("evaluate_valve_test", arguments, "unsupported_pipeline_grade")
    sampling = check_sampling_requirement({"populationCount": population, "sampledCount": tested, "requiredRatio": ratio, "minimumCount": 1})
    checks = list(sampling.get("checks") or [])
    required_records = ["testProcedure", "testPressure", "holdMinutes", "testResult", "standardRef"]
    checks.extend(check(f"valve_{safe_code(path)}", is_present(arguments.get(path)), arguments.get(path), "present") for path in required_records)
    accepted = normalize_value(arguments.get("testResult"), "text") in {"passed", "qualified", "合格", "无泄漏", "no_leak"}
    checks.append(check("valve_test_result_accepted", accepted, arguments.get("testResult"), "accepted"))
    return checked_result("evaluate_valve_test", arguments, checks, "valve-test-gbt20801-v1")


def evaluate_rule_profile(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if arguments.get("applicable") is False:
        return result(tool_name, "not_applicable", facts=arguments, checks=[], rule_version=rule_version(arguments))
    if arguments.get("applicable") not in {None, True, False}:
        return insufficient(tool_name, arguments, "applicability_not_boolean")
    facts = fact_container(arguments)
    required_fields = string_list(arguments.get("requiredFields"))
    rule_checks = list_of_dicts(arguments.get("ruleChecks"))
    if not required_fields:
        return insufficient(tool_name, arguments, "requiredFields_not_configured")
    if not rule_checks:
        return insufficient(tool_name, arguments, "ruleChecks_not_configured")
    checks = [check(f"required_{safe_code(path)}", is_present(read_path(facts, path)), read_path(facts, path), "present") for path in required_fields]
    for index, spec in enumerate(rule_checks, 1):
        evaluated = evaluate_rule_check(spec)
        if evaluated is None:
            return insufficient(tool_name, arguments, f"unsupported_rule_check_{index}")
        checks.append(evaluated)
    return checked_result(tool_name, facts, checks, rule_version(arguments))


def evaluate_rule_check(spec: dict[str, Any]) -> dict[str, Any] | None:
    operator = str(spec.get("operator") or "").strip()
    actual = spec.get("actual")
    expected = spec.get("expected")
    if operator == "present":
        passed = is_present(actual)
    elif operator == "equals":
        passed = normalize_value(actual, str(spec.get("normalizer") or "text")) == normalize_value(expected, str(spec.get("normalizer") or "text"))
    elif operator in {"gte", "lte", "gt", "lt"}:
        left, right = decimal(actual), decimal(expected)
        if left is None or right is None:
            passed = False
        else:
            passed = {"gte": left >= right, "lte": left <= right, "gt": left > right, "lt": left < right}[operator]
    elif operator == "contains_all":
        passed = normalized_set(actual) >= normalized_set(expected)
    elif operator == "accepted":
        passed = normalize_value(actual, "text") in normalized_set(expected or ["passed", "qualified", "合格"])
    else:
        return None
    return check(str(spec.get("code") or "rule_check"), passed, actual, expected)


def checked_result(tool_name: str, facts: Any, checks: list[dict[str, Any]], version: str | None = None) -> dict[str, Any]:
    if not checks:
        return insufficient(tool_name, facts, "checks_empty")
    return result(tool_name, "passed" if all(item.get("passed") for item in checks) else "failed", facts={"input": facts}, checks=checks, rule_version=version or rule_version(dict_value(facts)))


def insufficient(tool_name: str, arguments: Any, reason: str) -> dict[str, Any]:
    output = result(tool_name, "evidence_insufficient", facts={"input": arguments, "reason": reason}, checks=[], rule_version=rule_version(dict_value(arguments)))
    output["warnings"] = [reason]
    return output


def rule_version(arguments: dict[str, Any]) -> str:
    return str(arguments.get("ruleVersion") or arguments.get("profile") or "business-rule-profile-v1")


def fact_container(arguments: dict[str, Any]) -> dict[str, Any]:
    return arguments.get("facts") if isinstance(arguments.get("facts"), dict) else arguments


def read_path(value: dict[str, Any], path: str) -> Any:
    current: Any = value
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def is_present(value: Any) -> bool:
    if value is None or value == "":
        return False
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def string_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple, set)):
        return []
    return [str(item) for item in value if item not in {None, ""}]


def list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def normalized_set(value: Any) -> set[str]:
    values = value if isinstance(value, (list, tuple, set)) else []
    return {normalize_value(item, "text") for item in values if item not in {None, ""}}


def integer(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def ceiling(value: Decimal) -> int:
    return int(value.to_integral_value(rounding="ROUND_CEILING"))


def safe_code(value: Any) -> str:
    text = normalize_value(value, "text")
    return "".join(character if character.isalnum() else "_" for character in text).strip("_") or "item"


def date_coverage_checks(arguments: dict[str, Any]) -> list[dict[str, Any]] | None:
    valid_from = parse_date(arguments.get("validFrom"))
    valid_until = parse_date(arguments.get("validUntil"))
    period_start = parse_date(arguments.get("periodStart"))
    planned_end = parse_date(arguments.get("plannedPeriodEnd") or arguments.get("periodEnd"))
    actual_end = parse_date(arguments.get("actualPeriodEnd"))
    if valid_until is None or period_start is None or planned_end is None:
        return None
    period_end = max(item for item in (planned_end, actual_end) if item is not None)
    return [
        check("valid_from_covers_period_start", valid_from is None or valid_from <= period_start, valid_from, period_start),
        check("valid_until_covers_later_construction_end", valid_until >= period_end, valid_until, period_end),
    ]


def person_is_current(person: dict[str, Any], work_date: Any) -> bool:
    date = parse_date(work_date)
    valid_until = parse_date(person.get("validUntil"))
    registered = person.get("registered")
    return date is not None and valid_until is not None and valid_until >= date and registered is True


def coverage_item_matches(qualification: dict[str, Any], work: dict[str, Any]) -> bool:
    for field in ("method", "materialCategory", "position", "fillerMetal"):
        expected = work.get(field)
        if expected not in {None, ""} and normalize_value(qualification.get(field), "text") != normalize_value(expected, "text"):
            return False
    thickness = decimal(work.get("thickness"))
    diameter = decimal(work.get("diameter"))
    if thickness is None or diameter is None:
        return False
    thickness_min, thickness_max = decimal(qualification.get("thicknessMin")), decimal(qualification.get("thicknessMax"))
    diameter_min, diameter_max = decimal(qualification.get("diameterMin")), decimal(qualification.get("diameterMax"))
    if None in {thickness_min, thickness_max, diameter_min}:
        return False
    return thickness_min <= thickness <= thickness_max and diameter >= diameter_min and (diameter_max is None or diameter <= diameter_max)
