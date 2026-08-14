from __future__ import annotations

import re
from typing import Any

from libs.review_orchestrator.deterministic_tools import check, normalize_value, result
from libs.review_tools.r13_tools import (
    classify_component_requirement,
    evaluate_r13_supervision_certificate_completeness,
    evaluate_r13_type_test_coverage,
)

R15_RULE_VERSION = "r15-foreign-component-tsg31-2025-d7006-2020-v1"

_DOMESTIC_COUNTRY_MARKERS = {
    "cn",
    "prc",
    "china",
    "中国",
    "中华人民共和国",
}
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
_INVALID_REGISTRY_STATUSES = {"expired", "revoked", "suspended", "invalid", "过期", "撤销", "暂停", "失效"}
_ACTIVE_REGISTRY_STATUSES = {"active", "valid", "normal", "有效", "正常"}
_KNOWN_LICENSED_CATEGORIES = {
    "submerged_arc_welded_steel_pipe",
    "polyethylene_pipe",
    "seamless_steel_pipe",
    "pressure_pipe_fitting",
    "pressure_piping_flange",
    "metal_bellows_expansion_joint",
}


def classify_r15_foreign_manufacturing_applicability(arguments: dict[str, Any]) -> dict[str, Any]:
    design_items = _list_of_dicts(arguments.get("designItems"))
    if not design_items:
        return _insufficient(
            "classify_r15_foreign_manufacturing_applicability",
            arguments,
            "r15_design_items_missing",
        )

    matrix: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    unknown = False
    foreign_count = 0
    for index, item in enumerate(design_items, 1):
        item_id = _item_id(item, index)
        foreign_state, source = _foreign_manufacturing_state(item)
        if foreign_state is True:
            foreign_count += 1
        elif foreign_state is None:
            unknown = True
        checks.append(
            check(
                f"component_{index}_foreign_manufacturing_identified",
                isinstance(foreign_state, bool),
                foreign_state,
                "boolean_from_manufacturing_country_or_explicit_business_fact",
            )
        )
        matrix.append(
            {
                "componentItemId": item_id,
                "componentType": item.get("componentType") or item.get("productName"),
                "manufacturerName": item.get("manufacturerName"),
                "manufacturingCountry": item.get("manufacturingCountry")
                or item.get("countryOfManufacture")
                or item.get("manufacturerCountry"),
                "manufacturingLocation": item.get("manufacturingLocation"),
                "isForeignManufactured": foreign_state,
                "classificationSource": source,
                "result": (
                    "passed"
                    if foreign_state is True
                    else "not_applicable"
                    if foreign_state is False
                    else "evidence_insufficient"
                ),
            }
        )

    business_result = "evidence_insufficient" if unknown else "passed" if foreign_count else "not_applicable"
    output = result(
        "classify_r15_foreign_manufacturing_applicability",
        business_result,
        facts={
            "designItemCount": len(design_items),
            "foreignItemCount": foreign_count,
            "applicabilityMatrix": matrix,
        },
        checks=checks,
        rule_version=str(arguments.get("ruleVersion") or R15_RULE_VERSION),
    )
    output["applicabilityMatrix"] = matrix
    if unknown:
        output["warnings"] = ["one_or_more_manufacturing_origins_unclassifiable"]
    return output


