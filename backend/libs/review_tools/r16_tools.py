from __future__ import annotations

import re
from typing import Any

from libs.review_orchestrator.deterministic_tools import check, decimal, result
from libs.review_tools.material_standard_profiles import (
    PROFILE_VERSION,
    resolve_material_standard_profile,
)

R16_RULE_VERSION = "r16-quality-certificate-tsg-d7006-2020-v1"
_PASS = {"accepted", "approved", "compliant", "qualified", "passed", "符合", "合格", "通过"}
_ORIGINAL = {"original", "正本", "原件"}
_COPY = {"copy", "photocopy", "复印件", "副本", "扫描复印件"}


def resolve_r16_product_standard_profile(arguments: dict[str, Any]) -> dict[str, Any]:
    design_items = _records(arguments.get("designItems"))
    if not design_items:
        return _insufficient("resolve_r16_product_standard_profile", "r16_design_items_missing")
    matrix, checks, incomplete = [], [], False
    for index, item in enumerate(design_items, 1):
        standard_ref = _first(item, "standardRef", "acceptanceStandard", "productStandard")
        profile = resolve_material_standard_profile(standard_ref)
        known = profile is not None
        incomplete |= not known
        checks.append(check(f"component_{index}_product_standard_resolved", known, standard_ref, "frozen_product_standard_profile"))
        matrix.append({"componentItemId": _id(item, index), "inputStandardRef": standard_ref, "profile": profile, "result": "passed" if known else "evidence_insufficient"})
    output = result("resolve_r16_product_standard_profile", "evidence_insufficient" if incomplete else "passed", facts={"standardProfileMatrix": matrix}, checks=checks, rule_version=R16_RULE_VERSION)
    output["standardProfileMatrix"] = matrix
    return output


def evaluate_r16_quality_certificate_batch_coverage(arguments: dict[str, Any]) -> dict[str, Any]:
    design_items = _records(arguments.get("designItems"))
    certificates = _records(arguments.get("qualityCertificates"))
    if not design_items:
        return _insufficient("evaluate_r16_quality_certificate_batch_coverage", "r16_design_items_missing")
    matrix, checks = [], []
    failed = incomplete = False
    for index, item in enumerate(design_items, 1):
        matches = _match_records(item, certificates)
        if not _identity_ready(item):
            incomplete = True
            status, reasons = "evidence_insufficient", ["design_item_identity_incomplete"]
        elif not matches:
            failed = True
            status, reasons = "failed", ["quality_certificate_missing"]
        elif len(matches) > 1 and not _unique_batch_match(item, matches):
            incomplete = True
            status, reasons = "evidence_insufficient", ["quality_certificate_match_ambiguous"]
        else:
            status, reasons = "passed", []
        checks.append(check(f"component_{index}_quality_certificate_covered", status == "passed", [record.get("certificateId") for record in matches], "one_unique_matching_certificate"))
        matrix.append({"componentItemId": _id(item, index), "matchedCertificateIds": [record.get("certificateId") for record in matches], "result": status, "reasonCodes": reasons})
    output = result("evaluate_r16_quality_certificate_batch_coverage", _aggregate(failed, incomplete), facts={"componentCoverageMatrix": matrix}, checks=checks, rule_version=R16_RULE_VERSION)
    output["componentCoverageMatrix"] = matrix
    return output


def evaluate_r16_quality_certificate_form_and_seals(arguments: dict[str, Any]) -> dict[str, Any]:
    certificates = _records(arguments.get("qualityCertificates"))
    if not certificates:
        return _insufficient("evaluate_r16_quality_certificate_form_and_seals", "quality_certificates_missing")
    matrix, checks = [], []
    failed = incomplete = False
    for index, certificate in enumerate(certificates, 1):
        form = _norm(_first(certificate, "documentForm", "copyType", "originalOrCopy"))
        is_original = form in {_norm(value) for value in _ORIGINAL}
        is_copy = form in {_norm(value) for value in _COPY}
        dealer_seal = _truth(_first(certificate, "dealerOfficialSealPresent", "businessOperatorOfficialSealPresent"))
        handler_seal = _truth(_first(certificate, "handlerResponsibleSealPresent", "handlerSealPresent"))
        manufacturer_seal = _truth(_first(certificate, "manufacturerQualitySealPresent", "qualitySealPresent", "sealPresent"))
        if not (is_original or is_copy):
            status, reasons = "evidence_insufficient", ["document_form_unclassified"]
            incomplete = True
        elif is_copy and not (dealer_seal and handler_seal):
            status, reasons = "failed", ["copy_required_dual_seals_missing"]
            failed = True
        elif is_original and manufacturer_seal is None:
            status, reasons = "evidence_insufficient", ["manufacturer_quality_seal_unreadable"]
            incomplete = True
        elif is_original and not manufacturer_seal:
            status, reasons = "failed", ["manufacturer_quality_seal_missing"]
            failed = True
        else:
            status, reasons = "passed", []
        checks.append(check(f"certificate_{index}_form_and_seals", status == "passed", {"documentForm": form, "dealerOfficialSeal": dealer_seal, "handlerResponsibleSeal": handler_seal, "manufacturerQualitySeal": manufacturer_seal}, "original_with_manufacturer_quality_seal_or_copy_with_dealer_and_handler_seals"))
        matrix.append({"certificateId": certificate.get("certificateId"), "documentForm": form or None, "result": status, "reasonCodes": reasons})
    output = result("evaluate_r16_quality_certificate_form_and_seals", _aggregate(failed, incomplete), facts={"certificateFormMatrix": matrix}, checks=checks, rule_version=R16_RULE_VERSION)
    output["certificateFormMatrix"] = matrix
    return output


