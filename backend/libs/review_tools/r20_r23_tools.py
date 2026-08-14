from __future__ import annotations

import math
import re
from decimal import Decimal
from typing import Any

from libs.review_orchestrator.deterministic_tools import check, decimal, result

R20_RULE_VERSION = "r20-new-material-tsg31-2025-d7006-2020-v1"
R21_RULE_VERSION = "r21-mark-transfer-gbt20801.1-2025-d7006-2020-v1"
R22_RULE_VERSION = "r22-material-substitution-tsg31-2025-d7006-2020-v1"
R23_RULE_VERSION = "r23-valve-test-gbt20801.1-2025-v1"

_PASS = {"accepted", "approved", "compliant", "qualified", "passed", "符合", "合格", "通过", "无泄漏"}
_HARD_MARK = {"hardstamp", "hardmark", "steelstamp", "硬印", "钢印", "冲印"}
_COLOR_MARK = {"colorcode", "paintmark", "色码", "色标", "涂色"}
_PROHIBIT_HARD_MARK_MATERIALS = ("低温", "不锈钢", "stainless", "nonferrous", "有色", "镍", "钛", "锆", "铝", "铜")
_AUSTENITIC_OR_NONFERROUS = ("奥氏体", "austenitic", "nonferrous", "有色", "镍", "钛", "锆", "铝", "铜")
_SUPPORTED_VALVE_STANDARDS = {
    "gbt139272022": "GB/T 13927-2022",
    "gbt264802011": "GB/T 26480-2011",
}


def classify_r20_new_material_applicability(arguments: dict[str, Any]) -> dict[str, Any]:
    items = _records(arguments.get("designItems"))
    if not items:
        return _insufficient("classify_r20_new_material_applicability", "r20_design_items_missing", R20_RULE_VERSION)
    matrix, checks = [], []
    unknown = False
    applicable = 0
    for index, item in enumerate(items, 1):
        category, reasons = _new_material_category(item)
        known = category is not None
        unknown |= not known
        if category in {"unlisted_all", "listed_dedicated_material_standard"}:
            applicable += 1
        checks.append(
            check(
                f"component_{index}_new_material_category_known",
                known,
                category,
                "not_new_material_or_one_of_two_tsg31_2_1_3_branches",
            )
        )
        matrix.append(
            {
                "componentItemId": _id(item, index),
                "materialName": _first(item, "materialName", "materialGrade", "material"),
                "newMaterialCategory": category,
                "technicalReviewRequired": category == "unlisted_all" if known else None,
                "materialDataRequired": category == "listed_dedicated_material_standard" if known else None,
                "result": "evidence_insufficient" if not known else "not_applicable" if category == "not_new_material" else "passed",
                "reasonCodes": reasons,
            }
        )
    business_result = "evidence_insufficient" if unknown else "passed" if applicable else "not_applicable"
    output = result(
        "classify_r20_new_material_applicability",
        business_result,
        facts={"newMaterialClassificationMatrix": matrix, "applicableItemCount": applicable},
        checks=checks,
        rule_version=R20_RULE_VERSION,
    )
    output["newMaterialClassificationMatrix"] = matrix
    return output


def evaluate_r20_new_material_procedure(arguments: dict[str, Any]) -> dict[str, Any]:
    items = _records(arguments.get("designItems"))
    reports = _records(arguments.get("typeTestReports"))
    reviews = _records(arguments.get("technicalReviewApprovals"))
    data_documents = _records(arguments.get("materialDataDocuments"))
    if not items:
        return _insufficient("evaluate_r20_new_material_procedure", "r20_design_items_missing", R20_RULE_VERSION)
    matrix, checks = [], []
    failed = incomplete = False
    applicable = 0
    for index, item in enumerate(items, 1):
        category, category_reasons = _new_material_category(item)
        if category == "not_new_material":
            matrix.append({"componentItemId": _id(item, index), "result": "not_applicable"})
            continue
        if category is None:
            incomplete = True
            matrix.append(
                {
                    "componentItemId": _id(item, index),
                    "result": "evidence_insufficient",
                    "reasonCodes": category_reasons or ["new_material_category_unknown"],
                }
            )
            continue
        applicable += 1
        matching_reports = _matching_material_records(item, reports)
        report_status, report_reasons = _type_test_report_status(item, matching_reports)
        checks.append(
            check(
                f"component_{index}_type_test_coverage",
                report_status == "passed",
                [record.get("reportNo") or record.get("reportId") for record in matching_reports],
                "covering_type_test_report_with_accepted_conclusion",
            )
        )
        item_failed = report_status == "failed"
        item_incomplete = report_status == "evidence_insufficient"
        reasons = list(report_reasons)
        matched_review_ids: list[Any] = []
        matched_data_ids: list[Any] = []
        if category == "unlisted_all":
            matching_reviews = _matching_material_records(item, reviews)
            review_status, review_reasons = _technical_review_status(matching_reviews)
            matched_review_ids = [record.get("reviewNo") or record.get("approvalDocumentNo") or record.get("recordId") for record in matching_reviews]
            checks.append(
                check(
                    f"component_{index}_technical_review_and_approval",
                    review_status == "passed",
                    matched_review_ids,
                    "technical_review_passed_and_approval_document_present",
                )
            )
            item_failed |= review_status == "failed"
            item_incomplete |= review_status == "evidence_insufficient"
            reasons.extend(review_reasons)
        else:
            matching_data = _matching_material_records(item, data_documents)
            data_status, data_reasons = _material_data_status(matching_data)
            matched_data_ids = [record.get("documentNo") or record.get("recordId") for record in matching_data]
            checks.append(
                check(
                    f"component_{index}_necessary_material_data",
                    data_status == "passed",
                    matched_data_ids,
                    ["chemical_composition", "tensile_properties", "fatigue_data", "fracture_toughness", "scope_performance_parameters"],
                )
            )
            item_failed |= data_status == "failed"
            item_incomplete |= data_status == "evidence_insufficient"
            reasons.extend(data_reasons)
        failed |= item_failed
        incomplete |= item_incomplete
        status = "failed" if item_failed else "evidence_insufficient" if item_incomplete else "passed"
        matrix.append(
            {
                "componentItemId": _id(item, index),
                "newMaterialCategory": category,
                "matchedTypeTestReportIds": [record.get("reportId") or record.get("reportNo") for record in matching_reports],
                "matchedTechnicalReviewIds": matched_review_ids,
                "matchedMaterialDataIds": matched_data_ids,
                "result": status,
                "reasonCodes": list(dict.fromkeys(reasons)),
            }
        )
    business_result = "not_applicable" if not applicable and not incomplete else _aggregate(failed, incomplete)
    output = result(
        "evaluate_r20_new_material_procedure",
        business_result,
        facts={"newMaterialProcedureMatrix": matrix},
        checks=checks,
        rule_version=R20_RULE_VERSION,
    )
    output["newMaterialProcedureMatrix"] = matrix
    return output