def classify_r15_regulatory_requirements(arguments: dict[str, Any]) -> dict[str, Any]:
    design_items = _list_of_dicts(arguments.get("designItems"))
    if not design_items:
        return _insufficient("classify_r15_regulatory_requirements", arguments, "r15_design_items_missing")

    foreign_items, origin_unknown = _foreign_items(design_items)
    if not foreign_items:
        if origin_unknown:
            return _insufficient(
                "classify_r15_regulatory_requirements",
                arguments,
                "foreign_manufacturing_applicability_unknown",
            )
        return result(
            "classify_r15_regulatory_requirements",
            "not_applicable",
            facts={"designItemCount": len(design_items), "requirementMatrix": []},
            checks=[],
            rule_version=str(arguments.get("ruleVersion") or R15_RULE_VERSION),
        )

    matrix: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    incomplete = origin_unknown
    for index, item in enumerate(foreign_items, 1):
        classification = _regulatory_classification(item, index)
        matrix.append(classification)
        for field in (
            "manufacturingLicenseRequirementKnown",
            "typeTestRequirementKnown",
            "supervisionRequirementKnown",
        ):
            known = classification.get(field) is True
            incomplete = incomplete or not known
            checks.append(
                check(
                    f"component_{index}_{_snake(field)}",
                    known,
                    classification.get(field),
                    "boolean_requirement_from_frozen_directory_or_explicit_business_fact",
                )
            )

    output = result(
        "classify_r15_regulatory_requirements",
        "evidence_insufficient" if incomplete else "passed",
        facts={
            "foreignItemCount": len(foreign_items),
            "requirementMatrix": matrix,
        },
        checks=checks,
        rule_version=str(arguments.get("ruleVersion") or R15_RULE_VERSION),
    )
    output["requirementMatrix"] = matrix
    if incomplete:
        output["warnings"] = ["one_or_more_r15_regulatory_requirements_unclassifiable"]
    return output