def evaluate_r16_quality_certificate_design_match(arguments: dict[str, Any]) -> dict[str, Any]:
    return _evaluate_design_matches(arguments, "evaluate_r16_quality_certificate_design_match")


def evaluate_r16_quality_certificate_content(arguments: dict[str, Any]) -> dict[str, Any]:
    design_items = _records(arguments.get("designItems"))
    certificates = _records(arguments.get("qualityCertificates"))
    if not design_items:
        return _insufficient("evaluate_r16_quality_certificate_content", "r16_design_items_missing")
    matrix, checks = [], []
    failed = incomplete = False
    for index, item in enumerate(design_items, 1):
        profile = resolve_material_standard_profile(_first(item, "standardRef", "acceptanceStandard", "productStandard"))
        matches = _match_records(item, certificates)
        if not profile:
            incomplete = True
            matrix.append({"componentItemId": _id(item, index), "result": "evidence_insufficient", "reasonCodes": ["product_standard_profile_missing"]})
            continue
        if not matches:
            failed = True
            matrix.append({"componentItemId": _id(item, index), "result": "failed", "reasonCodes": ["quality_certificate_missing"]})
            continue
        certificate = matches[0]
        required_fields = list(profile["requiredCertificateFields"])
        special_items = _string_set(item.get("specialRequirements") or item.get("requiredInspectionItems"))
        required_tests = set(profile["coreTestItems"]) | special_items
        missing_fields = [field for field in required_fields if not _present(_first(certificate, field, _certificate_alias(field)))]
        actual_tests = _string_set(certificate.get("inspectionItems") or certificate.get("testItems"))
        missing_tests = sorted(item for item in required_tests if not _contains_test(actual_tests, item))
        conclusion = _first(certificate, "conclusion", "inspectionConclusion")
        conclusion_known = _present(conclusion)
        conclusion_passed = _accepted(conclusion) if conclusion_known else False
        if missing_fields or missing_tests or (conclusion_known and not conclusion_passed):
            failed = True
            status = "failed"
        elif not conclusion_known:
            incomplete = True
            status = "evidence_insufficient"
        else:
            status = "passed"
        checks.extend([
            check(f"component_{index}_certificate_fields_complete", not missing_fields, missing_fields, required_fields),
            check(f"component_{index}_required_test_items_complete", not missing_tests, missing_tests, sorted(required_tests)),
            check(f"component_{index}_certificate_conclusion", conclusion_passed, conclusion, "accepted"),
        ])
        matrix.append({"componentItemId": _id(item, index), "certificateId": certificate.get("certificateId"), "standardRef": profile["standardRef"], "requiredTestItems": sorted(required_tests), "missingFields": missing_fields, "missingTestItems": missing_tests, "result": status})
    output = result("evaluate_r16_quality_certificate_content", _aggregate(failed, incomplete), facts={"certificateContentMatrix": matrix, "profileVersion": PROFILE_VERSION}, checks=checks, rule_version=R16_RULE_VERSION)
    output["certificateContentMatrix"] = matrix
    return output