def evaluate_r21_mark_transfer(arguments: dict[str, Any]) -> dict[str, Any]:
    records = _records(arguments.get("transferRecords"))
    inventory = _records(arguments.get("materialInventory"))
    occurred = _truth(arguments.get("markTransferOccurred"))
    if occurred is None and records:
        occurred = True
    if occurred is False:
        return result(
            "evaluate_r21_mark_transfer",
            "not_applicable",
            facts={"markTransferOccurred": False},
            checks=[],
            rule_version=R21_RULE_VERSION,
        )
    if occurred is None:
        return _insufficient("evaluate_r21_mark_transfer", "mark_transfer_occurrence_unknown", R21_RULE_VERSION)
    if not records:
        return result(
            "evaluate_r21_mark_transfer",
            "failed",
            facts={"markTransferOccurred": True, "transferRecordCount": 0},
            checks=[check("transfer_record_present", False, 0, ">=1")],
            rule_version=R21_RULE_VERSION,
        )
    matrix, checks = [], []
    failed = incomplete = False
    for index, record in enumerate(records, 1):
        missing = [
            field
            for field in ("originalMark", "transferredMark", "batchNo", "materialGrade", "markMethod", "inspector", "conclusion")
            if not _present(_first(record, field, _snake(field)))
        ]
        material = str(_first(record, "materialType", "materialGrade", "material") or "")
        method = _norm(_first(record, "markMethod", "transferMethod", "标记方法"))
        hard_prohibited = method in {_norm(value) for value in _HARD_MARK} and _contains_any(material, _PROHIBIT_HARD_MARK_MATERIALS)
        color_sensitive = method in {_norm(value) for value in _COLOR_MARK} and _contains_any(material, _AUSTENITIC_OR_NONFERROUS)
        harmful_control = _truth(_first(record, "harmfulSubstancesAbsent", "colorantSulfurLeadChlorineControlled"))
        confusion_control = _truth(_first(record, "confusionControl", "separateProcessingOrColorBand"))
        original = _first(record, "originalMark", "sourceMark")
        transferred = _first(record, "transferredMark", "newMark")
        traceable = _marks_traceable(record, inventory)
        conclusion = _first(record, "conclusion", "inspectionConclusion")
        explicit_failures = []
        if hard_prohibited:
            explicit_failures.append("hard_mark_prohibited_for_material")
        if color_sensitive and harmful_control is False:
            explicit_failures.append("colorant_harmful_substance_control_failed")
        if confusion_control is False:
            explicit_failures.append("material_confusion_control_failed")
        if _present(conclusion) and not _accepted(conclusion):
            explicit_failures.append("inspection_conclusion_not_accepted")
        missing_controls = []
        if color_sensitive and harmful_control is None:
            missing_controls.append("colorant_harmful_substance_control_unknown")
        if method not in {_norm(value) for value in _HARD_MARK} and confusion_control is None:
            missing_controls.append("material_confusion_control_unknown")
        if not traceable:
            if original and transferred and _present(_first(record, "batchNo", "heatNo")):
                explicit_failures.append("mark_identity_chain_mismatch")
            else:
                missing_controls.append("mark_identity_chain_incomplete")
        if explicit_failures or missing:
            status = "failed"
            failed = True
        elif missing_controls:
            status = "evidence_insufficient"
            incomplete = True
        else:
            status = "passed"
        checks.extend(
            [
                check(f"transfer_{index}_required_fields", not missing, missing, "complete"),
                check(f"transfer_{index}_mark_method_allowed", not hard_prohibited, method, "non_damaging_non_polluting"),
                check(f"transfer_{index}_identity_traceable", traceable, {"original": original, "transferred": transferred}, "same_material_identity_chain"),
            ]
        )
        if color_sensitive:
            checks.append(check(f"transfer_{index}_colorant_safe", harmful_control is True, harmful_control, True))
        matrix.append(
            {
                "recordId": record.get("recordId"),
                "materialType": material,
                "markMethod": method,
                "result": status,
                "reasonCodes": [*explicit_failures, *missing_controls, *(["required_fields_missing"] if missing else [])],
            }
        )
    required_special_types = {
        _norm(_first(item, "specialMaterialType", "materialType", "materialGrade"))
        for item in inventory
        if _truth(_first(item, "specialMaterial", "isSpecialMaterial")) is True
    }
    sampled_special_types = {
        _norm(_first(record, "specialMaterialType", "materialType", "materialGrade")) for record in records
    }
    missing_special_types = sorted(value for value in required_special_types if value and value not in sampled_special_types)
    if missing_special_types:
        failed = True
    checks.append(
        check(
            "all_special_material_types_sampled",
            not missing_special_types,
            sorted(sampled_special_types),
            sorted(required_special_types),
        )
    )
    output = result(
        "evaluate_r21_mark_transfer",
        _aggregate(failed, incomplete),
        facts={"markTransferMatrix": matrix, "missingSpecialMaterialTypes": missing_special_types},
        checks=checks,
        rule_version=R21_RULE_VERSION,
    )
    output["markTransferMatrix"] = matrix
    return output


