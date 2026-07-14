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
    "check_installation_license_scope",
    "check_wps_pqr_coverage",
    "decode_ndt_approval_item_codes",
    "evaluate_calculation_document_consistency",
    "evaluate_alternative_standard",
    "evaluate_blowing_cleaning",
    "evaluate_component_manufacturer_scope",
    "evaluate_construction_plan",
    "evaluate_corrosion_protection",
    "evaluate_design_approval_level",
    "evaluate_design_document_approval",
    "evaluate_design_change_approval",
    "evaluate_design_special_requirements",
    "evaluate_foreign_component",
    "evaluate_heat_treatment",
    "evaluate_heat_treatment_instruments",
    "evaluate_installation_license_scope",
    "evaluate_leak_test",
    "evaluate_material_component",
    "evaluate_ndt_nonconformance",
    "evaluate_ndt_organization_scope",
    "evaluate_ndt_agencies",
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
    "verify_design_license_seals",
)


BUSINESS_TOOL_CAPABILITIES = {
    "check_installation_license_scope": (
        "按照GC1、GC2、GCD和A级锅炉安装资质的固定覆盖关系，判断安装许可证是否覆盖项目管道等级。"
    ),
    "decode_ndt_approval_item_codes": (
        "按照TSG Z7002-2022附件A表A-1解码检测机构核准项目代码；未知代码返回证据不足。"
    ),
    "evaluate_ndt_agencies": (
        "按检测机构分别核验核准证与检测方案机构名称、核准项目代码的方法覆盖和施工计划工期有效期。"
    ),
    "evaluate_calculation_document_consistency": (
        "逐份核验强度计算书和管道应力计算书本体、覆盖管线及其与设计文件的结构化参数比较结果。"
    ),
    "evaluate_design_document_approval": (
        "逐份核验主要设计文件本体和签字角色，并根据文件覆盖的管道级别、设计压力和设计温度，"
        "确定执行三级或四级批准程序。"
    ),
    "evaluate_design_change_approval": (
        "逐份核验设计变更书面批准文件的原设计单位批准、文件本体及按受影响设计文件和管道条件确定的三级或四级签字。"
    ),
    "evaluate_design_special_requirements": (
        "核验设计说明是否对无损检测、防腐、耐压试验和泄漏试验规定了具体要求，并按冻结标准规则逐领域判断符合性。"
    ),
    "verify_design_license_seals": (
        "依据TSG 31-2025第3.1.2条，逐份核验重新出具的管道图纸目录和管道布置图上的压力管道设计许可印章。"
    ),
}