def evaluate_r15_manufacturing_license_coverage(arguments: dict[str, Any]) -> dict[str, Any]:
    design_items = _list_of_dicts(arguments.get("designItems"))
    candidates = _list_of_dicts(arguments.get("licenseCandidates"))
    verifications = _list_of_dicts(arguments.get("registryVerifications"))
    if not design_items:
        return _insufficient(
            "evaluate_r15_manufacturing_license_coverage",
            arguments,
            "r15_design_items_missing",
        )

    foreign_items, origin_unknown = _foreign_items(design_items)
    required_items: list[tuple[dict[str, Any], dict[str, Any]]] = []
    requirement_unknown = origin_unknown
    for index, item in enumerate(foreign_items, 1):
        classification = _regulatory_classification(item, index)
        if not classification["manufacturingLicenseRequirementKnown"]:
            requirement_unknown = True
        elif classification["requiresManufacturingLicense"]:
            required_items.append((item, classification))
    if not foreign_items:
        return _insufficient(
            "evaluate_r15_manufacturing_license_coverage",
            arguments,
            "foreign_manufacturing_applicability_unknown",
        ) if origin_unknown else result(
            "evaluate_r15_manufacturing_license_coverage",
            "not_applicable",
            facts={"foreignItemCount": 0, "componentCoverageMatrix": []},
            checks=[],
            rule_version=str(arguments.get("ruleVersion") or R15_RULE_VERSION),
        )
    if not required_items:
        return _insufficient(
            "evaluate_r15_manufacturing_license_coverage",
            arguments,
            "manufacturing_license_requirement_unknown",
        ) if requirement_unknown else result(
            "evaluate_r15_manufacturing_license_coverage",
            "not_applicable",
            facts={"foreignItemCount": len(foreign_items), "componentCoverageMatrix": []},
            checks=[],
            rule_version=str(arguments.get("ruleVersion") or R15_RULE_VERSION),
        )

    require_registry = arguments.get("requireRegistryVerification") is not False
    verification_by_candidate = {
        str(item.get("candidateId")): item
        for item in verifications
        if item.get("candidateId")
    }
    checks: list[dict[str, Any]] = []
    matrix: list[dict[str, Any]] = []
    failed = False
    incomplete = requirement_unknown
    for index, (item, classification) in enumerate(required_items, 1):
        item_id = classification["componentItemId"]
        manufacturer = _organization(item.get("manufacturerName"))
        required_scope = _component_scope_category(item.get("componentType") or item.get("productName"))
        if not manufacturer or not required_scope:
            incomplete = True
            missing = []
            if not manufacturer:
                missing.append("manufacturerName")
            if not required_scope:
                missing.append("supportedComponentType")
            checks.append(check(f"component_{index}_license_scope_facts", False, missing, "complete"))
            matrix.append(
                {
                    **classification,
                    "result": "evidence_insufficient",
                    "reasonCodes": ["license_scope_facts_missing", *missing],
                }
            )
            continue

        matched_candidates = [
            candidate
            for candidate in candidates
            if _organization(candidate.get("organizationName") or candidate.get("manufacturerName")) == manufacturer
        ]
        if not matched_candidates:
            failed = True
            checks.append(check(f"component_{index}_manufacturing_license_present", False, None, manufacturer))
            matrix.append(
                {
                    **classification,
                    "requiredScopeCategory": required_scope,
                    "result": "failed",
                    "reasonCodes": ["manufacturing_license_missing"],
                }
            )
            continue

        evaluated = [
            _evaluate_license_candidate(candidate, verification_by_candidate.get(str(candidate.get("candidateId"))), required_scope, require_registry)
            for candidate in matched_candidates
        ]
        passed_match = next((entry for entry in evaluated if entry["state"] == "passed"), None)
        if passed_match:
            checks.append(
                check(
                    f"component_{index}_manufacturing_license_scope",
                    True,
                    passed_match.get("scope"),
                    required_scope,
                )
            )
            matrix.append(
                {
                    **classification,
                    "requiredScopeCategory": required_scope,
                    "matchedLicenseCandidateId": passed_match.get("candidateId"),
                    "result": "passed",
                    "reasonCodes": [],
                }
            )
            continue

        insufficient_match = next((entry for entry in evaluated if entry["state"] == "evidence_insufficient"), None)
        if insufficient_match:
            incomplete = True
            checks.append(
                check(
                    f"component_{index}_manufacturing_license_scope",
                    False,
                    insufficient_match.get("reasonCodes"),
                    required_scope,
                )
            )
            matrix.append(
                {
                    **classification,
                    "requiredScopeCategory": required_scope,
                    "matchedLicenseCandidateId": insufficient_match.get("candidateId"),
                    "result": "evidence_insufficient",
                    "reasonCodes": insufficient_match.get("reasonCodes"),
                }
            )
            continue

        failed = True
        reason_codes = list(dict.fromkeys(code for entry in evaluated for code in entry.get("reasonCodes") or []))
        checks.append(check(f"component_{index}_manufacturing_license_scope", False, reason_codes, required_scope))
        matrix.append(
            {
                **classification,
                "requiredScopeCategory": required_scope,
                "result": "failed",
                "reasonCodes": reason_codes or ["manufacturing_license_scope_not_covering_item"],
            }
        )

    business_result = "failed" if failed else "evidence_insufficient" if incomplete else "passed"
    output = result(
        "evaluate_r15_manufacturing_license_coverage",
        business_result,
        facts={
            "foreignItemCount": len(foreign_items),
            "requiredLicenseItemCount": len(required_items),
            "licenseCandidateCount": len(candidates),
            "componentCoverageMatrix": matrix,
        },
        checks=checks,
        rule_version=str(arguments.get("ruleVersion") or R15_RULE_VERSION),
    )
    output["componentCoverageMatrix"] = matrix
    return output