def evaluate_r22_material_substitution(arguments: dict[str, Any]) -> dict[str, Any]:
    records = _records(arguments.get("substitutionRecords"))
    actual_usage = _records(arguments.get("actualMaterialUsage"))
    occurred = _truth(arguments.get("materialSubstitutionOccurred"))
    if occurred is None and records:
        occurred = any(_truth(_first(record, "implemented", "actuallyUsed")) is not False for record in records)
    if occurred is False:
        return result(
            "evaluate_r22_material_substitution",
            "not_applicable",
            facts={"materialSubstitutionOccurred": False},
            checks=[],
            rule_version=R22_RULE_VERSION,
        )
    if occurred is None:
        return _insufficient("evaluate_r22_material_substitution", "material_substitution_occurrence_unknown", R22_RULE_VERSION)
    implemented_records = [record for record in records if _truth(_first(record, "implemented", "actuallyUsed")) is not False]
    if not implemented_records:
        return result(
            "evaluate_r22_material_substitution",
            "failed",
            facts={"materialSubstitutionOccurred": True},
            checks=[check("implemented_substitution_record_present", False, 0, ">=1")],
            rule_version=R22_RULE_VERSION,
        )
    matrix, checks = [], []
    failed = incomplete = False
    for index, record in enumerate(implemented_records, 1):
        original_org = _first(record, "originalDesignOrganization", "designOrganization")
        approving_org = _first(record, "approvingOrganization", "approvalOrganization")
        written = _truth(_first(record, "writtenApprovalPresent", "writtenApproval", "documentBodyPresent"))
        missing = [
            field
            for field in ("originalMaterial", "substituteMaterial", "substitutionScope", "changeNo", "approvalDate")
            if not _present(_first(record, field, _snake(field)))
        ]
        same_org = _same(original_org, approving_org)
        approval_date = _date_key(_first(record, "approvalDate", "approvedAt"))
        use_date = _date_key(_first(record, "implementationDate", "firstUseDate", "usedAt"))
        approval_before_use = None if not approval_date or not use_date else approval_date <= use_date
        usage_matches = _substitution_usage_matches(record, actual_usage)
        explicit_failures = []
        missing_facts = list(missing)
        if written is False:
            explicit_failures.append("written_approval_missing")
        elif written is None:
            missing_facts.append("written_approval_status_unknown")
        if original_org and approving_org and not same_org:
            explicit_failures.append("approval_not_from_original_design_organization")
        elif not original_org or not approving_org:
            missing_facts.append("design_organization_identity_incomplete")
        if approval_before_use is False:
            explicit_failures.append("approval_after_material_use")
        elif approval_before_use is None:
            missing_facts.append("approval_or_use_date_missing")
        if actual_usage and not usage_matches:
            explicit_failures.append("approved_substitution_not_matching_actual_usage")
        elif not actual_usage:
            missing_facts.append("actual_material_usage_missing")
        if explicit_failures or missing:
            status = "failed"
            failed = True
        elif missing_facts:
            status = "evidence_insufficient"
            incomplete = True
        else:
            status = "passed"
        checks.extend(
            [
                check(f"substitution_{index}_written_approval", written is True, written, True),
                check(f"substitution_{index}_original_design_org", same_org, approving_org, original_org),
                check(f"substitution_{index}_approval_before_use", approval_before_use is True, approval_date, f"<= {use_date or 'implementation_date'}"),
                check(f"substitution_{index}_actual_usage_match", usage_matches, actual_usage, "approved_substitution_scope"),
            ]
        )
        matrix.append(
            {
                "recordId": record.get("recordId"),
                "changeNo": _first(record, "changeNo", "changeDocumentNo"),
                "originalDesignOrganization": original_org,
                "approvingOrganization": approving_org,
                "result": status,
                "reasonCodes": [*explicit_failures, *list(dict.fromkeys(missing_facts))],
            }
        )
    output = result(
        "evaluate_r22_material_substitution",
        _aggregate(failed, incomplete),
        facts={"materialSubstitutionMatrix": matrix},
        checks=checks,
        rule_version=R22_RULE_VERSION,
    )
    output["materialSubstitutionMatrix"] = matrix
    return output


def resolve_r23_valve_test_basis(arguments: dict[str, Any]) -> dict[str, Any]:
    design = _standard_list(arguments.get("designStandardRefs"))
    contract = _standard_list(arguments.get("contractStandardRefs"))
    basis_checked = _truth(arguments.get("designAndContractBasisChecked"))
    if not design and not contract and basis_checked is not True:
        return _insufficient(
            "resolve_r23_valve_test_basis",
            "design_and_contract_valve_basis_not_checked",
            R23_RULE_VERSION,
        )
    if design and contract and set(design) != set(contract):
        output = _insufficient("resolve_r23_valve_test_basis", "design_contract_valve_standard_conflict", R23_RULE_VERSION)
        output["designStandardRefs"] = design
        output["contractStandardRefs"] = contract
        return output
    selected = design or contract or ["GB/T 13927-2022"]
    unsupported = [item for item in selected if _norm(item) not in _SUPPORTED_VALVE_STANDARDS]
    if unsupported:
        output = _insufficient("resolve_r23_valve_test_basis", "unsupported_valve_test_standard", R23_RULE_VERSION)
        output["unsupportedStandardRefs"] = unsupported
        return output
    selected = [_SUPPORTED_VALVE_STANDARDS[_norm(item)] for item in selected]
    checks = [
        check("design_and_contract_basis_consistent", not (design and contract) or set(design) == set(contract), contract, design),
        check("applicable_standard_supported", not unsupported, selected, sorted(_SUPPORTED_VALVE_STANDARDS.values())),
    ]
    output = result(
        "resolve_r23_valve_test_basis",
        "passed",
        facts={"applicableStandardRefs": selected, "basisSource": "design" if design else "contract" if contract else "gbt13927_default"},
        checks=checks,
        rule_version=R23_RULE_VERSION,
    )
    output["applicableStandardRefs"] = selected
    return output