def evaluate_r16_quality_certificate_results(arguments: dict[str, Any]) -> dict[str, Any]:
    design_items = _records(arguments.get("designItems"))
    certificates = _records(arguments.get("qualityCertificates"))
    if not design_items:
        return _insufficient("evaluate_r16_quality_certificate_results", "r16_design_items_missing")
    matrix, checks = [], []
    failed = incomplete = False
    for index, item in enumerate(design_items, 1):
        matches = _match_records(item, certificates)
        if not matches:
            failed = True
            matrix.append({"componentItemId": _id(item, index), "result": "failed", "reasonCodes": ["quality_certificate_missing"]})
            continue
        certificate = matches[0]
        limits = _records(item.get("acceptanceLimits"))
        results = _result_map(certificate.get("testResults"))
        required_quantitative = _string_set(item.get("requiredQuantitativeItems"))
        if required_quantitative and not limits:
            incomplete = True
            matrix.append({"componentItemId": _id(item, index), "result": "evidence_insufficient", "reasonCodes": ["quantitative_acceptance_limits_not_frozen"]})
            checks.append(check(f"component_{index}_acceptance_limits_available", False, [], sorted(required_quantitative)))
            continue
        item_failed = item_incomplete = False
        comparisons = []
        for limit in limits:
            code = str(limit.get("itemCode") or limit.get("name") or "")
            actual = decimal(results.get(_norm(code)))
            minimum, maximum = decimal(limit.get("minimum")), decimal(limit.get("maximum"))
            if actual is None:
                item_incomplete = True
                passed = False
            else:
                passed = (minimum is None or actual >= minimum) and (maximum is None or actual <= maximum)
                item_failed |= not passed
            comparisons.append({"itemCode": code, "actual": actual, "minimum": minimum, "maximum": maximum, "passed": passed})
            checks.append(check(f"component_{index}_{_safe(code)}_within_limits", passed, actual, {"minimum": minimum, "maximum": maximum}))
        failed |= item_failed
        incomplete |= item_incomplete
        matrix.append({"componentItemId": _id(item, index), "certificateId": certificate.get("certificateId"), "comparisons": comparisons, "result": "failed" if item_failed else "evidence_insufficient" if item_incomplete else "passed"})
    output = result("evaluate_r16_quality_certificate_results", _aggregate(failed, incomplete), facts={"numericResultMatrix": matrix}, checks=checks, rule_version=R16_RULE_VERSION)
    output["numericResultMatrix"] = matrix
    return output


def evaluate_r16_batch_traceability(arguments: dict[str, Any]) -> dict[str, Any]:
    design_items = _records(arguments.get("designItems"))
    certificates = _records(arguments.get("qualityCertificates"))
    if not design_items:
        return _insufficient("evaluate_r16_batch_traceability", "r16_design_items_missing")
    checks, matrix = [], []
    failed = incomplete = False
    for index, item in enumerate(design_items, 1):
        matches = _match_records(item, certificates)
        certificate = matches[0] if len(matches) == 1 else None
        design_trace = _first(item, "batchNo", "heatNo", "serialNo")
        cert_trace = _first(certificate or {}, "batchNo", "heatNo", "serialNo")
        physical_trace = _first(item, "physicalMarkBatchNo", "physicalHeatNo", "physicalMark")
        if not certificate or not design_trace or not cert_trace:
            incomplete = True
            status = "evidence_insufficient"
        elif not _same(design_trace, cert_trace):
            failed = True
            status = "failed"
        elif physical_trace is None:
            incomplete = True
            status = "evidence_insufficient"
        elif not _same(cert_trace, physical_trace):
            failed = True
            status = "failed"
        else:
            status = "passed"
        checks.append(check(f"component_{index}_batch_traceable", status == "passed", {"design": design_trace, "certificate": cert_trace, "physicalMark": physical_trace}, "same_batch_heat_or_serial_identity"))
        matrix.append({"componentItemId": _id(item, index), "certificateId": (certificate or {}).get("certificateId"), "result": status})
    output = result("evaluate_r16_batch_traceability", _aggregate(failed, incomplete), facts={"traceabilityMatrix": matrix}, checks=checks, rule_version=R16_RULE_VERSION)
    output["traceabilityMatrix"] = matrix
    return output


def _evaluate_design_matches(arguments: dict[str, Any], tool_name: str) -> dict[str, Any]:
    design_items, certificates = _records(arguments.get("designItems")), _records(arguments.get("qualityCertificates"))
    if not design_items:
        return _insufficient(tool_name, "r16_design_items_missing")
    fields = ("manufacturerName", "productName", "specification", "materialGrade", "standardRef", "deliveryCondition")
    matrix, checks = [], []
    failed = incomplete = False
    for index, item in enumerate(design_items, 1):
        matches = _match_records(item, certificates)
        if not matches:
            failed = True
            matrix.append({"componentItemId": _id(item, index), "result": "failed", "reasonCodes": ["quality_certificate_missing"]})
            continue
        certificate = matches[0]
        mismatches, missing = [], []
        for field in fields:
            expected = _first(item, field, _design_alias(field))
            actual = _first(certificate, field, _certificate_alias(field))
            if not _present(expected) or not _present(actual):
                missing.append(field)
            elif not _same(expected, actual):
                mismatches.append(field)
            checks.append(check(f"component_{index}_{_safe(field)}_match", _present(expected) and _present(actual) and _same(expected, actual), actual, expected))
        if mismatches:
            failed = True
            status = "failed"
        elif missing:
            incomplete = True
            status = "evidence_insufficient"
        else:
            status = "passed"
        matrix.append({"componentItemId": _id(item, index), "certificateId": certificate.get("certificateId"), "mismatchedFields": mismatches, "missingComparisonFields": missing, "result": status})
    output = result(tool_name, _aggregate(failed, incomplete), facts={"designMatchMatrix": matrix}, checks=checks, rule_version=R16_RULE_VERSION)
    output["designMatchMatrix"] = matrix
    return output