def evaluate_r15_type_test_coverage(arguments: dict[str, Any]) -> dict[str, Any]:
    design_items = _list_of_dicts(arguments.get("designItems"))
    reports = _list_of_dicts(arguments.get("typeTestReports"))
    if not design_items:
        return _insufficient("evaluate_r15_type_test_coverage", arguments, "r15_design_items_missing")
    foreign_items, origin_unknown = _foreign_items(design_items)
    if not foreign_items:
        return _insufficient(
            "evaluate_r15_type_test_coverage",
            arguments,
            "foreign_manufacturing_applicability_unknown",
        ) if origin_unknown else result(
            "evaluate_r15_type_test_coverage",
            "not_applicable",
            facts={"foreignItemCount": 0, "coverageMatrix": []},
            checks=[],
            rule_version=str(arguments.get("ruleVersion") or R15_RULE_VERSION),
        )

    requirement_unknown = False
    required_items: list[dict[str, Any]] = []
    for index, item in enumerate(foreign_items, 1):
        classification = _regulatory_classification(item, index)
        if not classification["typeTestRequirementKnown"]:
            requirement_unknown = True
        elif classification["requiresTypeTest"]:
            required_items.append(item)
    if not required_items:
        return _insufficient(
            "evaluate_r15_type_test_coverage",
            arguments,
            "type_test_requirement_unknown",
        ) if requirement_unknown else result(
            "evaluate_r15_type_test_coverage",
            "not_applicable",
            facts={"foreignItemCount": len(foreign_items), "coverageMatrix": []},
            checks=[],
            rule_version=str(arguments.get("ruleVersion") or R15_RULE_VERSION),
        )

    delegated = evaluate_r13_type_test_coverage(
        {
            "designItems": required_items,
            "typeTestReports": reports,
            "ruleVersion": str(arguments.get("ruleVersion") or R15_RULE_VERSION),
        }
    )
    delegated["toolName"] = "evaluate_r15_type_test_coverage"
    if requirement_unknown and delegated.get("result") == "passed":
        delegated["result"] = "evidence_insufficient"
        delegated.setdefault("warnings", []).append("one_or_more_type_test_requirements_unclassifiable")
    delegated["facts"]["foreignItemCount"] = len(foreign_items)
    delegated["facts"]["requiredTypeTestItemCount"] = len(required_items)
    return delegated