def evaluate_r23_valve_sampling(arguments: dict[str, Any]) -> dict[str, Any]:
    lots = _valve_lots(arguments)
    if not lots:
        return _insufficient("evaluate_r23_valve_sampling", "valve_test_lots_missing", R23_RULE_VERSION)
    matrix, checks = [], []
    failed = incomplete = False
    for index, lot in enumerate(lots, 1):
        grade = _norm(_first(lot, "pipelineGrade", "grade"))
        lot_size = _integer(_first(lot, "lotSize", "populationCount", "quantity"))
        tested = _integer(_first(lot, "testedCount", "sampledCount"))
        ratio = {"gc1": Decimal(1), "gc2": Decimal("0.10"), "gc3": Decimal("0.05")}.get(grade)
        exemption = _truth(lot.get("factoryWitnessExemption")) is True
        reasons = []
        if exemption:
            exemption_ok = all(
                _truth(lot.get(field)) is True
                for field in ("factoryTestedEach", "ownerApprovedExemption", "factoryRecordsTraceable")
            )
            if not exemption_ok:
                failed = True
                status = "failed"
                reasons.append("factory_witness_exemption_conditions_incomplete")
            else:
                status = "passed"
            required_count = 0
            checks.append(check(f"lot_{index}_factory_witness_exemption", exemption_ok, lot, "owner_approved_each_valve_witnessed_and_traceable"))
        elif ratio is None or lot_size is None or tested is None:
            incomplete = True
            status = "evidence_insufficient"
            required_count = None
            reasons.append("pipeline_grade_lot_size_or_tested_count_missing")
        else:
            required_count = max(1, math.ceil(Decimal(lot_size) * ratio))
            if tested < required_count:
                failed = True
                status = "failed"
                reasons.append("valve_sampling_count_insufficient")
            else:
                status = "passed"
            checks.append(check(f"lot_{index}_sampling_count", tested >= required_count, tested, required_count))
        nonconforming = _integer(lot.get("nonconformingCount")) or 0
        if nonconforming:
            disposition_ok = (
                lot_size is not None
                and tested is not None
                and tested >= lot_size
                and _truth(lot.get("individualRetestCompleted")) is True
            ) or (_truth(lot.get("lotRejectedOrIsolated")) is True)
            if not disposition_ok:
                failed = True
                status = "failed"
                reasons.append("nonconforming_sample_lot_not_controlled")
            checks.append(check(f"lot_{index}_nonconformance_control", disposition_ok, lot, "individual_test_or_lot_rejected_isolated"))
        matrix.append(
            {
                "lotId": lot.get("lotId") or f"LOT-{index}",
                "pipelineGrade": grade.upper() if grade else None,
                "lotSize": lot_size,
                "testedCount": tested,
                "requiredTestCount": required_count,
                "result": status,
                "reasonCodes": reasons,
            }
        )
    output = result(
        "evaluate_r23_valve_sampling",
        _aggregate(failed, incomplete),
        facts={"valveSamplingMatrix": matrix},
        checks=checks,
        rule_version=R23_RULE_VERSION,
    )
    output["valveSamplingMatrix"] = matrix
    return output


