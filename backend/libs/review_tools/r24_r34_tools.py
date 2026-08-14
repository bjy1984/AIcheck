from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from decimal import Decimal
from typing import Any

from libs.review_orchestrator.deterministic_tools import (
    check,
    check_welder_work_coverage,
    decimal,
    parse_date,
    result,
)

R25_VERSION = "r25-wps-pqr-nbt47014-2023-v1"
R26_VERSION = "r26-consumable-mtc-nbt47018-product-standard-v1"
R27_VERSION = "r27-consumable-control-gbt20801.1-2025-jbt3223-v1"
R28_VERSION = "r28-pipe-fit-up-gbt20801.1-2025-gb50236-v1"
R29_VERSION = "r29-welding-record-linked-r24-r25-v1"
R30_VERSION = "r30-weld-appearance-gbt20801.1-2025-table43-v1"
R31_VERSION = "r31-weld-repair-gbt20801.1-2025-7.4.11-v1"
PWHT_VERSION = "pwht-applicability-gbt20801.1-2025-table36-v1"
R32_VERSION = "r32-pwht-procedure-gbt20801.1-2025-v1"
R33_VERSION = "r33-pwht-instruments-calibration-v1"
R34_VERSION = "r34-pwht-result-hardness-gbt20801.1-2025-v1"


def check_wps_pqr_coverage(arguments: dict[str, Any]) -> dict[str, Any]:
    process_type = _norm(arguments.get("processType") or "welding")
    if process_type in {"bonding", "粘接", "adhesivebonding"}:
        if arguments.get("bondingRuleProfileVerified") is not True:
            return _insufficient(
                "check_wps_pqr_coverage",
                "bonding_standard_rule_profile_not_verified",
                R25_VERSION,
                arguments,
            )
        wps_items = _records(arguments.get("bondingProcedureSpecifications") or arguments.get("wpsItems"))
        pqr_items = _records(arguments.get("bondingProcedureQualifications") or arguments.get("pqrItems"))
    else:
        wps_items = _records(arguments.get("wpsItems") or arguments.get("procedureSpecifications"))
        pqr_items = _records(arguments.get("pqrItems") or arguments.get("qualifiedRanges"))
    work_items = _records(arguments.get("workItems") or arguments.get("pipelineItems"))
    if not wps_items or not pqr_items or not work_items:
        return _insufficient("check_wps_pqr_coverage", "wps_pqr_or_actual_work_missing", R25_VERSION, arguments)

    matrix: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    failed = incomplete = False
    for index, work in enumerate(work_items, 1):
        candidates = [wps for wps in wps_items if _same_if_present(wps, work, "weldingMethod", "method")]
        actual_wps_no = _first(work, "wpsNo", "procedureNo")
        if _present(actual_wps_no):
            candidates = [wps for wps in candidates if _norm(_first(wps, "wpsNo", "documentNo", "id")) == _norm(actual_wps_no)]
        if not candidates:
            failed = True
            matrix.append({"workItemId": _id(work, index), "result": "failed", "reasonCodes": ["covering_wps_missing"]})
            checks.append(check(f"work_{index}_covering_wps", False, [], "covering_approved_wps"))
            continue
        work_failed = work_incomplete = False
        reasons: list[str] = []
        matched_wps: list[str] = []
        for wps in candidates:
            wps_no = str(_first(wps, "wpsNo", "documentNo", "id") or "")
            pqr_no = str(_first(wps, "pqrNo", "supportingPqrNo", "qualificationNo") or "")
            matched_pqrs = [pqr for pqr in pqr_items if pqr_no and _norm(_first(pqr, "pqrNo", "reportNo", "id")) == _norm(pqr_no)]
            approved = _bool(_first(wps, "approved", "approvalCompleted"))
            pqr_approved = any(_bool(_first(pqr, "approved", "approvalCompleted")) is True for pqr in matched_pqrs)
            if approved is False or pqr_no and not matched_pqrs:
                work_failed = True
                reasons.append("wps_not_approved_or_pqr_link_broken")
                continue
            if approved is None or not pqr_no or not matched_pqrs or not pqr_approved:
                work_incomplete = True
                reasons.append("wps_pqr_approval_or_link_evidence_incomplete")
                continue
            pqr = next((item for item in matched_pqrs if _bool(_first(item, "approved", "approvalCompleted")) is True), matched_pqrs[0])
            range_status, range_reasons = _wps_pqr_ranges(wps, pqr, work)
            reasons.extend(range_reasons)
            if range_status == "failed":
                work_failed = True
            elif range_status == "evidence_insufficient":
                work_incomplete = True
            else:
                matched_wps.append(wps_no)
        status = "passed" if matched_wps else "failed" if work_failed else "evidence_insufficient" if work_incomplete else "failed"
        failed |= status == "failed"
        incomplete |= status == "evidence_insufficient"
        checks.append(check(f"work_{index}_wps_pqr_and_range_coverage", status == "passed", matched_wps, "approved_linked_and_covering"))
        matrix.append({"workItemId": _id(work, index), "matchedWpsNos": matched_wps, "result": status, "reasonCodes": list(dict.fromkeys(reasons))})
    return _output("check_wps_pqr_coverage", failed, incomplete, {"processType": process_type, "wpsPqrCoverageMatrix": matrix}, checks, R25_VERSION)


def evaluate_welding_consumable(arguments: dict[str, Any]) -> dict[str, Any]:
    certificates = _records(arguments.get("qualityCertificates") or arguments.get("certificates"))
    requirements = _records(arguments.get("designRequirements") or arguments.get("requiredConsumables"))
    physical = _records(arguments.get("physicalItems") or arguments.get("receiptItems"))
    profiles = arguments.get("productStandardProfiles") if isinstance(arguments.get("productStandardProfiles"), dict) else {}
    if not certificates or not requirements:
        return _insufficient("evaluate_welding_consumable", "consumable_certificate_or_design_requirement_missing", R26_VERSION, arguments)
    matrix, checks = [], []
    failed = incomplete = False
    for index, required in enumerate(requirements, 1):
        matches = [cert for cert in certificates if _match_consumable(required, cert)]
        if not matches:
            failed = True
            checks.append(check(f"consumable_{index}_certificate", False, [], "matching_mtc"))
            matrix.append({"itemId": _id(required, index), "result": "failed", "reasonCodes": ["matching_mtc_missing"]})
            continue
        cert = matches[0]
        reasons: list[str] = []
        explicit = False
        missing = False
        standard_ref = _first(cert, "standardRef", "productStandard") or _first(required, "standardRef", "productStandard")
        chemistry = _measurement_map(cert.get("chemicalComposition"))
        mechanics = _measurement_map(cert.get("mechanicalProperties"))
        original_seen = _bool(_first(cert, "originalSeen", "originalVerified"))
        verified_copy = _bool(_first(cert, "verifiedCopy", "copyVerified"))
        if original_seen is not True and verified_copy is not True:
            missing = True
            reasons.append("mtc_original_or_verified_copy_evidence_missing")
        if verified_copy is True:
            supplier_seal = _bool(_first(cert, "supplierInspectionSealPresent", "supplierSealPresent"))
            handler_signed = _bool(_first(cert, "handlerSigned", "responsiblePersonSigned"))
            if supplier_seal is False or handler_signed is False:
                explicit = True
                reasons.append("mtc_copy_supplier_seal_or_handler_signature_failed")
            elif supplier_seal is not True or handler_signed is not True:
                missing = True
                reasons.append("mtc_copy_supplier_seal_or_handler_signature_missing")
        conclusion = _first(cert, "conclusion", "inspectionConclusion")
        if _present(conclusion) and not _accepted(conclusion):
            explicit = True
            reasons.append("mtc_conclusion_not_accepted")
        if not chemistry:
            missing = True
            reasons.append("chemical_composition_missing")
        if not mechanics:
            missing = True
            reasons.append("mechanical_properties_missing")
        profile = profiles.get(_standard_key(standard_ref)) if standard_ref else None
        if profile is None:
            missing = True
            reasons.append("product_standard_limit_profile_missing")
        else:
            for group_name, values in (("chemicalComposition", chemistry), ("mechanicalProperties", mechanics)):
                for field, limits in dict(profile.get(group_name) or {}).items():
                    value = decimal(values.get(field))
                    if value is None:
                        missing = True
                        reasons.append(f"{group_name}_{field}_missing")
                    elif not _within_limits(value, limits):
                        explicit = True
                        reasons.append(f"{group_name}_{field}_out_of_range")
        batch = _first(cert, "batchNo", "lotNo")
        matching_physical = [item for item in physical if batch and _norm(_first(item, "batchNo", "lotNo")) == _norm(batch)]
        if physical and not matching_physical:
            explicit = True
            reasons.append("physical_batch_not_traceable_to_mtc")
        elif not physical:
            missing = True
            reasons.append("physical_batch_evidence_missing")
        expiry = parse_date(_first(cert, "stockValidUntil", "inventoryValidUntil", "expiryDate"))
        use_date = parse_date(_first(required, "useDate") or arguments.get("reviewDate"))
        if expiry and use_date and expiry < use_date:
            retested = _bool(_first(cert, "retestQualified", "expiredStockRetestQualified"))
            if retested is False:
                explicit = True
                reasons.append("expired_stock_retest_failed")
            elif retested is not True:
                missing = True
                reasons.append("expired_stock_retest_evidence_missing")
        status = "failed" if explicit else "evidence_insufficient" if missing else "passed"
        failed |= explicit
        incomplete |= missing and not explicit
        checks.append(check(f"consumable_{index}_mtc_and_traceability", status == "passed", _id(cert, index), "qualified_and_batch_traceable"))
        matrix.append({"itemId": _id(required, index), "certificateId": _id(cert, index), "standardRef": standard_ref, "result": status, "reasonCodes": list(dict.fromkeys(reasons))})
    return _output("evaluate_welding_consumable", failed, incomplete, {"consumableCertificateMatrix": matrix}, checks, R26_VERSION)