def evaluate_r15_manufacturing_inspection_route(arguments: dict[str, Any]) -> dict[str, Any]:
    design_items = _list_of_dicts(arguments.get("designItems"))
    supervision_certificates = _list_of_dicts(arguments.get("supervisionCertificates"))
    arrival_records = _list_of_dicts(arguments.get("arrivalInspectionRecords"))
    complete_machine_records = _list_of_dicts(arguments.get("completeMachineInspectionRecords"))
    if not design_items:
        return _insufficient(
            "evaluate_r15_manufacturing_inspection_route",
            arguments,
            "r15_design_items_missing",
        )

    foreign_items, origin_unknown = _foreign_items(design_items)
    if not foreign_items:
        return _insufficient(
            "evaluate_r15_manufacturing_inspection_route",
            arguments,
            "foreign_manufacturing_applicability_unknown",
        ) if origin_unknown else result(
            "evaluate_r15_manufacturing_inspection_route",
            "not_applicable",
            facts={"foreignItemCount": 0, "routeMatrix": []},
            checks=[],
            rule_version=str(arguments.get("ruleVersion") or R15_RULE_VERSION),
        )

    checks: list[dict[str, Any]] = []
    matrix: list[dict[str, Any]] = []
    failed = False
    incomplete = origin_unknown
    applicable_count = 0
    for index, item in enumerate(foreign_items, 1):
        classification = _regulatory_classification(item, index)
        if not classification["supervisionRequirementKnown"]:
            incomplete = True
            checks.append(check(f"component_{index}_supervision_requirement_known", False, None, "boolean"))
            matrix.append(
                {**classification, "result": "evidence_insufficient", "reasonCodes": ["supervision_requirement_unknown"]}
            )
            continue
        if not classification["requiresManufacturingSupervision"]:
            matrix.append(
                {
                    **classification,
                    "inspectionRoute": (
                        "d2_4_1_3_alternative_inspection"
                        if classification.get("alternativeInspectionRouteRequired")
                        else "not_applicable"
                    ),
                    "result": "not_applicable",
                    "reasonCodes": [],
                }
            )
            continue

        applicable_count += 1
        route = _inspection_route(item)
        if route is None:
            incomplete = True
            checks.append(check(f"component_{index}_inspection_route_known", False, None, "overseas|arrival|complete_machine"))
            matrix.append(
                {**classification, "result": "evidence_insufficient", "reasonCodes": ["manufacturing_inspection_route_unknown"]}
            )
            continue

        if route == "overseas":
            delegated = evaluate_r13_supervision_certificate_completeness(
                {
                    "designItems": [item],
                    "supervisionCertificates": supervision_certificates,
                    "ruleVersion": str(arguments.get("ruleVersion") or R15_RULE_VERSION),
                }
            )
            state = str(delegated.get("result") or "evidence_insufficient")
            reason_codes = list(delegated.get("warnings") or [])
            if state == "failed":
                failed = True
            elif state != "passed":
                incomplete = True
            checks.append(check(f"component_{index}_overseas_supervision_certificate", state == "passed", state, "passed"))
            matrix.append(
                {
                    **classification,
                    "inspectionRoute": route,
                    "result": state,
                    "reasonCodes": reason_codes,
                    "coverageMatrix": delegated.get("coverageMatrix") or [],
                }
            )
            continue

        records = complete_machine_records if route == "complete_machine" else arrival_records
        evaluated = [_match_inspection_record(item, record, route) for record in records]
        passed_match = next((entry for entry in evaluated if entry["state"] == "passed"), None)
        if passed_match:
            checks.append(check(f"component_{index}_{route}_inspection", True, passed_match.get("recordId"), route))
            matrix.append(
                {
                    **classification,
                    "inspectionRoute": route,
                    "matchedRecordId": passed_match.get("recordId"),
                    "result": "passed",
                    "reasonCodes": [],
                }
            )
            continue
        insufficient_match = next((entry for entry in evaluated if entry["state"] == "evidence_insufficient"), None)
        if insufficient_match:
            incomplete = True
            checks.append(check(f"component_{index}_{route}_inspection", False, insufficient_match.get("reasonCodes"), route))
            matrix.append(
                {
                    **classification,
                    "inspectionRoute": route,
                    "matchedRecordId": insufficient_match.get("recordId"),
                    "result": "evidence_insufficient",
                    "reasonCodes": insufficient_match.get("reasonCodes"),
                }
            )
            continue
        failed = True
        checks.append(check(f"component_{index}_{route}_inspection", False, None, route))
        matrix.append(
            {
                **classification,
                "inspectionRoute": route,
                "result": "failed",
                "reasonCodes": [f"{route}_inspection_record_missing_or_not_covering_item"],
            }
        )

    business_result = (
        "failed"
        if failed
        else "evidence_insufficient"
        if incomplete
        else "not_applicable"
        if applicable_count == 0
        else "passed"
    )
    output = result(
        "evaluate_r15_manufacturing_inspection_route",
        business_result,
        facts={
            "foreignItemCount": len(foreign_items),
            "applicableSupervisionItemCount": applicable_count,
            "routeMatrix": matrix,
        },
        checks=checks,
        rule_version=str(arguments.get("ruleVersion") or R15_RULE_VERSION),
    )
    output["routeMatrix"] = matrix
    return output


def _regulatory_classification(item: dict[str, Any], index: int) -> dict[str, Any]:
    base = classify_component_requirement(item)
    explicit_license = item.get("requiresManufacturingLicense")
    if isinstance(explicit_license, bool):
        license_required: bool | None = explicit_license
        license_reason = "structured_business_fact:requiresManufacturingLicense"
    elif base.get("regulatoryCategory") == "non_r13_component":
        license_required = False
        license_reason = "known_non_licensed_material"
    elif base.get("requiresManufacturingSupervision") is True:
        license_required = True
        license_reason = "manufacturing_supervision_category_requires_license"
    elif base.get("regulatoryCategory") in _KNOWN_LICENSED_CATEGORIES:
        license_required = True
        license_reason = str(base.get("classificationReason"))
    elif str(base.get("regulatoryCategory") or "").startswith("type_test_only"):
        license_required = False
        license_reason = "frozen_type_test_only_category"
    else:
        license_required = None
        license_reason = "manufacturing_license_requirement_not_in_frozen_directory"

    type_required = base.get("requiresTypeTest")
    supervision_required = base.get("requiresManufacturingSupervision")
    item_id = _item_id(item, index)
    return {
        "componentItemId": item_id,
        "componentType": item.get("componentType") or item.get("productName"),
        "manufacturerName": item.get("manufacturerName"),
        "regulatoryCategory": base.get("regulatoryCategory"),
        "requiresManufacturingLicense": license_required,
        "manufacturingLicenseRequirementKnown": isinstance(license_required, bool),
        "requiresTypeTest": type_required,
        "typeTestRequirementKnown": isinstance(type_required, bool),
        "requiresManufacturingSupervision": supervision_required,
        "supervisionRequirementKnown": isinstance(supervision_required, bool),
        "supervisionGranularity": base.get("supervisionGranularity"),
        "alternativeInspectionRouteRequired": all(
            value is False for value in (license_required, type_required, supervision_required)
        ),
        "classificationReason": base.get("classificationReason"),
        "licenseClassificationReason": license_reason,
        "sourceClauseRefs": list(
            dict.fromkeys(
                [
                    "TSG-31-2025-1.10",
                    "TSG-31-2025-2.2.1.5",
                    "TSG-D7006-2020-D2.4.1",
                    *(base.get("sourceClauseRefs") or []),
                ]
            )
        ),
    }