def evaluate_r23_valve_test_records(arguments: dict[str, Any]) -> dict[str, Any]:
    records = _records(arguments.get("testRecords"))
    construction_records = _records(arguments.get("constructionRecords"))
    if not records:
        if "testRecords" not in arguments:
            return _insufficient(
                "evaluate_r23_valve_test_records",
                "valve_test_record_facts_missing",
                R23_RULE_VERSION,
            )
        return result(
            "evaluate_r23_valve_test_records",
            "failed",
            facts={"testRecordCount": 0},
            checks=[check("valve_test_record_present", False, 0, ">=1")],
            rule_version=R23_RULE_VERSION,
        )
    basis = resolve_r23_valve_test_basis(arguments)
    if basis.get("result") != "passed":
        basis["toolName"] = "evaluate_r23_valve_test_records"
        return basis
    applicable_standards = basis.get("applicableStandardRefs") or []
    requirement_profiles = arguments.get("standardRequirementProfiles") if isinstance(arguments.get("standardRequirementProfiles"), dict) else {}
    matrix, checks = [], []
    failed = incomplete = False
    for index, record in enumerate(records, 1):
        construction = _matching_valve_construction_record(record, construction_records)
        effective_record = {**(construction or {}), **record}
        standard = _canonical_standard(_first(effective_record, "standardRef", "basisStandard", "依据标准"))
        missing = [
            field
            for field in ("valveNo", "valveType", "nominalDiameterMM", "nominalPressure", "conclusion")
            if not _present(_first(effective_record, field, _snake(field), "model" if field == "valveType" else ""))
        ]
        reasons = []
        item_failed = bool(missing)
        item_incomplete = False
        if construction is None:
            if construction_records:
                item_failed = True
                reasons.append("valve_test_report_not_matched_to_construction_record")
            else:
                item_incomplete = True
                reasons.append("valve_construction_records_missing")
        else:
            identity_status, identity_reasons = _valve_identity_status(record, construction)
            if identity_status == "failed":
                item_failed = True
            elif identity_status == "evidence_insufficient":
                item_incomplete = True
            reasons.extend(identity_reasons)
            checks.append(
                check(
                    f"valve_{index}_construction_record_identity",
                    identity_status == "passed",
                    construction.get("recordId") or construction.get("recordNo"),
                    "same_valve_number_type_dn_and_pn",
                )
            )
        if not standard:
            item_failed = True
            reasons.append("report_basis_standard_missing")
        elif standard not in applicable_standards:
            item_failed = True
            reasons.append("report_basis_standard_not_applicable")
        large_gate = _large_gate_exception(effective_record)
        if large_gate:
            exception_ok = all(
                _truth(effective_record.get(field)) is True
                for field in ("designOrOwnerApprovedSystemTest", "systemPressureTestRecorded", "colorPrintSealTestRecorded")
            )
            if not exception_ok:
                item_failed = True
                reasons.append("large_gate_valve_exception_conditions_incomplete")
            checks.append(check(f"valve_{index}_large_gate_exception", exception_ok, effective_record, "approved_system_test_and_color_print_seal_test"))
        else:
            shell = record.get("shellTest") if isinstance(record.get("shellTest"), dict) else {}
            seal = record.get("sealTest") if isinstance(record.get("sealTest"), dict) else {}
            for test_name, test_data in (("shell", shell), ("seal", seal)):
                if not test_data:
                    item_failed = True
                    reasons.append(f"{test_name}_test_missing")
                    checks.append(check(f"valve_{index}_{test_name}_test_present", False, None, "present"))
                    continue
                basic_missing = [field for field in ("medium", "pressureMPa", "result") if not _present(test_data.get(field))]
                hold_seconds = _hold_seconds(test_data)
                if hold_seconds is None:
                    basic_missing.append("holdSeconds")
                if basic_missing:
                    item_failed = True
                    reasons.append(f"{test_name}_test_required_fields_missing")
                accepted = _accepted(test_data.get("result"))
                if _present(test_data.get("result")) and not accepted:
                    item_failed = True
                    reasons.append(f"{test_name}_test_result_not_accepted")
                requirements = _test_requirements(effective_record, requirement_profiles, standard, test_name)
                comparison = _compare_test_parameters(test_data, requirements, standard, effective_record, test_name)
                if comparison["result"] == "failed":
                    item_failed = True
                    reasons.extend(comparison["reasonCodes"])
                elif comparison["result"] == "evidence_insufficient":
                    item_incomplete = True
                    reasons.extend(comparison["reasonCodes"])
                checks.extend(
                    [
                        check(f"valve_{index}_{test_name}_required_fields", not basic_missing, basic_missing, "complete"),
                        check(f"valve_{index}_{test_name}_result", accepted, test_data.get("result"), "accepted"),
                        check(f"valve_{index}_{test_name}_parameters", comparison["result"] == "passed", comparison, "frozen_standard_or_design_requirements"),
                    ]
                )
        if _truth(effective_record.get("jacketed")) is True:
            jacket_pressure = _decimal_value(effective_record.get("jacketTestPressureMPa"))
            jacket_design = _decimal_value(effective_record.get("jacketDesignPressureMPa"))
            if jacket_pressure is None or jacket_design is None:
                item_incomplete = True
                reasons.append("jacket_pressure_facts_missing")
            elif jacket_pressure < jacket_design * Decimal("1.5"):
                item_failed = True
                reasons.append("jacket_test_pressure_below_1_5_design_pressure")
            checks.append(check(f"valve_{index}_jacket_pressure", jacket_pressure is not None and jacket_design is not None and jacket_pressure >= jacket_design * Decimal("1.5"), jacket_pressure, jacket_design * Decimal("1.5") if jacket_design is not None else None))
        conclusion = _first(effective_record, "conclusion", "testConclusion")
        if _present(conclusion) and not _accepted(conclusion):
            item_failed = True
            reasons.append("report_conclusion_not_accepted")
        failed |= item_failed
        incomplete |= item_incomplete
        status = "failed" if item_failed else "evidence_insufficient" if item_incomplete else "passed"
        matrix.append(
            {
                "recordId": record.get("recordId") or record.get("reportNo"),
                "valveNo": _first(effective_record, "valveNo", "serialNo"),
                "matchedConstructionRecordId": (construction or {}).get("recordId") or (construction or {}).get("recordNo"),
                "standardRef": standard,
                "result": status,
                "reasonCodes": list(dict.fromkeys(reasons + (["required_report_fields_missing"] if missing else []))),
            }
        )
    output = result(
        "evaluate_r23_valve_test_records",
        _aggregate(failed, incomplete),
        facts={"valveTestRecordMatrix": matrix, "applicableStandardRefs": applicable_standards},
        checks=checks,
        rule_version=R23_RULE_VERSION,
    )
    output["valveTestRecordMatrix"] = matrix
    return output


def _matching_valve_construction_record(
    test_record: dict[str, Any],
    construction_records: list[dict[str, Any]],
) -> dict[str, Any] | None:
    reference = _first(test_record, "constructionRecordId", "constructionRecordNo")
    if reference:
        for record in construction_records:
            if any(
                _same(reference, _first(record, key))
                for key in ("recordId", "recordNo", "constructionRecordId", "constructionRecordNo")
            ):
                return record
    valve_no = _first(test_record, "valveNo", "serialNo")
    return next(
        (record for record in construction_records if _same(valve_no, _first(record, "valveNo", "serialNo"))),
        None,
    )


def _valve_identity_status(
    test_record: dict[str, Any],
    construction_record: dict[str, Any],
) -> tuple[str, list[str]]:
    aliases = {
        "valveNo": ("valveNo", "serialNo"),
        "valveType": ("valveType", "model", "productName"),
        "nominalDiameterMM": ("nominalDiameterMM", "dn"),
        "nominalPressure": ("nominalPressure", "nominalPressurePN", "pn"),
    }
    missing, mismatched = [], []
    for field, keys in aliases.items():
        test_value = _first(test_record, *keys)
        construction_value = _first(construction_record, *keys)
        if not _present(test_value) or not _present(construction_value):
            missing.append(field)
        elif field in {"nominalDiameterMM", "nominalPressure"}:
            if _decimal_value(test_value) != _decimal_value(construction_value):
                mismatched.append(field)
        elif not _same(test_value, construction_value):
            mismatched.append(field)
    if mismatched:
        return "failed", ["valve_construction_and_test_identity_mismatch"]
    if missing:
        return "evidence_insufficient", ["valve_construction_or_test_identity_incomplete"]
    return "passed", []