def _match_records(item: dict[str, Any], records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    strong = (("batchNo", "heatNo", "serialNo"), ("componentItemId",))
    for fields in strong:
        values = [_first(item, field) for field in fields]
        if any(_present(value) for value in values):
            matches = [record for record in records if any(_present(value) and _same(value, _first(record, field)) for field, value in zip(fields, values))]
            if matches:
                return matches
    return [record for record in records if _same(_first(item, "productName", "componentType"), _first(record, "productName", "componentType")) and _same(_first(item, "specification"), _first(record, "specification"))]


def _unique_batch_match(item: dict[str, Any], matches: list[dict[str, Any]]) -> bool:
    batch = _first(item, "batchNo", "heatNo", "serialNo")
    return bool(batch) and sum(1 for record in matches if _same(batch, _first(record, "batchNo", "heatNo", "serialNo"))) == 1


def _identity_ready(item: dict[str, Any]) -> bool:
    return _present(_first(item, "productName", "componentType")) and (_present(item.get("specification")) or _present(_first(item, "batchNo", "heatNo", "serialNo")))


def _result_map(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return {_norm(key): item for key, item in value.items()}
    return {_norm(item.get("itemCode") or item.get("name")): item.get("value") for item in _records(value)}


def _contains_test(actual: set[str], required: str) -> bool:
    aliases = {
        "chemical_composition": ("chemicalcomposition", "chemistry", "化学成分"),
        "mechanical_properties": ("mechanicalproperties", "力学性能", "tensiletest", "拉伸"),
        "tensile_test": ("tensiletest", "拉伸", "mechanicalproperties", "力学性能"),
        "impact_test": ("impacttest", "冲击"),
        "hydrostatic_or_ndt": ("hydrostatic", "pressuretest", "水压", "液压", "ndt", "无损"),
        "weld_ndt": ("weldndt", "焊缝无损", "ndt", "无损"),
        "flattening_or_flaring": ("flattening", "flaring", "压扁", "扩口"),
        "inspection_and_test": ("inspectionandtest", "检验试验", "出厂检验"),
    }
    markers = aliases.get(required, (_norm(required),))
    return any(any(marker in candidate for marker in markers) for candidate in actual)


def _certificate_alias(field: str) -> str:
    return {"standardRef": "standardNo", "materialGrade": "material", "deliveryCondition": "supplyCondition", "conclusion": "inspectionConclusion"}.get(field, field)


def _design_alias(field: str) -> str:
    return {"standardRef": "acceptanceStandard", "materialGrade": "material", "deliveryCondition": "supplyCondition", "productName": "componentType"}.get(field, field)


def _records(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _first(value: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if _present(value.get(key)):
            return value[key]
    return None


def _present(value: Any) -> bool:
    return value not in (None, "", [], {})


def _same(left: Any, right: Any) -> bool:
    return bool(_present(left) and _present(right) and _norm(left) == _norm(right))


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", str(value or "").lower())


def _safe(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_") or "item"


def _string_set(value: Any) -> set[str]:
    if isinstance(value, str):
        value = re.split(r"[,，;；、\n]", value)
    return {_norm(item) for item in (value or []) if _present(item)} if isinstance(value, (list, tuple, set)) else set()


def _truth(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    normalized = _norm(value)
    if normalized in {"true", "yes", "present", "有", "是", "已盖章", "存在"}:
        return True
    if normalized in {"false", "no", "missing", "无", "否", "未盖章", "缺失"}:
        return False
    return None


def _accepted(value: Any) -> bool:
    normalized = _norm(value)
    return any(_norm(item) in normalized for item in _PASS)


def _id(item: dict[str, Any], index: int) -> str:
    return str(item.get("componentItemId") or item.get("itemId") or f"R16-ITEM-{index}")


def _aggregate(failed: bool, incomplete: bool) -> str:
    return "failed" if failed else "evidence_insufficient" if incomplete else "passed"


def _insufficient(tool_name: str, reason: str) -> dict[str, Any]:
    output = result(tool_name, "evidence_insufficient", facts={}, checks=[], rule_version=R16_RULE_VERSION)
    output["warnings"] = [reason]
    return output