def _foreign_items(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], bool]:
    output: list[dict[str, Any]] = []
    unknown = False
    for item in items:
        state, _ = _foreign_manufacturing_state(item)
        if state is True:
            output.append(item)
        elif state is None:
            unknown = True
    return output, unknown


def _foreign_manufacturing_state(item: dict[str, Any]) -> tuple[bool | None, str]:
    for key in ("isForeignManufactured", "manufacturerIsOverseas", "foreignManufactured"):
        if isinstance(item.get(key), bool):
            return bool(item[key]), f"structured_business_fact:{key}"
    country = next(
        (
            item.get(key)
            for key in ("manufacturingCountry", "countryOfManufacture", "manufacturerCountry", "manufacturerRegistrationCountry")
            if item.get(key) not in {None, ""}
        ),
        None,
    )
    if country not in {None, ""}:
        normalized = _compact(country)
        return normalized not in {_compact(value) for value in _DOMESTIC_COUNTRY_MARKERS}, "manufacturing_country"
    location = item.get("manufacturingLocation") or item.get("manufacturerAddress")
    if location not in {None, ""} and any(marker in _compact(location) for marker in ("中国", "china", "prc")):
        return False, "manufacturing_location_domestic_marker"
    if item.get("originCountryRepresentsManufacturing") is True and item.get("originCountry") not in {None, ""}:
        normalized = _compact(item.get("originCountry"))
        return normalized not in {_compact(value) for value in _DOMESTIC_COUNTRY_MARKERS}, "qualified_origin_country"
    return None, "manufacturing_origin_missing"