def evaluate_welding_consumable_control(arguments: dict[str, Any]) -> dict[str, Any]:
    records = _records(arguments.get("managementRecords") or arguments.get("records"))
    requirements = arguments.get("controlRequirements") if isinstance(arguments.get("controlRequirements"), dict) else {}
    if not records:
        return _insufficient("evaluate_welding_consumable_control", "consumable_management_records_missing", R27_VERSION, arguments)
    kinds = {_record_kind(record): record for record in records}
    required_kinds = ("acceptance", "storage", "drying", "issue", "use", "return")
    checks, reasons = [], []
    failed = incomplete = False
    if not requirements:
        incomplete = True
        reasons.append("consumable_control_requirement_profile_missing")
    for kind in required_kinds:
        present = kind in kinds
        if not present:
            incomplete = True
            reasons.append(f"{kind}_record_missing")
        checks.append(check(f"{kind}_record_present", present, present, True))
    for field in ("temperature", "humidity", "dryingTemperature", "dryingMinutes"):
        if requirements.get(field) is not None and not any(_present(record.get(field)) for record in records):
            incomplete = True
            reasons.append(f"{field}_recorded_value_missing")
    for index, record in enumerate(records, 1):
        conclusion = _first(record, "conclusion", "result")
        if _present(conclusion) and not _accepted(conclusion):
            failed = True
            reasons.append(f"record_{index}_conclusion_not_accepted")
        expired = _bool(_first(record, "expired", "isExpired"))
        mixed = _bool(_first(record, "mixedUse", "materialMixing"))
        if expired is True or mixed is True:
            failed = True
            reasons.append("expired_or_mixed_consumable_used")
        for field, spec in (("temperature", requirements.get("temperature")), ("humidity", requirements.get("humidity")), ("dryingTemperature", requirements.get("dryingTemperature")), ("dryingMinutes", requirements.get("dryingMinutes"))):
            if spec is None or not _present(record.get(field)):
                continue
            if not _within_limits(decimal(record.get(field)), spec):
                failed = True
                reasons.append(f"{field}_out_of_range")
    trace_fields = ("batchNo", "materialGrade")
    ledgers = [record for record in records if _record_kind(record) in {"issue", "use", "return"}]
    if ledgers and any(not all(_present(_first(record, field)) for field in trace_fields) for record in ledgers):
        incomplete = True
        reasons.append("issue_use_return_trace_fields_incomplete")
    return _output("evaluate_welding_consumable_control", failed, incomplete, {"recordKinds": sorted(kinds), "reasonCodes": list(dict.fromkeys(reasons))}, checks, R27_VERSION)


def evaluate_pipe_fit_up(arguments: dict[str, Any]) -> dict[str, Any]:
    records = _records(arguments.get("fitUpRecords") or arguments.get("records"))
    if not records:
        return _insufficient("evaluate_pipe_fit_up", "pipe_fit_up_records_missing", R28_VERSION, arguments)
    matrix, checks = [], []
    failed = incomplete = False
    for index, record in enumerate(records, 1):
        thickness = decimal(_first(record, "thickness", "wallThickness"))
        misalignment = decimal(_first(record, "misalignment", "internalMisalignment", "错边量"))
        material = _norm(_first(record, "materialGroup", "materialType", "material"))
        limit = _fit_up_limit(material, thickness)
        reasons: list[str] = []
        explicit = False
        missing = False
        if thickness is None or misalignment is None or limit is None:
            missing = True
            reasons.append("misalignment_limit_input_missing")
        elif misalignment > limit:
            explicit = True
            reasons.append("misalignment_exceeds_limit")
        wps_gap = _range(_first(record, "wpsGapRange", "gapRange"), record, "gapMin", "gapMax")
        gap = decimal(_first(record, "gap", "rootGap"))
        if gap is None or wps_gap is None:
            missing = True
            reasons.append("root_gap_or_wps_limit_missing")
        elif not _between(gap, *wps_gap):
            explicit = True
            reasons.append("root_gap_outside_wps_range")
        bevel = decimal(_first(record, "bevelAngle", "坡口角度"))
        bevel_range = _range(_first(record, "bevelAngleRange"), record, "bevelAngleMin", "bevelAngleMax")
        if bevel is None or bevel_range is None:
            missing = True
            reasons.append("bevel_angle_or_limit_missing")
        elif not _between(bevel, *bevel_range):
            explicit = True
            reasons.append("bevel_angle_outside_required_range")
        forced = _bool(_first(record, "forcedFitUp", "强力组对"))
        prestretch = _bool(_first(record, "designPrestretch", "设计预拉伸"))
        if forced is True and prestretch is not True:
            explicit = True
            reasons.append("forced_fit_up_not_allowed")
        elif forced is None:
            missing = True
            reasons.append("forced_fit_up_fact_missing")
        status = "failed" if explicit else "evidence_insufficient" if missing else "passed"
        failed |= explicit
        incomplete |= missing and not explicit
        checks.append(check(f"fit_up_{index}", status == "passed", {"misalignment": misalignment, "limit": limit, "gap": gap, "bevel": bevel}, "within_limits_and_no_forced_fit"))
        matrix.append({"jointId": _id(record, index), "misalignmentLimitMM": limit, "result": status, "reasonCodes": reasons})
    return _output("evaluate_pipe_fit_up", failed, incomplete, {"fitUpMatrix": matrix}, checks, R28_VERSION)