BUSINESS_TOOL_DESCRIPTORS: list[dict[str, Any]] = [
    {
        "name": name,
        "capability": BUSINESS_TOOL_CAPABILITIES.get(
            name,
            "执行结构化、确定性业务规则；事实或规则参数不足时禁止判定符合。",
        ),
        "inputSchema": (
            {
                "approvalMode": "three_level|four_level_conditional",
                "documents": ["object"],
                "pipelines": ["object"],
                "targetDocumentTypes": ["string"],
                "requiredRoles": ["string"],
                "ruleVersion": "string?",
            }
            if name == "evaluate_design_document_approval"
            else {
                "hasDesignChanges": "boolean",
                "documents": ["object"],
                "pipelines": ["object"],
                "ruleVersion": "string?",
            }
            if name == "evaluate_design_change_approval"
            else {
                "requirements": "object",
                "standardRules": "object",
                "requiredPathsByDomain": "object",
                "domains": ["ndt|corrosion|pressureTest|leakTest"],
                "ruleVersion": "string?",
            }
            if name == "evaluate_design_special_requirements"
            else {
                "hasDesignChanges": "boolean",
                "documents": ["object"],
                "requiredDocumentTypes": ["string"],
                "expectedSealName": "string",
                "ruleVersion": "string?",
            }
            if name == "verify_design_license_seals"
            else {
                "documents": ["object"],
                "targetDocumentTypes": ["string"],
                "ruleVersion": "string?",
            }
            if name == "evaluate_calculation_document_consistency"
            else {
                "agencies": ["object"],
                "evaluationMode": "identity|method_coverage|date_coverage",
                "failureAction": "string?",
                "ruleVersion": "string?",
            }
            if name == "evaluate_ndt_agencies"
            else {
                "approvalItemCodes": ["string"],
                "ruleVersion": "string?",
            }
            if name == "decode_ndt_approval_item_codes"
            else {
                "licenseScopes": ["string"],
                "requiredPipelineGrades": ["string"],
                "ruleVersion": "string?",
            }
            if name == "check_installation_license_scope"
            else {
                "facts": "object?",
                "requiredFields": ["string?"],
                "ruleChecks": ["object?"],
                "profile": "string?",
                "applicable": "boolean?",
            }
        ),
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
        "check_installation_license_scope": check_installation_license_scope,
        "check_wps_pqr_coverage": check_wps_pqr_coverage,
        "decode_ndt_approval_item_codes": decode_ndt_approval_item_codes,
        "evaluate_installation_license_scope": evaluate_installation_license_scope,
        "evaluate_ndt_organization_scope": evaluate_ndt_organization_scope,
        "evaluate_ndt_agencies": evaluate_ndt_agencies,
        "evaluate_design_approval_level": evaluate_design_approval_level,
        "evaluate_design_document_approval": evaluate_design_document_approval,
        "evaluate_design_change_approval": evaluate_design_change_approval,
        "evaluate_design_special_requirements": evaluate_design_special_requirements,
        "evaluate_calculation_document_consistency": evaluate_calculation_document_consistency,
        "evaluate_rt_film": evaluate_rt_film,
        "evaluate_pressure_test": evaluate_pressure_test,
        "evaluate_valve_test": evaluate_valve_test,
        "verify_design_license_seals": verify_design_license_seals,
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


def check_installation_license_scope(arguments: dict[str, Any]) -> dict[str, Any]:
    scopes = normalized_set(arguments.get("licenseScopes"))
    grades = normalized_set(arguments.get("requiredPipelineGrades"))
    if not scopes or not grades:
        return insufficient("check_installation_license_scope", arguments, "license_scope_facts_missing")
    coverage = {
        "gc1": {"gc1"},
        "gc2": {"gc1", "gc2", "gcd"},
        "gcd": {"gcd", "a级锅炉安装资质"},
    }
    checks = [
        check(
            f"grade_{safe_code(grade)}",
            bool(scopes & coverage.get(grade, {grade})),
            sorted(scopes),
            sorted(coverage.get(grade, {grade})),
        )
        for grade in sorted(grades)
    ]
    return checked_result(
        "check_installation_license_scope",
        {"licenseScopes": sorted(scopes), "requiredPipelineGrades": sorted(grades)},
        checks,
        "installation-license-scope-cn-v2",
    )


NDT_APPROVAL_CODE_METHODS: dict[str, set[str]] = {
    "CG": {"RT", "UT", "MT", "PT"},
    "ECT": {"ECT"},
    "AE": {"AE"},
    "TOFD": {"TOFD"},
    "PA": {"PA"},
    "MFL": {"MFL"},
    "TC": {"TC"},
    "FD1": {"FD1"},
    "FD2": {"FD2"},
}


def decode_ndt_approval_item_codes(arguments: dict[str, Any]) -> dict[str, Any]:
    codes = unique_upper(arguments.get("approvalItemCodes"))
    if not codes:
        return insufficient("decode_ndt_approval_item_codes", arguments, "approval_item_codes_missing")
    unknown = [code for code in codes if code not in NDT_APPROVAL_CODE_METHODS]
    decoded = sorted({method for code in codes for method in NDT_APPROVAL_CODE_METHODS.get(code, set())})
    output = result(
        "decode_ndt_approval_item_codes",
        "evidence_insufficient" if unknown else "passed",
        facts={"approvalItemCodes": codes, "decodedMethods": decoded, "unknownCodes": unknown},
        checks=[check("all_approval_codes_decoded", not unknown, unknown, [])],
        rule_version=str(arguments.get("ruleVersion") or "ndt-approval-code-tsg-z7002-2022-v1"),
    )
    if unknown:
        output["warnings"] = ["unknown_ndt_approval_item_codes"]
    return output


def evaluate_ndt_agencies(arguments: dict[str, Any]) -> dict[str, Any]:
    agencies = list_of_dicts(arguments.get("agencies"))
    mode = str(arguments.get("evaluationMode") or "").strip()
    if not agencies:
        return insufficient("evaluate_ndt_agencies", arguments, "ndt_agencies_missing")
    if mode not in {"identity", "method_coverage", "date_coverage"}:
        return insufficient("evaluate_ndt_agencies", arguments, "ndt_evaluation_mode_unsupported")

    checks: list[dict[str, Any]] = []
    agency_results: list[dict[str, Any]] = []
    recommended_actions: list[dict[str, Any]] = []
    for index, agency in enumerate(agencies, 1):
        agency_id = str(agency.get("agencyId") or "").strip()
        if not agency_id:
            return insufficient("evaluate_ndt_agencies", arguments, "ndt_agency_id_missing")
        item_checks: list[dict[str, Any]] = []
        item_facts: dict[str, Any] = {"agencyId": agency_id}
        if mode == "identity":
            license_name = agency.get("licenseOrganizationName")
            plan_name = agency.get("planOrganizationName")
            if not license_name or not plan_name:
                return insufficient("evaluate_ndt_agencies", arguments, "ndt_organization_names_missing")
            normalized_license = normalize_value(license_name, "organization_name")
            normalized_plan = normalize_value(plan_name, "organization_name")
            item_checks.append(check(f"agency_{index}_organization_name", normalized_license == normalized_plan, license_name, plan_name))
            item_facts.update({"licenseOrganizationName": license_name, "planOrganizationName": plan_name})
        elif mode == "method_coverage":
            codes = unique_upper(agency.get("approvalItemCodes"))
            required = set(unique_upper(agency.get("requiredMethods")))
            if not codes or not required:
                return insufficient("evaluate_ndt_agencies", arguments, "ndt_codes_or_required_methods_missing")
            unknown = [code for code in codes if code not in NDT_APPROVAL_CODE_METHODS]
            if unknown:
                return insufficient("evaluate_ndt_agencies", arguments, "unknown_ndt_approval_item_codes")
            decoded = {method for code in codes for method in NDT_APPROVAL_CODE_METHODS[code]}
            for method in sorted(required):
                item_checks.append(check(f"agency_{index}_method_{safe_code(method)}", method in decoded, sorted(decoded), method))
            item_facts.update({"approvalItemCodes": codes, "decodedMethods": sorted(decoded), "requiredMethods": sorted(required)})
        else:
            valid_from = parse_date(agency.get("validFrom"))
            valid_until = parse_date(agency.get("validUntil"))
            period_start = parse_date(agency.get("periodStart"))
            period_end = parse_date(agency.get("plannedPeriodEnd"))
            if valid_until is None or period_start is None or period_end is None:
                return insufficient("evaluate_ndt_agencies", arguments, "ndt_license_or_planned_period_dates_missing")
            starts_before = valid_from is None or valid_from <= period_start
            ends_after = valid_until >= period_end
            item_checks.extend(
                [
                    check(f"agency_{index}_valid_from", starts_before, valid_from, period_start),
                    check(f"agency_{index}_valid_until", ends_after, valid_until, period_end),
                ]
            )
            item_facts.update(
                {
                    "validFrom": valid_from,
                    "validUntil": valid_until,
                    "periodStart": period_start,
                    "plannedPeriodEnd": period_end,
                }
            )
            if not starts_before or not ends_after:
                recommended_actions.append(
                    {
                        "agencyId": agency_id,
                        "action": str(arguments.get("failureAction") or "CONTACT_NOTICE_REQUIRED"),
                        "externalDocumentCreated": False,
                    }
                )
        checks.extend(item_checks)
        agency_results.append(
            {
                **item_facts,
                "result": "passed" if all(item.get("passed") for item in item_checks) else "failed",
            }
        )

    output = result(
        "evaluate_ndt_agencies",
        "passed" if checks and all(item.get("passed") for item in checks) else "failed",
        facts={"evaluationMode": mode, "agencyCount": len(agencies)},
        checks=checks,
        rule_version=str(arguments.get("ruleVersion") or "ndt-agency-tsg-z7002-2022-v1"),
    )
    output["agencyResults"] = agency_results
    output["recommendedActions"] = recommended_actions
    return output


def evaluate_installation_license_scope(arguments: dict[str, Any]) -> dict[str, Any]:
    scopes = normalized_set(arguments.get("licenseScopes"))
    grades = normalized_set(arguments.get("requiredPipelineGrades"))
    if not scopes or not grades:
        return insufficient("evaluate_installation_license_scope", arguments, "license_scope_facts_missing")
    aliases = {"gc1": {"gc1"}, "gc2": {"gc1", "gc2", "gcd"}, "gcd": {"gcd", "a级锅炉安装资质"}}
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


def evaluate_calculation_document_consistency(arguments: dict[str, Any]) -> dict[str, Any]:
    documents = list_of_dicts(arguments.get("documents"))
    target_types = normalized_set(arguments.get("targetDocumentTypes"))
    if not documents or not target_types:
        return insufficient("evaluate_calculation_document_consistency", arguments, "calculation_documents_or_types_missing")
    selected = [item for item in documents if normalize_value(item.get("documentType"), "text") in target_types]
    if not selected:
        return insufficient("evaluate_calculation_document_consistency", arguments, "target_calculation_documents_missing")

    checks: list[dict[str, Any]] = []
    document_results: list[dict[str, Any]] = []
    for index, document in enumerate(selected, 1):
        document_id = str(document.get("documentId") or "").strip()
        comparisons = list_of_dicts(document.get("parameterComparisons"))
        covered_ids = string_list(document.get("coveredPipelineIds"))
        if not document_id or "bodyUploaded" not in document or not covered_ids or not comparisons:
            return insufficient(
                "evaluate_calculation_document_consistency",
                arguments,
                "calculation_identity_body_coverage_or_comparisons_missing",
            )
        item_checks = [
            check(f"document_{index}_body_uploaded", document.get("bodyUploaded") is True, document.get("bodyUploaded"), True),
            check(f"document_{index}_covered_pipeline", bool(covered_ids), covered_ids, "non_empty"),
        ]
        for comparison_index, comparison in enumerate(comparisons, 1):
            actual = comparison.get("documentValue")
            expected = comparison.get("designValue")
            if actual is None or expected is None:
                return insufficient("evaluate_calculation_document_consistency", arguments, "calculation_parameter_value_missing")
            tolerance = decimal(comparison.get("tolerance"))
            if tolerance is not None:
                actual_number = decimal(actual)
                expected_number = decimal(expected)
                if actual_number is None or expected_number is None:
                    return insufficient("evaluate_calculation_document_consistency", arguments, "calculation_numeric_parameter_invalid")
                passed = abs(actual_number - expected_number) <= tolerance
            else:
                normalizer = str(comparison.get("normalizer") or "text")
                passed = normalize_value(actual, normalizer) == normalize_value(expected, normalizer)
            code = safe_code(comparison.get("code") or f"parameter_{comparison_index}")
            item_checks.append(check(f"document_{index}_{code}", passed, actual, expected))
        checks.extend(item_checks)
        document_results.append(
            {
                "documentId": document_id,
                "documentType": document.get("documentType"),
                "coveredPipelineIds": covered_ids,
                "result": "passed" if all(item.get("passed") for item in item_checks) else "failed",
            }
        )
    output = result(
        "evaluate_calculation_document_consistency",
        "passed" if checks and all(item.get("passed") for item in checks) else "failed",
        facts={"documentCount": len(selected)},
        checks=checks,
        rule_version=str(arguments.get("ruleVersion") or "r06-calculation-consistency-v1"),
    )
    output["documentResults"] = document_results
    return output


FOUR_LEVEL_DESIGN_DOCUMENT_TYPES = {
    "pipeline_material_grade_table",
    "pipeline_stress_calculation",
    "equipment_layout_drawing",
    "pipeline_layout_drawing",
}


def evaluate_design_change_approval(arguments: dict[str, Any]) -> dict[str, Any]:
    has_changes = arguments.get("hasDesignChanges")
    if not isinstance(has_changes, bool):
        return insufficient("evaluate_design_change_approval", arguments, "design_change_applicability_missing")
    if not has_changes:
        return result(
            "evaluate_design_change_approval",
            "not_applicable",
            facts={"hasDesignChanges": False},
            checks=[],
            rule_version=str(arguments.get("ruleVersion") or "r07-design-change-approval-tsg31-2025-v1"),
        )
    documents = list_of_dicts(arguments.get("documents"))
    pipelines = list_of_dicts(arguments.get("pipelines"))
    if not documents:
        return insufficient("evaluate_design_change_approval", arguments, "design_change_documents_missing")
    pipeline_by_id = {str(item.get("pipelineId")): item for item in pipelines if item.get("pipelineId")}

    checks: list[dict[str, Any]] = []
    document_results: list[dict[str, Any]] = []
    for index, document in enumerate(documents, 1):
        document_id = str(document.get("documentId") or "").strip()
        document_type = normalize_value(document.get("documentType"), "text")
        approval_type = normalize_value(document.get("changedDocumentType") or document.get("documentType"), "text")
        if not document_id or not document_type or "bodyUploaded" not in document or "writtenApproval" not in document:
            return insufficient("evaluate_design_change_approval", arguments, "design_change_identity_body_or_approval_missing")
        actual_role_list = unique_normalized(document.get("signatureRoles"))
        if not actual_role_list:
            return insufficient("evaluate_design_change_approval", arguments, "design_change_signature_roles_missing")
        original_org = document.get("originalDesignOrganizationName")
        approving_org = document.get("approvingOrganizationName")
        if not original_org or not approving_org:
            return insufficient("evaluate_design_change_approval", arguments, "design_change_organization_names_missing")

        required_level = 3
        trigger_codes: list[str] = []
        if approval_type in FOUR_LEVEL_DESIGN_DOCUMENT_TYPES:
            covered_ids = string_list(document.get("coveredPipelineIds"))
            if covered_ids:
                covered = [pipeline_by_id[item] for item in covered_ids if item in pipeline_by_id]
                if len(covered) != len(set(covered_ids)):
                    return insufficient("evaluate_design_change_approval", arguments, "design_change_covered_pipeline_not_found")
            elif len(pipelines) == 1:
                covered = pipelines
            else:
                return insufficient("evaluate_design_change_approval", arguments, "design_change_pipeline_link_missing")
            for pipeline in covered:
                trigger = design_four_level_trigger(pipeline)
                if trigger is None:
                    return insufficient("evaluate_design_change_approval", arguments, "design_change_pipeline_parameters_missing")
                if trigger:
                    trigger_codes.append(trigger)
            if trigger_codes:
                required_level = 4

        required_roles = ["设计", "校核", "审核"] + (["审定"] if required_level == 4 else [])
        actual_roles = set(actual_role_list)
        item_checks = [
            check(f"document_{index}_body_uploaded", document.get("bodyUploaded") is True, document.get("bodyUploaded"), True),
            check(f"document_{index}_written_approval", document.get("writtenApproval") is True, document.get("writtenApproval"), True),
            check(
                f"document_{index}_original_design_organization",
                normalize_value(approving_org, "organization_name") == normalize_value(original_org, "organization_name"),
                approving_org,
                original_org,
            ),
            *[
                check(f"document_{index}_{safe_code(role)}", role in actual_roles, actual_role_list, role)
                for role in required_roles
            ],
        ]
        checks.extend(item_checks)
        document_results.append(
            {
                "documentId": document_id,
                "documentType": document.get("documentType"),
                "changedDocumentType": document.get("changedDocumentType"),
                "requiredApprovalLevel": required_level,
                "requiredRoles": required_roles,
                "actualRoles": actual_role_list,
                "triggerCodes": sorted(set(trigger_codes)),
                "result": "passed" if all(item.get("passed") for item in item_checks) else "failed",
            }
        )
    output = result(
        "evaluate_design_change_approval",
        "passed" if checks and all(item.get("passed") for item in checks) else "failed",
        facts={"hasDesignChanges": True, "documentCount": len(documents)},
        checks=checks,
        rule_version=str(arguments.get("ruleVersion") or "r07-design-change-approval-tsg31-2025-v1"),
    )
    output["documentResults"] = document_results
    return output


def verify_design_license_seals(arguments: dict[str, Any]) -> dict[str, Any]:
    has_changes = arguments.get("hasDesignChanges")
    if not isinstance(has_changes, bool):
        return insufficient("verify_design_license_seals", arguments, "design_change_applicability_missing")
    if not has_changes:
        return result("verify_design_license_seals", "not_applicable", facts={"hasDesignChanges": False}, checks=[])
    documents = list_of_dicts(arguments.get("documents"))
    required_types = normalized_set(arguments.get("requiredDocumentTypes"))
    expected_name = str(arguments.get("expectedSealName") or "").strip()
    if not documents or not required_types or not expected_name:
        return insufficient("verify_design_license_seals", arguments, "seal_documents_or_policy_missing")
    selected = [item for item in documents if normalize_value(item.get("documentType"), "text") in required_types]
    if not selected:
        return result(
            "verify_design_license_seals",
            "not_applicable",
            facts={"requiredDocumentTypes": sorted(required_types), "matchedDocumentCount": 0},
            checks=[],
            rule_version=str(arguments.get("ruleVersion") or "r07-design-license-seal-tsg31-2025-3.1.2-v1"),
        )

    checks: list[dict[str, Any]] = []
    document_results: list[dict[str, Any]] = []
    for index, document in enumerate(selected, 1):
        document_id = str(document.get("documentId") or "").strip()
        seal = dict_value(document.get("designLicenseSeal"))
        if not document_id or "present" not in seal:
            return insufficient("verify_design_license_seals", arguments, "seal_presence_fact_missing")
        item_checks = [check(f"document_{index}_seal_present", seal.get("present") is True, seal.get("present"), True)]
        if seal.get("present") is True:
            original_org = document.get("originalDesignOrganizationName")
            seal_name = seal.get("sealName")
            seal_org = seal.get("organizationName")
            impression_type = normalize_value(seal.get("impressionType"), "text")
            if not original_org or not seal_name or not seal_org or not impression_type:
                return insufficient("verify_design_license_seals", arguments, "seal_identity_or_impression_missing")
            item_checks.extend(
                [
                    check(f"document_{index}_seal_name", normalize_value(seal_name, "text") == normalize_value(expected_name, "text"), seal_name, expected_name),
                    check(
                        f"document_{index}_seal_organization",
                        normalize_value(seal_org, "organization_name") == normalize_value(original_org, "organization_name"),
                        seal_org,
                        original_org,
                    ),
                    check(f"document_{index}_seal_original", impression_type == "original", impression_type, "original"),
                    check(f"document_{index}_not_as_built_drawing", document.get("isAsBuiltDrawing") is not True, document.get("isAsBuiltDrawing"), False),
                ]
            )
            expected_license = document.get("expectedDesignLicenseNumber")
            if expected_license:
                item_checks.append(
                    check(
                        f"document_{index}_seal_license_number",
                        normalize_value(seal.get("licenseNumber"), "text") == normalize_value(expected_license, "text"),
                        seal.get("licenseNumber"),
                        expected_license,
                    )
                )
        checks.extend(item_checks)
        document_results.append(
            {
                "documentId": document_id,
                "documentType": document.get("documentType"),
                "sealRequired": True,
                "result": "passed" if all(item.get("passed") for item in item_checks) else "failed",
            }
        )
    output = result(
        "verify_design_license_seals",
        "passed" if checks and all(item.get("passed") for item in checks) else "failed",
        facts={"requiredDocumentTypes": sorted(required_types), "matchedDocumentCount": len(selected)},
        checks=checks,
        rule_version=str(arguments.get("ruleVersion") or "r07-design-license-seal-tsg31-2025-3.1.2-v1"),
    )
    output["documentResults"] = document_results
    return output


def evaluate_design_special_requirements(arguments: dict[str, Any]) -> dict[str, Any]:
    requirements = dict_value(arguments.get("requirements"))
    standard_rules = dict_value(arguments.get("standardRules"))
    required_paths_by_domain = dict_value(arguments.get("requiredPathsByDomain"))
    domains = string_list(arguments.get("domains"))
    if not requirements or not standard_rules or not required_paths_by_domain or not domains:
        return insufficient(
            "evaluate_design_special_requirements",
            arguments,
            "design_special_requirement_profile_missing",
        )

    checks: list[dict[str, Any]] = []
    domain_results: list[dict[str, Any]] = []
    for domain_name in domains:
        domain = dict_value(requirements.get(domain_name))
        if not domain or not isinstance(domain.get("specified"), bool):
            return insufficient(
                "evaluate_design_special_requirements",
                arguments,
                f"{domain_name}_requirement_fact_missing",
            )
        required_paths = string_list(required_paths_by_domain.get(domain_name))
        rule_container = standard_rules.get(domain_name)
        rules = list_of_dicts(rule_container.get("checks")) if isinstance(rule_container, dict) else list_of_dicts(rule_container)
        if not required_paths or not rules:
            return insufficient(
                "evaluate_design_special_requirements",
                arguments,
                f"{domain_name}_required_paths_or_standard_rules_missing",
            )

        domain_checks = [
            check(
                f"{safe_code(domain_name)}_specified",
                domain.get("specified") is True,
                domain.get("specified"),
                True,
            )
        ]
        missing_paths: list[str] = []
        for path in required_paths:
            actual = read_path(domain, path)
            present = is_present(actual)
            if not present:
                missing_paths.append(path)
            domain_checks.append(check(f"{safe_code(domain_name)}_{safe_code(path)}", present, actual, "present"))

        referenced_standards = set(string_list(domain.get("standardRefs")))
        standard_checks: list[dict[str, Any]] = []
        violations: list[str] = []
        for index, rule in enumerate(rules, 1):
            actual_path = str(rule.get("actualPath") or "").strip()
            standard_ref = str(rule.get("standardRef") or "").strip()
            operator = str(rule.get("operator") or "").strip()
            if not actual_path or not standard_ref or not operator:
                return insufficient(
                    "evaluate_design_special_requirements",
                    arguments,
                    f"{domain_name}_standard_rule_{index}_invalid",
                )
            reference_check = check(
                f"{safe_code(domain_name)}_standard_ref_{index}",
                standard_ref in referenced_standards,
                sorted(referenced_standards),
                standard_ref,
            )
            evaluated = evaluate_rule_check(
                {
                    **rule,
                    "actual": read_path(domain, actual_path),
                    "code": f"{safe_code(domain_name)}_{rule.get('code') or index}",
                }
            )
            if evaluated is None:
                return insufficient(
                    "evaluate_design_special_requirements",
                    arguments,
                    f"{domain_name}_standard_rule_{index}_unsupported",
                )
            standard_checks.extend([reference_check, evaluated])
            if not reference_check.get("passed"):
                violations.append(f"standard_not_referenced:{standard_ref}")
            if not evaluated.get("passed"):
                violations.append(str(rule.get("code") or f"rule_{index}"))

        checks.extend([*domain_checks, *standard_checks])
        completeness_passed = all(item.get("passed") for item in domain_checks)
        compliance_passed = all(item.get("passed") for item in standard_checks)
        domain_results.append(
            {
                "domain": domain_name,
                "specified": domain.get("specified"),
                "completenessResult": "passed" if completeness_passed else "failed",
                "standardComplianceResult": "passed" if compliance_passed else "failed",
                "missingPaths": missing_paths,
                "violations": violations,
                "standardRefs": sorted(referenced_standards),
                "result": "passed" if completeness_passed and compliance_passed else "failed",
            }
        )

    output = result(
        "evaluate_design_special_requirements",
        "passed" if checks and all(item.get("passed") for item in checks) else "failed",
        facts={"domains": domains},
        checks=checks,
        rule_version=str(arguments.get("ruleVersion") or "r09-design-special-requirements-v1"),
    )
    output["domainResults"] = domain_results
    return output


def evaluate_design_document_approval(arguments: dict[str, Any]) -> dict[str, Any]:
    """Evaluate R04 approval signatures per document and per covered pipeline."""
    mode = str(arguments.get("approvalMode") or "").strip()
    documents = list_of_dicts(arguments.get("documents"))
    target_types = normalized_set(arguments.get("targetDocumentTypes"))
    required_role_list = unique_normalized(arguments.get("requiredRoles"))
    required_roles = set(required_role_list)
    if mode not in {"three_level", "four_level_conditional"}:
        return insufficient("evaluate_design_document_approval", arguments, "approval_mode_unsupported")
    if not documents:
        return insufficient("evaluate_design_document_approval", arguments, "design_documents_missing")
    if not target_types or not required_roles:
        return insufficient("evaluate_design_document_approval", arguments, "approval_rule_parameters_missing")

    selected = [item for item in documents if normalize_value(item.get("documentType"), "text") in target_types]
    if not selected:
        return insufficient("evaluate_design_document_approval", arguments, "target_design_documents_missing")
    for document in selected:
        if not document.get("documentId") or "bodyUploaded" not in document or not isinstance(document.get("signatureRoles"), list):
            return insufficient("evaluate_design_document_approval", arguments, "document_identity_body_or_signatures_missing")

    pipelines = list_of_dicts(arguments.get("pipelines"))
    pipeline_by_id = {str(item.get("pipelineId")): item for item in pipelines if item.get("pipelineId")}
    if mode == "four_level_conditional" and not pipelines:
        return insufficient("evaluate_design_document_approval", arguments, "pipeline_design_parameters_missing")

    checks: list[dict[str, Any]] = []
    document_results: list[dict[str, Any]] = []
    applicable_document_count = 0
    for index, document in enumerate(selected, 1):
        trigger_codes: list[str] = []
        if mode == "four_level_conditional":
            covered_ids = string_list(document.get("coveredPipelineIds"))
            if covered_ids:
                covered = [pipeline_by_id[item] for item in covered_ids if item in pipeline_by_id]
                if len(covered) != len(set(covered_ids)):
                    return insufficient("evaluate_design_document_approval", arguments, "covered_pipeline_not_found")
            elif len(pipelines) == 1:
                covered = pipelines
            else:
                return insufficient("evaluate_design_document_approval", arguments, "document_pipeline_link_missing")
            for pipeline in covered:
                trigger = design_four_level_trigger(pipeline)
                if trigger is None:
                    return insufficient("evaluate_design_document_approval", arguments, "pipeline_grade_pressure_or_temperature_missing")
                if trigger:
                    trigger_codes.append(trigger)
            if not trigger_codes:
                continue

        applicable_document_count += 1
        actual_role_list = unique_normalized(document.get("signatureRoles"))
        actual_roles = set(actual_role_list)
        body_check = check(
            f"document_{index}_body_uploaded",
            document.get("bodyUploaded") is True,
            document.get("bodyUploaded"),
            True,
        )
        role_checks = [
            check(f"document_{index}_{safe_code(role)}", role in actual_roles, actual_role_list, role)
            for role in required_role_list
        ]
        checks.extend([body_check, *role_checks])
        missing_roles = [role for role in required_role_list if role not in actual_roles]
        document_results.append(
            {
                "documentId": document.get("documentId"),
                "documentType": document.get("documentType"),
                "requiredApprovalLevel": 3 if mode == "three_level" else 4,
                "triggerCodes": sorted(set(trigger_codes)),
                "requiredRoles": required_role_list,
                "actualRoles": actual_role_list,
                "missingRoles": missing_roles,
                "bodyUploaded": document.get("bodyUploaded"),
                "result": "passed" if body_check["passed"] and not missing_roles else "failed",
                "evidenceRefs": list(document.get("evidenceRefs") or []),
            }
        )

    if mode == "four_level_conditional" and applicable_document_count == 0:
        output = result(
            "evaluate_design_document_approval",
            "not_applicable",
            facts={"documents": selected, "pipelines": pipelines, "approvalMode": mode},
            checks=[],
            rule_version=rule_version(arguments),
        )
        output["documentResults"] = []
        return output

    output = result(
        "evaluate_design_document_approval",
        "passed" if checks and all(item.get("passed") for item in checks) else "failed",
        facts={"documents": selected, "pipelines": pipelines, "approvalMode": mode},
        checks=checks,
        rule_version=rule_version(arguments),
    )
    output["documentResults"] = document_results
    return output


def design_four_level_trigger(pipeline: dict[str, Any]) -> str | None:
    grade = normalize_value(pipeline.get("pipelineGrade"), "text")
    if not grade:
        return None
    if grade == "gc1":
        return "GC1_PIPELINE"
    if grade != "gcd":
        return ""
    pressure = decimal(pipeline.get("designPressureMPa"))
    if pressure is None:
        return None
    if pressure >= Decimal("16.7"):
        return "GCD_PRESSURE_GTE_16_7"
    if pressure < Decimal("4.0"):
        return ""
    temperature = decimal(pipeline.get("designTemperatureC"))
    if temperature is None:
        return None
    if temperature >= Decimal("570"):
        return "GCD_PRESSURE_GTE_4_AND_TEMPERATURE_GTE_570"
    return ""


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


def unique_normalized(value: Any) -> list[str]:
    output: list[str] = []
    for item in string_list(value):
        normalized = normalize_value(item, "text")
        if normalized and normalized not in output:
            output.append(normalized)
    return output


def unique_upper(value: Any) -> list[str]:
    output: list[str] = []
    for item in string_list(value):
        normalized = str(item).strip().upper()
        if normalized and normalized not in output:
            output.append(normalized)
    return output


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