def _evaluate_license_candidate(
    candidate: dict[str, Any],
    verification: dict[str, Any] | None,
    required_scope: str,
    require_registry: bool,
) -> dict[str, Any]:
    candidate_id = str(candidate.get("candidateId") or "") or None
    if not candidate.get("licenseNo"):
        return {"state": "evidence_insufficient", "candidateId": candidate_id, "reasonCodes": ["license_number_missing"]}
    if require_registry:
        if not verification:
            return {
                "state": "evidence_insufficient",
                "candidateId": candidate_id,
                "reasonCodes": ["official_registry_verification_missing"],
            }
        outcome = str(verification.get("outcome") or "")
        registry_status = _compact(verification.get("registryStatus"))
        if outcome in {"verified_mismatch", "not_found"} or registry_status in {_compact(value) for value in _INVALID_REGISTRY_STATUSES}:
            return {
                "state": "failed",
                "candidateId": candidate_id,
                "reasonCodes": ["license_registry_mismatch_or_inactive"],
            }
        if outcome != "verified_match":
            return {
                "state": "evidence_insufficient",
                "candidateId": candidate_id,
                "reasonCodes": ["license_registry_verification_inconclusive"],
            }
        if not registry_status or registry_status not in {_compact(value) for value in _ACTIVE_REGISTRY_STATUSES}:
            return {
                "state": "evidence_insufficient",
                "candidateId": candidate_id,
                "reasonCodes": ["license_registry_active_status_unconfirmed"],
            }
        registry_license_no = verification.get("registryLicenseNo")
        registry_organization = verification.get("registryOrganizationName")
        if not registry_license_no or not registry_organization:
            return {
                "state": "evidence_insufficient",
                "candidateId": candidate_id,
                "reasonCodes": ["license_registry_identity_fields_missing"],
            }
        if _compact(registry_license_no) != _compact(candidate.get("licenseNo")):
            return {
                "state": "failed",
                "candidateId": candidate_id,
                "reasonCodes": ["license_registry_number_mismatch"],
            }
        if _organization(registry_organization) != _organization(
            candidate.get("organizationName") or candidate.get("manufacturerName")
        ):
            return {
                "state": "failed",
                "candidateId": candidate_id,
                "reasonCodes": ["license_registry_organization_mismatch"],
            }
        scope = verification.get("registryScopeRaw")
    else:
        scope = candidate.get("licenseScopeRaw")
    if not scope:
        return {"state": "evidence_insufficient", "candidateId": candidate_id, "reasonCodes": ["license_scope_missing"]}
    if not _scope_covers_component(str(scope), required_scope):
        return {
            "state": "failed",
            "candidateId": candidate_id,
            "scope": scope,
            "reasonCodes": ["manufacturing_license_scope_not_covering_item"],
        }
    return {"state": "passed", "candidateId": candidate_id, "scope": scope, "reasonCodes": []}


def _inspection_route(item: dict[str, Any]) -> str | None:
    explicit = _compact(item.get("manufacturingInspectionRoute"))
    aliases = {
        "overseas": "overseas",
        "境外制造监检": "overseas",
        "arrival": "arrival",
        "到岸检验": "arrival",
        "口岸检验": "arrival",
        "使用地检验": "arrival",
        "completemachine": "complete_machine",
        "随整机检验": "complete_machine",
        "整机检验": "complete_machine",
    }
    if explicit in {_compact(key): value for key, value in aliases.items()}:
        return {_compact(key): value for key, value in aliases.items()}[explicit]
    completed = item.get("manufacturingSupervisionCompletedOverseas")
    if completed is True:
        return "overseas"
    if completed is False:
        shipped = item.get("shippedWithBoilerOrPressureVessel")
        if shipped is True:
            return "complete_machine"
        if shipped is False:
            return "arrival"
    return None


def _match_inspection_record(item: dict[str, Any], record: dict[str, Any], route: str) -> dict[str, Any]:
    record_id = str(record.get("recordId") or record.get("certificateNo") or record.get("reportNo") or "") or None
    record_route = _compact(record.get("inspectionRoute"))
    expected_aliases = {
        "arrival": {_compact(value) for value in ("arrival", "到岸检验", "口岸检验", "使用地检验")},
        "complete_machine": {_compact(value) for value in ("complete_machine", "随整机检验", "整机检验")},
    }
    if record_route and record_route not in expected_aliases.get(route, set()):
        return {"state": "failed", "recordId": record_id, "reasonCodes": ["inspection_route_mismatch"]}
    item_org = _organization(item.get("manufacturerName"))
    record_org = _organization(record.get("manufacturerName") or record.get("manufacturer"))
    if not record_org:
        return {"state": "evidence_insufficient", "recordId": record_id, "reasonCodes": ["inspection_record_manufacturer_missing"]}
    if item_org and item_org != record_org:
        return {"state": "failed", "recordId": record_id, "reasonCodes": ["inspection_record_manufacturer_mismatch"]}
    item_scope = _component_scope_category(item.get("componentType") or item.get("productName"))
    record_scope = _component_scope_category(record.get("componentType") or record.get("productName"))
    if not record_scope:
        return {"state": "evidence_insufficient", "recordId": record_id, "reasonCodes": ["inspection_record_product_missing"]}
    if item_scope and item_scope != record_scope:
        return {"state": "failed", "recordId": record_id, "reasonCodes": ["inspection_record_product_mismatch"]}
    conclusion = _compact(record.get("conclusion"))
    if not conclusion:
        return {"state": "evidence_insufficient", "recordId": record_id, "reasonCodes": ["inspection_record_conclusion_missing"]}
    if conclusion not in {_compact(value) for value in _ACCEPTED_CONCLUSIONS}:
        return {"state": "failed", "recordId": record_id, "reasonCodes": ["inspection_record_conclusion_not_accepted"]}
    if not record_id:
        return {"state": "evidence_insufficient", "recordId": None, "reasonCodes": ["inspection_record_number_missing"]}
    return {"state": "passed", "recordId": record_id, "reasonCodes": []}