def _new_material_category(item: dict[str, Any]) -> tuple[str | None, list[str]]:
    explicit = _norm(_first(item, "newMaterialCategory", "materialCategory"))
    aliases = {
        "unlistedall": "unlisted_all",
        "unlistedinallstandards": "unlisted_all",
        "未列入任何专用材料标准": "unlisted_all",
        "listeddedicatedmaterialstandard": "listed_dedicated_material_standard",
        "listedinotherdedicatedstandard": "listed_dedicated_material_standard",
        "已列入专用材料标准": "listed_dedicated_material_standard",
        "notnewmaterial": "not_new_material",
        "非新材料": "not_new_material",
    }
    if explicit in aliases:
        return aliases[explicit], []
    in_20801 = _truth(_first(item, "listedInGBT20801", "inGBT20801"))
    in_32270 = _truth(_first(item, "listedInGBT32270", "inGBT32270"))
    in_dedicated = _truth(_first(item, "listedInDedicatedMaterialStandard", "inDedicatedMaterialStandard"))
    if in_20801 is True or in_32270 is True:
        return "not_new_material", []
    if in_20801 is False and in_32270 is False and in_dedicated is False:
        return "unlisted_all", []
    if in_20801 is False and in_32270 is False and in_dedicated is True:
        return "listed_dedicated_material_standard", []
    return None, ["gbt20801_gbt32270_and_dedicated_standard_listing_facts_required"]


def _type_test_report_status(item: dict[str, Any], reports: list[dict[str, Any]]) -> tuple[str, list[str]]:
    if not reports:
        return "failed", ["type_test_report_missing"]
    incomplete = False
    for report in reports:
        required = (
            _first(report, "reportNo", "certificateNo"),
            _first(report, "testOrganization", "inspectionOrganization"),
            _first(report, "productName", "componentType"),
            report.get("conclusion"),
        )
        if not all(_present(value) for value in required):
            incomplete = True
            continue
        if _accepted(report.get("conclusion")) and _range_covers(item, report):
            return "passed", []
    return ("evidence_insufficient", ["type_test_scope_or_core_fields_incomplete"]) if incomplete else ("failed", ["type_test_report_not_covering_item_or_not_accepted"])


def _technical_review_status(records: list[dict[str, Any]]) -> tuple[str, list[str]]:
    if not records:
        return "failed", ["technical_review_or_approval_missing"]
    incomplete = False
    for record in records:
        review_passed = _truth(_first(record, "technicalReviewPassed", "reviewPassed"))
        if review_passed is None and _present(record.get("conclusion")):
            review_passed = _accepted(record.get("conclusion"))
        approval_no = _first(record, "approvalDocumentNo", "approvalNo")
        authority = _first(record, "approvalOrganization", "approvalAuthority")
        approval_complete = _truth(record.get("approvalProcedureCompleted"))
        if review_passed is False or approval_complete is False:
            return "failed", ["technical_review_or_approval_not_passed"]
        if review_passed is True and approval_no and authority and approval_complete is True:
            return "passed", []
        incomplete = True
    return "evidence_insufficient", ["technical_review_approval_core_fields_incomplete"] if incomplete else ["technical_review_approval_missing"]


def _material_data_status(records: list[dict[str, Any]]) -> tuple[str, list[str]]:
    if not records:
        return "failed", ["necessary_material_data_missing"]
    required = {"chemicalcomposition", "tensileproperties", "fatiguedata", "fracturetoughness", "scopeperformanceparameters"}
    for record in records:
        provided = {_norm(value) for value in _list(record.get("dataItems") or record.get("materialDataItems"))}
        aliases = {
            "chemicalcomposition": ("化学成分",),
            "tensileproperties": ("拉伸", "拉伸力学性能"),
            "fatiguedata": ("疲劳", "疲劳试验数据"),
            "fracturetoughness": ("断裂韧性",),
            "scopeperformanceparameters": ("使用范围性能参数", "其他性能参数"),
        }
        covered = {code for code in required if code in provided or any(_norm(alias) in provided for alias in aliases[code])}
        if covered == required:
            return "passed", []
    return "failed", ["necessary_material_data_items_incomplete"]