def evaluate_welding_process(arguments: dict[str, Any]) -> dict[str, Any]:
    records = _records(arguments.get("weldingRecords") or arguments.get("records"))
    if not records:
        return _insufficient("evaluate_welding_process", "welding_records_missing", R29_VERSION, arguments)
    welder_result = arguments.get("welderCoverageResult") if isinstance(arguments.get("welderCoverageResult"), dict) else None
    wps_result = arguments.get("wpsPqrCoverageResult") if isinstance(arguments.get("wpsPqrCoverageResult"), dict) else None
    if welder_result is None and (_records(arguments.get("certificates")) or arguments.get("qualificationCodes")):
        welder_result = check_welder_work_coverage(arguments)
    if wps_result is None and _records(arguments.get("wpsItems")) and _records(arguments.get("pqrItems")):
        wps_result = check_wps_pqr_coverage(arguments)
    matrix, checks = [], []
    failed = incomplete = False
    for index, record in enumerate(records, 1):
        missing = [field for field in ("weldNo", "welderCertificateNo", "weldingMethod", "current", "voltage", "weldingSpeed", "interpassTemperature") if not _present(_first(record, field))]
        marked = _present(_first(record, "weldMapRef", "weldMark", "steelStamp"))
        traceable = _bool(_first(record, "traceable", "identityTraceable"))
        reasons = [f"{field}_missing" for field in missing]
        explicit = traceable is False
        if explicit:
            reasons.append("weld_record_not_traceable")
        if not marked:
            reasons.append("weld_identification_missing")
        linked = (welder_result, wps_result)
        if any(item and item.get("result") == "failed" for item in linked):
            explicit = True
            reasons.append("r24_or_r25_linked_check_failed")
        linked_missing = any(item is None or item.get("result") not in {"passed", "failed"} for item in linked)
        if linked_missing:
            reasons.append("r24_or_r25_linked_result_missing")
        status = "failed" if explicit else "evidence_insufficient" if missing or not marked or traceable is None or linked_missing else "passed"
        failed |= status == "failed"
        incomplete |= status == "evidence_insufficient"
        checks.append(check(f"welding_record_{index}", status == "passed", _id(record, index), "complete_traceable_and_linked"))
        matrix.append({"weldNo": _first(record, "weldNo") or _id(record, index), "result": status, "reasonCodes": reasons})
    return _output("evaluate_welding_process", failed, incomplete, {"weldingRecordMatrix": matrix}, checks, R29_VERSION)


def evaluate_weld_appearance(arguments: dict[str, Any]) -> dict[str, Any]:
    records = _records(arguments.get("appearanceRecords") or arguments.get("records"))
    if not records:
        return _insufficient("evaluate_weld_appearance", "weld_appearance_records_missing", R30_VERSION, arguments)
    matrix, checks = [], []
    failed = incomplete = False
    for index, record in enumerate(records, 1):
        grade = _inspection_grade(_first(record, "inspectionGrade", "acceptanceGrade"))
        joint = _norm(_first(record, "jointType", "weldType"))
        thickness = decimal(_first(record, "thickness", "wallThickness"))
        reasons: list[str] = []
        explicit = False
        missing = False
        for defect in ("crack", "lackOfFusion", "surfacePore", "exposedSlag"):
            value = _bool(_first(record, defect))
            if value is True:
                explicit = True
                reasons.append(f"{defect}_present")
            elif value is None:
                missing = True
                reasons.append(f"{defect}_inspection_missing")
        undercut = decimal(_first(record, "undercutDepth", "undercut"))
        undercut_limit = _design_limit(record, "undercutMax")
        if undercut_limit is None:
            undercut_limit = _undercut_limit(grade, joint, thickness)
        if undercut is None or undercut_limit is None:
            missing = True
            reasons.append("undercut_value_or_applicable_limit_missing")
        elif undercut > undercut_limit:
            explicit = True
            reasons.append("undercut_exceeds_limit")
        reinforcement = decimal(_first(record, "reinforcement", "weldReinforcement"))
        reinforcement_limit = _design_limit(record, "reinforcementMax")
        if reinforcement_limit is None:
            reinforcement_limit = _reinforcement_limit(grade, thickness)
        if reinforcement is None or reinforcement_limit is None:
            missing = True
            reasons.append("reinforcement_value_or_limit_missing")
        elif reinforcement > reinforcement_limit:
            explicit = True
            reasons.append("reinforcement_exceeds_limit")
        width = decimal(_first(record, "width", "weldWidth"))
        width_range = _range(_first(record, "widthRange", "designWidthRange", "wpsWidthRange"), record, "widthMin", "widthMax")
        if width is None or width_range is None:
            missing = True
            reasons.append("weld_width_or_design_wps_limit_missing")
        elif not _between(width, *width_range):
            explicit = True
            reasons.append("weld_width_outside_design_wps_range")
        photo_required = _bool(arguments.get("photoRequired")) is True
        if photo_required and not _present(_first(record, "photoRef", "imageEvidenceRef")):
            missing = True
            reasons.append("required_photo_missing")
        status = "failed" if explicit else "evidence_insufficient" if missing else "passed"
        failed |= explicit
        incomplete |= missing and not explicit
        checks.append(check(f"appearance_{index}", status == "passed", _id(record, index), "GBT20801.1_table43_and_design_wps"))
        matrix.append({"weldNo": _first(record, "weldNo") or _id(record, index), "inspectionGrade": grade, "undercutLimitMM": undercut_limit, "reinforcementLimitMM": reinforcement_limit, "result": status, "reasonCodes": reasons})
    return _output("evaluate_weld_appearance", failed, incomplete, {"appearanceMatrix": matrix}, checks, R30_VERSION)


def evaluate_weld_repair(arguments: dict[str, Any]) -> dict[str, Any]:
    repairs = _records(arguments.get("repairRecords") or arguments.get("records"))
    if not repairs:
        return result("evaluate_weld_repair", "not_applicable", facts={"repairOccurred": False}, checks=[], rule_version=R31_VERSION) if _bool(arguments.get("repairOccurred")) is False else _insufficient("evaluate_weld_repair", "repair_occurrence_or_records_missing", R31_VERSION, arguments)
    matrix, checks = [], []
    failed = incomplete = False
    for index, repair in enumerate(repairs, 1):
        count = _integer(_first(repair, "sameLocationRepairCount", "repairCount"))
        required = (
            "repairApplicationNo",
            "repairProcedureNo",
            "causeAnalysis",
            "originalInspectionMethod",
            "postRepairNdtReportNo",
            "postRepairNdtMethod",
            "postRepairNdtResult",
        )
        missing = [field for field in required if not _present(_first(repair, field))]
        reasons = [f"{field}_missing" for field in missing]
        explicit = _present(_first(repair, "postRepairNdtResult")) and not _accepted(_first(repair, "postRepairNdtResult"))
        if explicit:
            reasons.append("post_repair_ndt_not_accepted")
        procedure_approved = _bool(_first(repair, "repairProcedureApproved", "procedureApproved"))
        if procedure_approved is False:
            explicit = True
            reasons.append("repair_procedure_not_approved")
        elif procedure_approved is not True:
            missing.append("repairProcedureApproved")
            reasons.append("repair_procedure_approval_missing")
        original_method = _norm(_first(repair, "originalInspectionMethod"))
        post_method = _norm(_first(repair, "postRepairNdtMethod"))
        if original_method and post_method and original_method != post_method:
            explicit = True
            reasons.append("post_repair_ndt_method_differs_from_original")
        if count is None:
            missing.append("sameLocationRepairCount")
            reasons.append("same_location_repair_count_missing")
        elif count > 2:
            special = _bool(_first(repair, "revisedSpecialMeasures", "specialPlanApproved"))
            technical = _bool(_first(repair, "technicalHeadApproved"))
            if special is False or technical is False:
                explicit = True
                reasons.append("over_two_repairs_special_approval_failed")
            elif special is not True or technical is not True:
                missing.append("overTwoRepairApproval")
                reasons.append("over_two_repairs_special_approval_missing")
        after_pwht = _bool(_first(repair, "performedAfterPwht"))
        if after_pwht is True:
            re_pwht = _bool(_first(repair, "repeatPwhtCompleted"))
            if re_pwht is False:
                explicit = True
                reasons.append("repair_after_pwht_without_repeat_pwht")
            elif re_pwht is not True:
                missing.append("repeatPwhtCompleted")
                reasons.append("repeat_pwht_evidence_missing")
        status = "failed" if explicit else "evidence_insufficient" if missing else "passed"
        failed |= explicit
        incomplete |= bool(missing) and not explicit
        checks.append(check(f"repair_{index}", status == "passed", _id(repair, index), "approved_procedure_and_qualified_post_ndt"))
        matrix.append({"weldNo": _first(repair, "weldNo") or _id(repair, index), "sameLocationRepairCount": count, "result": status, "reasonCodes": list(dict.fromkeys(reasons))})
    return _output("evaluate_weld_repair", failed, incomplete, {"repairMatrix": matrix}, checks, R31_VERSION)