def _component_scope_category(component_type: Any) -> str | None:
    normalized = normalize_value(component_type, "text")
    if not normalized:
        return None
    if any(token in normalized for token in ("安全阀", "爆破片", "紧急切断阀", "安全附件")):
        return "safety_accessory"
    if "阀" in normalized:
        return "valve"
    if "法兰" in normalized:
        return "forged_flange"
    if any(token in normalized for token in ("无缝钢管", "无缝管")):
        return "seamless_steel_pipe"
    if any(token in normalized for token in ("埋弧焊钢管", "焊接钢管", "焊管", "螺旋钢管", "直缝钢管")):
        return "welded_steel_pipe"
    if any(token in normalized for token in ("弯头", "三通", "四通", "异径", "管帽", "管件", "接头")):
        return "welded_pipe_fitting" if "焊" in normalized else "pipe_fitting"
    if any(token in normalized for token in ("调压装置", "预制管段", "流量计壳体", "元件组合装置")):
        return "component_assembly"
    return None


def _scope_covers_component(scope: str, required_scope: str) -> bool:
    normalized = normalize_value(scope, "text")
    aliases = {
        "seamless_steel_pipe": ("无缝钢管", "无缝管"),
        "welded_steel_pipe": ("焊接钢管", "焊管", "螺旋缝埋弧焊钢管", "直缝埋弧焊钢管"),
        "pipe_fitting": ("管件制造", "非焊接管件", "锻制管件", "无缝管件"),
        "welded_pipe_fitting": ("焊接管件", "有缝管件"),
        "forged_flange": ("锻制法兰", "法兰制造", "钢制锻造法兰"),
        "valve": ("阀门制造", "压力管道阀门"),
        "safety_accessory": ("安全附件制造", "安全阀制造", "爆破片装置", "紧急切断阀"),
        "component_assembly": ("元件组合装置制造", "调压装置", "预制管段", "流量计壳体"),
    }
    return any(normalize_value(alias, "text") in normalized for alias in aliases.get(required_scope, ()))


def _item_id(item: dict[str, Any], index: int) -> str:
    return str(item.get("componentItemId") or item.get("itemId") or f"R15-ITEM-{index}")


def _organization(value: Any) -> str:
    normalized = normalize_value(value, "organization_name")
    for suffix in ("有限责任公司", "股份有限公司", "有限公司"):
        if normalized.endswith(suffix):
            normalized = normalized[: -len(suffix)]
            break
    return normalized


def _compact(value: Any) -> str:
    return re.sub(r"[\s\W_]+", "", str(value or "").lower(), flags=re.UNICODE)


def _snake(value: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", value).lower()


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    return [item for item in value or [] if isinstance(item, dict)] if isinstance(value, list) else []


def _insufficient(tool_name: str, arguments: Any, reason: str) -> dict[str, Any]:
    output = result(
        tool_name,
        "evidence_insufficient",
        facts={"input": arguments, "reason": reason},
        checks=[],
        rule_version=str((arguments or {}).get("ruleVersion") or R15_RULE_VERSION)
        if isinstance(arguments, dict)
        else R15_RULE_VERSION,
    )
    output["warnings"] = [reason]
    return output