def _matching_material_records(item: dict[str, Any], records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    material = _first(item, "materialName", "materialGrade", "material")
    product = _first(item, "productName", "componentType")
    matches = []
    for record in records:
        record_material = _first(record, "materialName", "materialGrade", "material")
        record_product = _first(record, "productName", "componentType", "applicableProduct")
        if material and record_material and not _same(material, record_material):
            continue
        if product and record_product and not (_norm(product) in _norm(record_product) or _norm(record_product) in _norm(product)):
            continue
        matches.append(record)
    return matches


def _range_covers(item: dict[str, Any], report: dict[str, Any]) -> bool:
    diameter = _decimal_value(_first(item, "nominalDiameterMM", "dn"))
    pressure = _decimal_value(_first(item, "nominalPressureMPa", "nominalPressure", "pnMPa"))
    diameter_min, diameter_max = _decimal_value(report.get("nominalDiameterMinMM")), _decimal_value(report.get("nominalDiameterMaxMM"))
    pressure_min, pressure_max = _decimal_value(report.get("nominalPressureMinMPa")), _decimal_value(report.get("nominalPressureMaxMPa"))
    diameter_ok = diameter is None or (diameter_min is not None and diameter_max is not None and diameter_min <= diameter <= diameter_max)
    pressure_ok = pressure is None or (pressure_min is not None and pressure_max is not None and pressure_min <= pressure <= pressure_max)
    return diameter_ok and pressure_ok


def _marks_traceable(record: dict[str, Any], inventory: list[dict[str, Any]]) -> bool:
    original = _first(record, "originalMark", "sourceMark")
    transferred = _first(record, "transferredMark", "newMark")
    batch = _first(record, "batchNo", "heatNo")
    explicit = _truth(record.get("identityChainVerified"))
    if explicit is not None:
        return explicit
    if not (original and transferred and batch):
        return False
    matches = [item for item in inventory if _same(batch, _first(item, "batchNo", "heatNo"))]
    if not matches:
        return bool(_truth(record.get("qualityCertificateMatched")) is True)
    material = _first(record, "materialGrade", "material")
    return any(not material or _same(material, _first(item, "materialGrade", "material")) for item in matches)


def _substitution_usage_matches(record: dict[str, Any], actual_usage: list[dict[str, Any]]) -> bool:
    substitute = _first(record, "substituteMaterial", "replacementMaterial")
    scope = _first(record, "substitutionScope", "affectedScope")
    return any(
        _same(substitute, _first(item, "material", "materialGrade", "actualMaterial"))
        and (not scope or _same(scope, _first(item, "scope", "lineNo", "componentId")))
        for item in actual_usage
    )


def _valve_lots(arguments: dict[str, Any]) -> list[dict[str, Any]]:
    lots = _records(arguments.get("testLots"))
    if lots:
        return lots
    if any(_present(arguments.get(key)) for key in ("pipelineGrade", "lotSize", "testedCount")):
        return [arguments]
    return []


def _large_gate_exception(record: dict[str, Any]) -> bool:
    valve_type = _norm(_first(record, "valveType", "productName", "model"))
    dn = _decimal_value(_first(record, "nominalDiameterMM", "dn"))
    pn = _decimal_value(_first(record, "nominalPressurePN", "pn", "nominalPressure"))
    return ("gate" in valve_type or "闸阀" in valve_type) and dn is not None and dn >= 600 and pn is not None and pn <= 100


def _test_requirements(
    record: dict[str, Any],
    profiles: dict[str, Any],
    standard: str | None,
    test_name: str,
) -> dict[str, Any]:
    record_requirements = record.get("requiredTestParameters") if isinstance(record.get("requiredTestParameters"), dict) else {}
    if isinstance(record_requirements.get(test_name), dict):
        return record_requirements[test_name]
    standard_profile = profiles.get(standard) or profiles.get(_norm(standard))
    if isinstance(standard_profile, dict) and isinstance(standard_profile.get(test_name), dict):
        return standard_profile[test_name]
    if standard == "GB/T 26480-2011":
        return _gbt26480_requirements(record, test_name)
    return {}


def _gbt26480_requirements(record: dict[str, Any], test_name: str) -> dict[str, Any]:
    """Resolve the common steel-valve branch verified from GB/T 26480-2011 clauses 5-7.

    Cast-iron pressure tables and ambiguous high/low seal selections deliberately
    remain unresolved so the caller fails closed instead of applying the wrong row.
    """
    material = _norm(_first(record, "valveBodyMaterialCategory", "bodyMaterialCategory", "bodyMaterial"))
    if not any(marker in material for marker in ("steel", "钢", "碳钢", "不锈钢", "合金钢")):
        return {}
    mawp = _decimal_value(_first(record, "maximumAllowableWorkingPressureMPa", "mawpMPa"))
    dn = _decimal_value(_first(record, "nominalDiameterMM", "dn"))
    if mawp is None or dn is None:
        return {}
    valve_type = _norm(_first(record, "valveType", "productName", "model"))
    is_check = "check" in valve_type or "止回阀" in valve_type
    hold_seconds = _gbt26480_hold_seconds(dn, is_check=is_check, test_name=test_name)
    if test_name == "shell":
        return {
            "minimumPressureMPa": mawp * Decimal("1.5"),
            "minimumHoldSeconds": hold_seconds,
            "allowedMedia": ["水", "煤油", "非腐蚀性液体", "氮气", "空气"],
            "requiredProcedureSteps": ["ends_closed", "partially_open", "body_cavity_pressurized", "air_removed_for_liquid"],
            "sourceClause": "GB/T 26480-2011 5.3.7、5.4、5.5、7.1-7.2",
        }
    seal_level = _norm(_first(record, "sealTestLevel", "sealTestType", "sealPressureLevel"))
    if seal_level in {"low", "lowpressure", "低压", "低压密封"}:
        return {
            "minimumPressureMPa": Decimal("0.4"),
            "maximumPressureMPa": Decimal("0.7"),
            "minimumHoldSeconds": hold_seconds,
            "allowedMedia": ["空气", "氮气", "惰性气体"],
            "requiredProcedureSteps": ["sealing_surface_clean", "outlet_leak_observed"],
            "sourceClause": "GB/T 26480-2011 5.3.7、5.4、5.5、7.4",
        }
    if seal_level in {"high", "highpressure", "高压", "高压密封"}:
        return {
            "minimumPressureMPa": mawp if is_check else mawp * Decimal("1.1"),
            "minimumHoldSeconds": hold_seconds,
            "allowedMedia": ["水", "煤油", "非腐蚀性液体", "氮气", "空气"],
            "requiredProcedureSteps": ["outlet_leak_observed"],
            "sourceClause": "GB/T 26480-2011 5.3.7、5.4、5.5、7.5",
        }
    return {}


def _gbt26480_hold_seconds(dn: Decimal, *, is_check: bool, test_name: str) -> int:
    if dn <= 50:
        return 60 if is_check else 15
    if dn <= 150:
        return 60
    if dn <= 300:
        return 60 if is_check else 120
    if test_name == "shell":
        return 120 if is_check else 300
    return 120


def _compare_test_parameters(
    actual: dict[str, Any],
    required: dict[str, Any],
    standard: str | None,
    record: dict[str, Any],
    test_name: str,
) -> dict[str, Any]:
    if not required:
        return {"result": "evidence_insufficient", "reasonCodes": ["standard_parameter_profile_not_frozen"]}
    missing_profile_dimensions = [
        key
        for key in ("minimumPressureMPa", "minimumHoldSeconds", "allowedMedia", "requiredProcedureSteps")
        if not _present(required.get(key))
    ]
    if missing_profile_dimensions:
        return {
            "result": "evidence_insufficient",
            "reasonCodes": ["standard_parameter_profile_incomplete"],
            "missingProfileDimensions": missing_profile_dimensions,
            "sourceClause": required.get("sourceClause"),
        }
    reasons = []
    pressure = _decimal_value(actual.get("pressureMPa"))
    minimum_pressure = _decimal_value(required.get("minimumPressureMPa"))
    maximum_pressure = _decimal_value(required.get("maximumPressureMPa"))
    hold = _hold_seconds(actual)
    minimum_hold = _decimal_value(required.get("minimumHoldSeconds"))
    allowed_media = {_norm(value) for value in _list(required.get("allowedMedia"))}
    if minimum_pressure is not None and (pressure is None or pressure < minimum_pressure):
        reasons.append(f"{test_name}_pressure_below_required")
    if maximum_pressure is not None and (pressure is None or pressure > maximum_pressure):
        reasons.append(f"{test_name}_pressure_above_allowed")
    if minimum_hold is not None and (hold is None or Decimal(str(hold)) < minimum_hold):
        reasons.append(f"{test_name}_hold_time_below_required")
    if allowed_media and not _medium_allowed(actual.get("medium"), allowed_media):
        reasons.append(f"{test_name}_medium_not_allowed")
    max_leakage = _decimal_value(required.get("maximumLeakage"))
    leakage = _decimal_value(actual.get("leakage"))
    if max_leakage is not None and (leakage is None or leakage > max_leakage):
        reasons.append(f"{test_name}_leakage_above_allowed")
    required_steps = {_norm(value) for value in _list(required.get("requiredProcedureSteps"))}
    actual_steps = {_norm(value) for value in _list(actual.get("procedureSteps"))}
    missing_steps = sorted(step for step in required_steps if not _procedure_step_covered(step, actual_steps))
    if missing_steps:
        reasons.append(f"{test_name}_procedure_steps_missing")
    return {
        "result": "failed" if reasons else "passed",
        "reasonCodes": reasons,
        "actualPressureMPa": pressure,
        "minimumPressureMPa": minimum_pressure,
        "actualHoldSeconds": hold,
        "minimumHoldSeconds": minimum_hold,
        "missingProcedureSteps": missing_steps,
    }


def _procedure_step_covered(required_step: str, actual_steps: set[str]) -> bool:
    aliases = {
        "endsclosed": ("两端封闭", "封闭两端", "endsclosed"),
        "partiallyopen": ("部分开启", "阀门部分开启", "partiallyopen"),
        "bodycavitypressurized": ("体腔加压", "阀体加压", "bodycavitypressurized"),
        "airremovedforliquid": ("排除空气", "排净空气", "airremoved", "vented"),
        "sealingsurfaceclean": ("密封面清洁", "密封面干净", "无油迹", "sealingsurfaceclean"),
        "outletleakobserved": ("出口端检查", "观察泄漏", "检漏", "outletleakobserved"),
    }
    candidates = aliases.get(required_step, (required_step,))
    return any(_norm(alias) in actual for actual in actual_steps for alias in candidates)


def _medium_allowed(actual: Any, allowed_media: set[str]) -> bool:
    normalized = _norm(actual)
    if not normalized:
        return False
    return any(candidate == normalized or candidate in normalized or normalized in candidate for candidate in allowed_media)


def _canonical_standard(value: Any) -> str | None:
    return _SUPPORTED_VALVE_STANDARDS.get(_norm(value))


def _standard_list(value: Any) -> list[str]:
    values = _list(value)
    return [canonical or str(item) for item in values if (canonical := _canonical_standard(item)) or _present(item)]


def _hold_seconds(value: dict[str, Any]) -> int | None:
    seconds = _decimal_value(value.get("holdSeconds"))
    if seconds is not None:
        return int(seconds)
    minutes = _decimal_value(value.get("holdMinutes"))
    return int(minutes * 60) if minutes is not None else None


def _records(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _list(value: Any) -> list[Any]:
    if isinstance(value, str):
        return [item.strip() for item in re.split(r"[,，;；、\n]", value) if item.strip()]
    return list(value) if isinstance(value, (list, tuple, set)) else []


def _first(value: dict[str, Any], *keys: str) -> Any:
    return next((value.get(key) for key in keys if key and _present(value.get(key))), None)


def _present(value: Any) -> bool:
    return value not in (None, "", [], {})


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", str(value or "").lower())


def _same(left: Any, right: Any) -> bool:
    return _present(left) and _present(right) and _norm(left) == _norm(right)


def _contains_any(value: Any, markers: tuple[str, ...]) -> bool:
    normalized = _norm(value)
    return any(_norm(marker) in normalized for marker in markers)


def _truth(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    normalized = _norm(value)
    if normalized in {"true", "yes", "present", "是", "有", "已完成", "已批准", "已发生", "已使用"}:
        return True
    if normalized in {"false", "no", "missing", "否", "无", "未完成", "未批准", "未发生", "未使用"}:
        return False
    return None


def _accepted(value: Any) -> bool:
    normalized = _norm(value)
    return any(_norm(item) in normalized for item in _PASS)


def _date_key(value: Any) -> str | None:
    match = re.search(r"(\d{4})[^0-9]?(\d{1,2})[^0-9]?(\d{1,2})", str(value or ""))
    return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}" if match else None


def _integer(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        numeric = _decimal_value(value)
        return int(numeric) if numeric is not None else None


def _decimal_value(value: Any) -> Decimal | None:
    parsed = decimal(value)
    if parsed is not None:
        return parsed
    match = re.search(r"[-+]?\d+(?:\.\d+)?", str(value or ""))
    return Decimal(match.group(0)) if match else None


def _id(value: dict[str, Any], index: int) -> str:
    return str(_first(value, "componentItemId", "itemId", "id") or f"ITEM-{index}")


def _snake(value: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", value).lower()


def _aggregate(failed: bool, incomplete: bool) -> str:
    return "failed" if failed else "evidence_insufficient" if incomplete else "passed"


def _insufficient(tool_name: str, reason: str, rule_version: str) -> dict[str, Any]:
    output = result(tool_name, "evidence_insufficient", facts={}, checks=[], rule_version=rule_version)
    output["reasonCodes"] = [reason]
    return output