def resolve_pwht_applicability(arguments: dict[str, Any]) -> dict[str, Any]:
    welds = _records(arguments.get("weldItems") or arguments.get("items"))
    if not welds:
        return _insufficient("resolve_pwht_applicability", "pwht_weld_items_missing", PWHT_VERSION, arguments)
    matrix, checks = [], []
    incomplete = False
    for index, weld in enumerate(welds, 1):
        resolved = _resolve_pwht_item(weld)
        incomplete |= resolved["result"] == "evidence_insufficient"
        checks.append(check(f"weld_{index}_pwht_applicability_resolved", resolved["result"] != "evidence_insufficient", resolved.get("required"), "true_or_false_with_rule_profile"))
        matrix.append(resolved)
    return result("resolve_pwht_applicability", "evidence_insufficient" if incomplete else "passed", facts={"pwhtApplicabilityMatrix": matrix}, checks=checks, rule_version=PWHT_VERSION)


def evaluate_heat_treatment(arguments: dict[str, Any]) -> dict[str, Any]:
    profile = _norm(arguments.get("profile") or arguments.get("evaluationProfile") or "heat_treatment_procedure")
    return _evaluate_heat_treatment_result(arguments) if profile in {"heattreatmentresult", "result", "r34"} else _evaluate_heat_treatment_procedure(arguments)


def evaluate_heat_treatment_instruments(arguments: dict[str, Any]) -> dict[str, Any]:
    records = _records(arguments.get("instrumentRecords") or arguments.get("records"))
    layouts = _records(arguments.get("temperaturePointLayouts") or arguments.get("layouts"))
    applicability = _pwht_applicability_from_arguments(arguments)
    if applicability is not None:
        if any(item.get("result") == "evidence_insufficient" for item in applicability):
            return _insufficient("evaluate_heat_treatment_instruments", "pwht_applicability_unresolved", R33_VERSION, arguments)
        if applicability and not any(item.get("required") is True for item in applicability):
            return result(
                "evaluate_heat_treatment_instruments",
                "not_applicable",
                facts={"pwhtApplicabilityMatrix": applicability},
                checks=[],
                rule_version=R33_VERSION,
            )
    if not records:
        return _insufficient("evaluate_heat_treatment_instruments", "temperature_instrument_records_missing", R33_VERSION, arguments)
    review_date = parse_date(arguments.get("reviewDate")) or date.today()
    required_types = {"thermocouple", "controller", "recorder"}
    found_types: set[str] = set()
    checks, reasons = [], []
    failed = incomplete = False
    for index, record in enumerate(records, 1):
        instrument_type = _instrument_type(record)
        if instrument_type:
            found_types.add(instrument_type)
        cert_no = _first(record, "calibrationCertificateNo", "certificateNo")
        valid_until = parse_date(_first(record, "validUntil", "calibrationValidUntil"))
        if not cert_no or valid_until is None:
            incomplete = True
            reasons.append(f"instrument_{index}_calibration_evidence_incomplete")
        elif valid_until < review_date:
            failed = True
            reasons.append(f"instrument_{index}_calibration_expired")
        checks.append(check(f"instrument_{index}_calibration_valid", bool(cert_no) and valid_until is not None and valid_until >= review_date, {"certificateNo": cert_no, "validUntil": valid_until}, f">={review_date}"))
    missing_types = required_types - found_types
    if missing_types:
        incomplete = True
        reasons.append("required_instrument_types_missing")
    if not layouts:
        incomplete = True
        reasons.append("temperature_point_layout_missing")
    checks.append(check("temperature_point_layout_present", bool(layouts), len(layouts), ">=1"))
    return _output("evaluate_heat_treatment_instruments", failed, incomplete, {"instrumentTypes": sorted(found_types), "missingTypes": sorted(missing_types), "reasonCodes": reasons}, checks, R33_VERSION)


def _evaluate_heat_treatment_procedure(arguments: dict[str, Any]) -> dict[str, Any]:
    procedures = _records(arguments.get("procedureCards") or arguments.get("procedures"))
    qualifications = _records(arguments.get("qualificationReports") or arguments.get("pqrItems"))
    welds = _records(arguments.get("weldItems") or arguments.get("items"))
    if not welds:
        return _insufficient("evaluate_heat_treatment", "pwht_weld_items_missing", R32_VERSION, arguments)
    if not procedures:
        return _insufficient("evaluate_heat_treatment", "pwht_procedure_cards_missing", R32_VERSION, arguments)
    matrix, checks = [], []
    failed = incomplete = False
    for index, weld in enumerate(welds, 1):
        applicability = _resolve_pwht_item(weld)
        if applicability["result"] == "evidence_insufficient":
            incomplete = True
            matrix.append({**applicability, "procedureResult": "evidence_insufficient"})
            continue
        if not applicability["required"]:
            matrix.append({**applicability, "procedureResult": "not_applicable"})
            continue
        procedure = _match_by_weld(weld, procedures)
        if not procedure:
            failed = True
            checks.append(check(f"weld_{index}_procedure", False, None, "approved_covering_pwht_card"))
            matrix.append({**applicability, "procedureResult": "failed", "reasonCodes": ["covering_pwht_procedure_missing"]})
            continue
        reasons, explicit, missing = [], False, False
        if _bool(_first(procedure, "approved", "approvalCompleted")) is not True:
            missing = _bool(_first(procedure, "approved", "approvalCompleted")) is None
            explicit = not missing
            reasons.append("pwht_procedure_not_approved_or_unknown")
        qualification_no = _first(procedure, "qualificationReportNo", "pqrNo", "heatTreatmentEvaluationReportNo")
        if not _present(qualification_no):
            missing = True
            reasons.append("supporting_qualification_report_missing")
        else:
            matched_qualifications = [item for item in qualifications if _norm(_first(item, "pqrNo", "reportNo", "documentNo")) == _norm(qualification_no)]
            if not matched_qualifications:
                missing = True
                reasons.append("supporting_qualification_report_not_linked")
            elif not any(_bool(_first(item, "approved", "approvalCompleted")) is True for item in matched_qualifications):
                missing = True
                reasons.append("supporting_qualification_approval_evidence_missing")
        rule = applicability.get("ruleProfile") or {}
        for field in ("heatingRate", "holdingTemperature", "holdingMinutes", "coolingRate"):
            if not _present(_first(procedure, field)):
                missing = True
                reasons.append(f"{field}_missing")
        hold_temp = decimal(_first(procedure, "holdingTemperature"))
        if hold_temp is not None and not _within_limits(hold_temp, {"min": rule.get("temperatureMinC"), "max": rule.get("temperatureMaxC")}):
            explicit = True
            reasons.append("holding_temperature_outside_table36_range")
        heat_rate = decimal(_first(procedure, "heatingRate"))
        cool_rate = decimal(_first(procedure, "coolingRate"))
        thickness = decimal(_first(weld, "governingThickness", "thickness", "wallThickness"))
        heat_treatment_thickness = decimal(_first(weld, "heatTreatmentThickness", "pwhtThickness")) or thickness
        hold_minutes = decimal(_first(procedure, "holdingMinutes"))
        minimum_hold = _minimum_hold_minutes(heat_treatment_thickness, rule)
        if hold_minutes is not None and minimum_hold is not None and hold_minutes < minimum_hold:
            explicit = True
            reasons.append("holding_time_below_table36_minimum")
        if thickness and thickness > 0:
            heat_max = min(Decimal(205) * Decimal(25) / thickness, Decimal(205))
            cool_max = min(Decimal(260) * Decimal(25) / thickness, Decimal(260))
            if heat_rate is not None and heat_rate > heat_max:
                explicit = True
                reasons.append("heating_rate_exceeds_7.6.4_limit")
            if cool_rate is not None and cool_rate > cool_max:
                explicit = True
                reasons.append("cooling_rate_exceeds_7.6.4_limit")
        status = "failed" if explicit else "evidence_insufficient" if missing else "passed"
        failed |= explicit
        incomplete |= missing and not explicit
        checks.append(check(f"weld_{index}_pwht_procedure", status == "passed", _id(procedure, index), "approved_qualified_and_within_profile"))
        matrix.append({**applicability, "procedureResult": status, "reasonCodes": reasons})
    return _output("evaluate_heat_treatment", failed, incomplete, {"pwhtProcedureMatrix": matrix}, checks, R32_VERSION)


def _evaluate_heat_treatment_result(arguments: dict[str, Any]) -> dict[str, Any]:
    reports = _records(arguments.get("heatTreatmentReports") or arguments.get("reports"))
    hardness_reports = _records(arguments.get("hardnessReports"))
    welds = _records(arguments.get("weldItems") or arguments.get("items"))
    if not welds:
        return _insufficient("evaluate_heat_treatment", "pwht_weld_items_missing", R34_VERSION, arguments)
    matrix, checks = [], []
    failed = incomplete = False
    for index, weld in enumerate(welds, 1):
        applicability = _resolve_pwht_item(weld)
        if applicability["result"] == "evidence_insufficient":
            incomplete = True
            matrix.append({**applicability, "resultReview": "evidence_insufficient"})
            continue
        if not applicability["required"]:
            matrix.append({**applicability, "resultReview": "not_applicable"})
            continue
        report = _match_by_weld(weld, reports)
        hardness = _match_by_weld(weld, hardness_reports)
        reasons, explicit, missing = [], False, False
        if not report:
            missing = True
            reasons.append("heat_treatment_report_missing")
        else:
            if _bool(_first(report, "curveContinuous", "curveCompleteNoInterruption")) is False:
                explicit = True
                reasons.append("temperature_time_curve_interrupted")
            elif _bool(_first(report, "curveContinuous", "curveCompleteNoInterruption")) is None:
                missing = True
                reasons.append("curve_continuity_fact_missing")
            if not _present(_first(report, "curveRef", "temperatureTimeCurve")):
                missing = True
                reasons.append("temperature_time_curve_missing")
            parameter_status, parameter_reasons = _pwht_parameter_status(
                weld,
                report,
                applicability.get("ruleProfile") or {},
            )
            reasons.extend(parameter_reasons)
            explicit |= parameter_status == "failed"
            missing |= parameter_status == "evidence_insufficient"
        if not hardness:
            missing = True
            reasons.append("hardness_report_missing")
        else:
            hstatus, hreasons = _hardness_status(weld, hardness, applicability.get("ruleProfile") or {})
            reasons.extend(hreasons)
            explicit |= hstatus == "failed"
            missing |= hstatus == "evidence_insufficient"
        status = "failed" if explicit else "evidence_insufficient" if missing else "passed"
        failed |= explicit
        incomplete |= missing and not explicit
        checks.append(check(f"weld_{index}_pwht_result", status == "passed", _id(weld, index), "continuous_curve_and_qualified_hardness"))
        matrix.append({**applicability, "resultReview": status, "reasonCodes": reasons})
    return _output("evaluate_heat_treatment", failed, incomplete, {"pwhtResultMatrix": matrix}, checks, R34_VERSION)


def _resolve_pwht_item(weld: dict[str, Any]) -> dict[str, Any]:
    weld_id = _first(weld, "weldNo", "jointNo", "id")
    thickness = decimal(_first(weld, "governingThickness", "thickness", "wallThickness"))
    group = _material_group(weld)
    tensile = decimal(_first(weld, "specifiedMinimumTensileStrength", "tensileStrength"))
    carbon = decimal(_first(weld, "carbonPercent", "carbonContent"))
    cr = decimal(_first(weld, "chromiumPercent", "chromiumContent"))
    override = _bool(_first(weld, "designPwhtRequired", "pwhtRequiredByDesign"))
    key_payload = {"weldId": weld_id, "materialGroup": group, "thickness": str(thickness), "tensile": str(tensile), "carbon": str(carbon), "chromium": str(cr)}
    application_key = hashlib.sha256(json.dumps(key_payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:20]
    base = {"weldId": weld_id, "applicabilityKey": application_key, "materialGroup": group, "governingThicknessMM": thickness}
    if override is not None:
        profile = _pwht_profile(group, carbon, cr)
        return {**base, "required": override, "basis": "design_override", "ruleProfile": profile, "result": "passed"}
    if thickness is None or not group:
        return {**base, "required": None, "basis": "classification_inputs_missing", "ruleProfile": None, "result": "evidence_insufficient"}
    exception = _pwht_exception(weld, group, thickness, tensile)
    if exception is True:
        return {**base, "required": False, "basis": "7.6.3.2_joint_exception", "ruleProfile": _pwht_profile(group, carbon, cr), "result": "passed"}
    if exception is None and _bool(_first(weld, "jointExceptionClaimed")) is True:
        return {**base, "required": None, "basis": "joint_exception_evidence_incomplete", "ruleProfile": None, "result": "evidence_insufficient"}
    required: bool | None
    if group == "carbon_manganese":
        required = thickness > 25
    elif group == "low_alloy_cr_le_0_5":
        required = True if thickness > 20 else None if tensile is None else tensile > 490
    elif group == "low_alloy_cr_0_5_to_2":
        required = True if thickness > 13 else None if tensile is None else tensile > 490
    elif group == "low_alloy_cr_2_to_3_low_c":
        required = thickness > 13
    elif group in {"low_alloy_cr_3_to_10_or_high_c", "nine_cr_one_mo_v", "martensitic_stainless"}:
        required = True
    elif group in {"ferritic_stainless", "austenitic_stainless", "nickel_alloy", "duplex_stainless"}:
        required = False
    elif group == "low_temperature_ni_le_4":
        required = thickness > 20
    elif group == "low_temperature_ni_5_8_9":
        required = thickness > 51
    else:
        required = None
    if required is None:
        return {**base, "required": None, "basis": "unsupported_material_group", "ruleProfile": None, "result": "evidence_insufficient"}
    return {**base, "required": required, "basis": "GBT20801.1-2025_table36", "ruleProfile": _pwht_profile(group, carbon, cr), "result": "passed"}


def _pwht_profile(group: str | None, carbon: Decimal | None, chromium: Decimal | None) -> dict[str, Any]:
    profiles: dict[str, dict[str, Any]] = {
        "carbon_manganese": {"temperatureMinC": 595, "temperatureMaxC": 650, "holdHoursPer25MM": 1, "holdFloorMinutes": 60, "hardnessMode": "design_conditional", "conditionalMaxHBW": 200},
        "low_alloy_cr_le_0_5": {"temperatureMinC": 595, "temperatureMaxC": 650, "holdHoursPer25MM": 1, "holdFloorMinutes": 60, "hardnessMode": "table_limit", "maxHBW": 225},
        "low_alloy_cr_0_5_to_2": {"temperatureMinC": 650, "temperatureMaxC": 705, "holdHoursPer25MM": 1, "holdFloorMinutes": 60, "hardnessMode": "table_limit", "maxHBW": 225},
        "low_alloy_cr_2_to_3_low_c": {"temperatureMinC": 675, "temperatureMaxC": 760, "holdHoursPer25MM": 1, "holdFloorMinutes": 120, "hardnessMode": "table_limit", "maxHBW": 241},
        "low_alloy_cr_3_to_10_or_high_c": {"temperatureMinC": 675, "temperatureMaxC": 760, "holdHoursPer25MM": 1, "holdFloorMinutes": 120, "hardnessMode": "table_limit", "maxHBW": 241},
        "nine_cr_one_mo_v": {"temperatureMinC": 730, "temperatureMaxC": 775, "holdHoursPer25MM": 1, "holdFloorMinutes": 120, "holdSchedule": "nine_cr", "hardnessMode": "table_limit", "maxHBW": 250, "weldMinHBW": 185},
        "martensitic_stainless": {"temperatureMinC": 760, "temperatureMaxC": 800, "holdHoursPer25MM": 1, "holdFloorMinutes": 120, "hardnessMode": "table_limit", "maxHBW": 241},
        "ferritic_stainless": {"hardnessMode": "base_125_percent"},
        "austenitic_stainless": {"hardnessMode": "design_conditional", "conditionalMaxHBW": 187},
        "nickel_alloy": {"hardnessMode": "design_conditional", "conditionalMaxHBW": 187},
        "low_temperature_ni_le_4": {"temperatureMinC": 595, "temperatureMaxC": 650, "holdHoursPer25MM": 0.5, "holdFloorMinutes": 60, "hardnessMode": "base_125_percent"},
        "low_temperature_ni_5_8_9": {"temperatureMinC": 550, "temperatureMaxC": 585, "holdHoursPer25MM": 1, "holdFloorMinutes": 60, "hardnessMode": "base_125_percent"},
    }
    return profiles.get(group or "", {"hardnessMode": "unresolved"})


def _minimum_hold_minutes(thickness: Decimal | None, profile: dict[str, Any]) -> Decimal | None:
    rate = decimal(profile.get("holdHoursPer25MM"))
    floor = decimal(profile.get("holdFloorMinutes"))
    if thickness is None or thickness <= 0 or rate is None or floor is None:
        return None
    if profile.get("holdSchedule") == "nine_cr":
        if thickness <= 125:
            return max(thickness / Decimal(25) * Decimal(60), floor)
        increments = ((thickness - Decimal(125)) / Decimal(25)).to_integral_value(rounding="ROUND_CEILING")
        return Decimal(300) + increments * Decimal(15)
    if thickness <= 50:
        return max(thickness / Decimal(25) * Decimal(60) * rate, floor)
    increments = ((thickness - Decimal(50)) / Decimal(25)).to_integral_value(rounding="ROUND_CEILING")
    return Decimal(120) + increments * Decimal(15)


def _hardness_status(weld: dict[str, Any], report: dict[str, Any], profile: dict[str, Any]) -> tuple[str, list[str]]:
    readings = _records(report.get("readings"))
    if not readings:
        return "evidence_insufficient", ["hardness_readings_missing"]
    method = _norm(_first(report, "hardnessMethod", "scale"))
    if method not in {"hb", "hbw", "brinell", "布氏"}:
        if not _present(_first(report, "conversionStandardRef")) or any(decimal(_first(item, "convertedHBW")) is None for item in readings):
            return "evidence_insufficient", ["non_hbw_conversion_evidence_missing"]
        values = [decimal(_first(item, "convertedHBW")) for item in readings]
    else:
        values = [decimal(_first(item, "value", "hardness")) for item in readings]
    if any(value is None for value in values):
        return "evidence_insufficient", ["hardness_value_missing"]
    zones = {_norm(_first(item, "zone", "testZone")) for item in readings}
    if not any("weld" in zone or "焊缝" in zone for zone in zones) or not any("haz" in zone or "heataffected" in zone or "热影响" in zone for zone in zones):
        return "evidence_insufficient", ["weld_and_haz_hardness_locations_not_covered"]
    local = _bool(_first(report, "localHeatTreatment"))
    tested = decimal(_first(report, "testedJointCount"))
    lot = decimal(_first(report, "lotJointCount"))
    if tested is None or lot is None or lot <= 0:
        return "evidence_insufficient", ["hardness_sampling_count_missing"]
    required = lot if local is True else (lot * Decimal("0.10")).to_integral_value(rounding="ROUND_CEILING")
    if tested < required:
        return "failed", ["hardness_sampling_below_required_coverage"]
    design_limit = decimal(_first(weld, "designHardnessMaxHBW", "hardnessMaxHBW"))
    mode = profile.get("hardnessMode")
    limit = design_limit
    if limit is None and mode == "table_limit":
        limit = decimal(profile.get("maxHBW"))
    elif limit is None and mode == "design_conditional":
        return "evidence_insufficient", ["design_hardness_requirement_needed_for_conditional_table_entry"]
    elif limit is None and mode == "base_125_percent":
        base = decimal(_first(weld, "baseMaterialHardnessHBW"))
        if base is None:
            return "evidence_insufficient", ["base_material_hardness_missing_for_125_percent_rule"]
        limit = base * Decimal("1.25")
    if limit is None:
        return "evidence_insufficient", ["applicable_hardness_limit_unresolved"]
    if any(value > limit for value in values if value is not None):
        return "failed", ["hardness_exceeds_applicable_limit"]
    weld_min = decimal(profile.get("weldMinHBW"))
    weld_values = [value for value, item in zip(values, readings) if "weld" in _norm(_first(item, "zone", "testZone")) or "焊缝" in _norm(_first(item, "zone", "testZone"))]
    if weld_min is not None and any(value < weld_min for value in weld_values if value is not None):
        return "failed", ["weld_hardness_below_table_minimum"]
    return "passed", []


def _wps_pqr_ranges(wps: dict[str, Any], pqr: dict[str, Any], work: dict[str, Any]) -> tuple[str, list[str]]:
    reasons: list[str] = []
    failed = incomplete = False
    actual_parameter_record = _norm(_first(work, "recordKind")) == "weldingrecord" or any(
        _present(work.get(key)) for key in ("current", "voltage", "weldingSpeed", "interpassTemperature")
    )
    for aliases in (("weldingMethod", "method"), ("materialCategory", "materialGroup", "materialGrade", "baseMaterial")):
        wps_value = _first(wps, *aliases)
        pqr_value = _first(pqr, *aliases)
        actual_value = _first(work, *aliases)
        field = aliases[0]
        if not _present(wps_value) or not _present(pqr_value) or not _present(actual_value):
            incomplete = True
            reasons.append(f"{field}_wps_pqr_or_actual_missing")
        elif len({_norm(wps_value), _norm(pqr_value), _norm(actual_value)}) != 1:
            failed = True
            reasons.append(f"{field}_wps_pqr_actual_mismatch")
    for key in ("current", "voltage", "weldingSpeed", "interpassTemperature"):
        wps_range = _range(wps.get(f"{key}Range"), wps, f"{key}Min", f"{key}Max")
        pqr_range = _range(pqr.get(f"{key}QualifiedRange") or pqr.get(f"{key}Range"), pqr, f"{key}Min", f"{key}Max")
        actual = decimal(work.get(key))
        if wps_range is None or pqr_range is None:
            incomplete = True
            reasons.append(f"{key}_wps_or_pqr_range_missing")
            continue
        if not _range_within(wps_range, pqr_range):
            failed = True
            reasons.append(f"{key}_wps_outside_pqr_range")
        if actual is None and actual_parameter_record:
            incomplete = True
            reasons.append(f"actual_{key}_missing")
        elif actual is not None and not _between(actual, *wps_range):
            failed = True
            reasons.append(f"actual_{key}_outside_wps_range")
    thickness = decimal(_first(work, "thickness", "wallThickness"))
    qualified_thickness = _range(pqr.get("thicknessRange"), pqr, "thicknessMin", "thicknessMax")
    if thickness is None or qualified_thickness is None:
        incomplete = True
        reasons.append("actual_or_qualified_thickness_missing")
    elif not _between(thickness, *qualified_thickness):
        failed = True
        reasons.append("actual_thickness_not_covered_by_pqr")
    return ("failed" if failed else "evidence_insufficient" if incomplete else "passed"), reasons


def _fit_up_limit(material: str, thickness: Decimal | None) -> Decimal | None:
    if thickness is None or not material:
        return None
    if any(token in material for token in ("aluminum", "aluminium", "铝")):
        return Decimal("0.5") if thickness <= 5 else min(thickness * Decimal("0.10"), Decimal(2))
    if any(token in material for token in ("copper", "nickel", "titanium", "zirconium", "铜", "镍", "钛", "锆")):
        return min(thickness * Decimal("0.10"), Decimal(1))
    return min(thickness * Decimal("0.10"), Decimal(2))


def _pwht_parameter_status(weld: dict[str, Any], record: dict[str, Any], profile: dict[str, Any]) -> tuple[str, list[str]]:
    reasons: list[str] = []
    failed = incomplete = False
    thickness = decimal(_first(weld, "governingThickness", "thickness", "wallThickness"))
    heat_treatment_thickness = decimal(_first(weld, "heatTreatmentThickness", "pwhtThickness")) or thickness
    holding_temperature = decimal(_first(record, "holdingTemperature"))
    holding_minutes = decimal(_first(record, "holdingMinutes"))
    heating_rate = decimal(_first(record, "heatingRate"))
    cooling_rate = decimal(_first(record, "coolingRate"))
    for field, value in (
        ("holdingTemperature", holding_temperature),
        ("holdingMinutes", holding_minutes),
        ("heatingRate", heating_rate),
        ("coolingRate", cooling_rate),
    ):
        if value is None:
            incomplete = True
            reasons.append(f"actual_{field}_missing")
    temperature_min = decimal(profile.get("temperatureMinC"))
    temperature_max = decimal(profile.get("temperatureMaxC"))
    if temperature_min is None or temperature_max is None:
        incomplete = True
        reasons.append("holding_temperature_rule_profile_missing")
    elif holding_temperature is not None and not _between(holding_temperature, temperature_min, temperature_max):
        failed = True
        reasons.append("actual_holding_temperature_outside_table36_range")
    minimum_hold = _minimum_hold_minutes(heat_treatment_thickness, profile)
    if minimum_hold is None:
        incomplete = True
        reasons.append("holding_time_rule_profile_missing")
    elif holding_minutes is not None and holding_minutes < minimum_hold:
        failed = True
        reasons.append("actual_holding_time_below_table36_minimum")
    if thickness is None or thickness <= 0:
        incomplete = True
        reasons.append("governing_thickness_missing_for_rate_limits")
    else:
        heating_max = min(Decimal(205) * Decimal(25) / thickness, Decimal(205))
        cooling_max = min(Decimal(260) * Decimal(25) / thickness, Decimal(260))
        if heating_rate is not None and heating_rate > heating_max:
            failed = True
            reasons.append("actual_heating_rate_exceeds_7.6.4_limit")
        if cooling_rate is not None and cooling_rate > cooling_max:
            failed = True
            reasons.append("actual_cooling_rate_exceeds_7.6.4_limit")
    return ("failed" if failed else "evidence_insufficient" if incomplete else "passed"), reasons


def _pwht_applicability_from_arguments(arguments: dict[str, Any]) -> list[dict[str, Any]] | None:
    supplied = arguments.get("pwhtApplicabilityMatrix")
    if isinstance(supplied, list):
        return [item for item in supplied if isinstance(item, dict)]
    welds = _records(arguments.get("weldItems") or arguments.get("items"))
    return [_resolve_pwht_item(weld) for weld in welds] if welds else None


def _reinforcement_limit(grade: str | None, thickness: Decimal | None) -> Decimal | None:
    if grade is None or thickness is None:
        return None
    base = Decimal("1.5") if thickness <= 6 else Decimal(3) if thickness <= 13 else Decimal(4) if thickness <= 25 else Decimal(5)
    return base * 2 if grade == "V" else base


def _undercut_limit(grade: str | None, joint: str, thickness: Decimal | None) -> Decimal | None:
    if grade is None or thickness is None:
        return None
    longitudinal = any(token in joint for token in ("longitudinal", "seam", "纵向", "直缝", "螺旋缝"))
    fillet = any(token in joint for token in ("fillet", "socket", "角焊", "承插"))
    recognizable = longitudinal or fillet or any(token in joint for token in ("circumferential", "girth", "branch", "butt", "环向", "斜接", "支管", "对接"))
    if not recognizable:
        return None
    # 表43：纵向坡口均为A；I/II级全部为A；III/IV级的环向/支管及角焊缝为D；V级环向/支管为E、角焊缝为D。
    if longitudinal or grade in {"I", "II"}:
        return Decimal(0)
    if grade in {"II", "III"}:
        return min(Decimal(1), thickness / Decimal(4))
    if grade == "IV" or grade == "V" and fillet:
        return min(Decimal(1), thickness / Decimal(4))
    if grade == "V":
        return min(Decimal("1.5"), max(thickness / Decimal(4), Decimal(1)))
    return None


def _pwht_exception(weld: dict[str, Any], group: str, thickness: Decimal, tensile: Decimal | None) -> bool | None:
    kind = _norm(_first(weld, "jointExceptionType", "jointType"))
    allowed_joint = kind in {"flatweldedflange", "socketweldedflange", "平焊法兰", "承插焊法兰", "nonpressureattachment", "非承压附件"}
    if kind in {"dnle50anglebranch", "dnle50threadsealing", "dn50以下角焊支管", "dn50以下螺纹密封焊"}:
        dn = decimal(_first(weld, "nominalDiameter", "dn"))
        if dn is None:
            return None
        allowed_joint = dn <= 50
    if not allowed_joint:
        return None if _bool(_first(weld, "jointExceptionClaimed")) is True and not kind else False
    weld_thickness = decimal(_first(weld, "weldThickness", "heatTreatmentThickness")) or thickness
    if group == "carbon_manganese" and weld_thickness <= 16:
        return True
    if group.startswith("low_alloy") and weld_thickness <= 13 and _bool(_first(weld, "adequatePreheat")) is True and tensile is not None and tensile < 490:
        return True
    if group == "ferritic_stainless" and _norm(_first(weld, "fillerGroup")) in {"austenitic", "nickel", "奥氏体", "镍基"}:
        return True
    return False


def _material_group(item: dict[str, Any]) -> str | None:
    explicit = _norm(_first(item, "materialGroup", "pwhtMaterialGroup"))
    aliases = {
        "carbonmanganese": "carbon_manganese", "carbonsteel": "carbon_manganese", "碳钢": "carbon_manganese", "碳锰钢": "carbon_manganese",
        "lowalloycrle05": "low_alloy_cr_le_0_5", "lowalloycr05to2": "low_alloy_cr_0_5_to_2", "lowalloycr2to3lowc": "low_alloy_cr_2_to_3_low_c",
        "lowalloycr3to10orhighc": "low_alloy_cr_3_to_10_or_high_c", "9cr1mov": "nine_cr_one_mo_v", "ninecr1mov": "nine_cr_one_mo_v",
        "martensiticstainless": "martensitic_stainless", "马氏体不锈钢": "martensitic_stainless", "ferriticstainless": "ferritic_stainless", "铁素体不锈钢": "ferritic_stainless",
        "austeniticstainless": "austenitic_stainless", "奥氏体不锈钢": "austenitic_stainless", "nickelalloy": "nickel_alloy", "镍基合金": "nickel_alloy",
        "duplexstainless": "duplex_stainless", "双相不锈钢": "duplex_stainless", "lowtemperaturenile4": "low_temperature_ni_le_4", "lowtemperatureni589": "low_temperature_ni_5_8_9",
    }
    if explicit in aliases:
        return aliases[explicit]
    cr = decimal(_first(item, "chromiumPercent", "chromiumContent"))
    carbon = decimal(_first(item, "carbonPercent", "carbonContent"))
    if cr is not None:
        if cr <= Decimal("0.5"):
            return "low_alloy_cr_le_0_5"
        if cr <= 2:
            return "low_alloy_cr_0_5_to_2"
        if cr <= 3 and carbon is not None and carbon <= Decimal("0.15"):
            return "low_alloy_cr_2_to_3_low_c"
        if cr <= 10:
            return "low_alloy_cr_3_to_10_or_high_c"
    return None


def _match_consumable(required: dict[str, Any], cert: dict[str, Any]) -> bool:
    for field in ("materialGrade", "brand", "specification", "standardRef"):
        expected = _first(required, field)
        if _present(expected) and _norm(_first(cert, field)) != _norm(expected):
            return False
    return True


def _measurement_map(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    output: dict[str, Any] = {}
    for row in value or []:
        if not isinstance(row, dict):
            continue
        name = _first(row, "element", "item", "property", "name", "项目", "元素")
        measured = _first(row, "value", "measuredValue", "result", "实测值")
        if _present(name) and _present(measured):
            output[str(name)] = measured
    return output


def _match_by_weld(weld: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any] | None:
    weld_no = _norm(_first(weld, "weldNo", "jointNo", "id"))
    return next((record for record in records if weld_no and weld_no == _norm(_first(record, "weldNo", "jointNo", "itemId"))), None)


def _record_kind(record: dict[str, Any]) -> str:
    text = _norm(_first(record, "recordKind", "type", "documentType"))
    routes = (("acceptance", ("acceptance", "验收")), ("storage", ("storage", "temperaturehumidity", "保管", "温湿度")), ("drying", ("drying", "烘干", "保温")), ("issue", ("issue", "领用", "发放")), ("return", ("return", "回收", "退库")), ("use", ("use", "使用")))
    for kind, markers in routes:
        if any(_norm(marker) in text for marker in markers):
            return kind
    return text


def _instrument_type(record: dict[str, Any]) -> str | None:
    text = _norm(_first(record, "instrumentType", "type", "name"))
    if "thermocouple" in text or "热电偶" in text:
        return "thermocouple"
    if "controller" in text or "温控" in text:
        return "controller"
    if "recorder" in text or "记录仪" in text:
        return "recorder"
    return None


def _inspection_grade(value: Any) -> str | None:
    text = str(value or "").upper().translate(str.maketrans({"Ⅰ": "I", "Ⅱ": "II", "Ⅲ": "III", "Ⅳ": "IV", "Ⅴ": "V"}))
    match = re.search(r"\b(I{1,3}|IV|V)\b", text)
    return match.group(1) if match else None


def _range(value: Any, source: dict[str, Any], min_key: str, max_key: str) -> tuple[Decimal | None, Decimal | None] | None:
    if isinstance(value, dict):
        minimum, maximum = decimal(value.get("min")), decimal(value.get("max"))
    elif isinstance(value, (list, tuple)) and len(value) >= 2:
        minimum, maximum = decimal(value[0]), decimal(value[1])
    elif isinstance(value, str):
        numbers = [decimal(item) for item in re.findall(r"\d+(?:\.\d+)?", value)]
        numbers = [item for item in numbers if item is not None]
        minimum, maximum = (numbers[0], numbers[1]) if len(numbers) >= 2 else (None, None)
    else:
        minimum, maximum = decimal(source.get(min_key)), decimal(source.get(max_key))
    return (minimum, maximum) if minimum is not None or maximum is not None else None


def _range_within(inner: tuple[Decimal | None, Decimal | None], outer: tuple[Decimal | None, Decimal | None]) -> bool:
    return (outer[0] is None or inner[0] is not None and inner[0] >= outer[0]) and (outer[1] is None or inner[1] is not None and inner[1] <= outer[1])


def _between(value: Decimal, minimum: Decimal | None, maximum: Decimal | None) -> bool:
    return (minimum is None or value >= minimum) and (maximum is None or value <= maximum)


def _within_limits(value: Decimal | None, spec: Any) -> bool:
    if value is None:
        return False
    if not isinstance(spec, dict):
        return False
    return _between(value, decimal(spec.get("min")), decimal(spec.get("max")))


def _design_limit(record: dict[str, Any], key: str) -> Decimal | None:
    return decimal(_first(record, key, f"design{key[0].upper()}{key[1:]}", f"wps{key[0].upper()}{key[1:]}"))


def _same_if_present(left: dict[str, Any], right: dict[str, Any], *fields: str) -> bool:
    for field in fields:
        rv = _first(right, field)
        left_value = _first(left, field)
        if _present(rv) and _present(left_value) and _norm(left_value) != _norm(rv):
            return False
    return True


def _standard_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def _accepted(value: Any) -> bool:
    return _norm(value) in {"passed", "qualified", "accepted", "compliant", "合格", "通过", "符合"}


def _bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    text = _norm(value)
    if text in {"true", "yes", "1", "是", "有", "合格", "通过", "已完成", "已批准"}:
        return True
    if text in {"false", "no", "0", "否", "无", "不合格", "未完成", "未批准"}:
        return False
    return None


def _integer(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _records(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [value]
    return [item for item in value or [] if isinstance(item, dict)]


def _first(record: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in record and _present(record[key]):
            return record[key]
    return None


def _present(value: Any) -> bool:
    return value is not None and value != "" and value != [] and value != {}


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", str(value or "").lower())


def _id(record: dict[str, Any], index: int) -> Any:
    return _first(record, "recordId", "itemId", "id", "documentNo", "reportNo") or f"item-{index}"


def _output(tool_name: str, failed: bool, incomplete: bool, facts: dict[str, Any], checks: list[dict[str, Any]], version: str) -> dict[str, Any]:
    status = "failed" if failed else "evidence_insufficient" if incomplete else "passed"
    return result(tool_name, status, facts=facts, checks=checks, rule_version=version)


def _insufficient(tool_name: str, reason: str, version: str, arguments: dict[str, Any]) -> dict[str, Any]:
    output = result(tool_name, "evidence_insufficient", facts={"reason": reason, "input": arguments}, checks=[], rule_version=version)
    output["warnings"] = [reason]
    return output
