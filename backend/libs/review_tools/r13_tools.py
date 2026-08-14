from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from libs.review_orchestrator.deterministic_tools import check, decimal, normalize_value, result

R13_RULE_VERSION = "r13-component-certificate-coverage-tsg-d7006-2020-samr41-v1"

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
_INVALID_STATUSES = {"expired", "revoked", "suspended", "invalid", "作废", "撤销", "暂停", "失效", "过期"}
_NON_COMPONENT_MARKERS = (
    "螺栓",
    "螺母",
    "垫圈",
    "支吊架",
    "焊条",
    "焊丝",
    "焊材",
    "油漆",
    "涂料",
    "保温材料",
)


def classify_r13_component_requirements(arguments: dict[str, Any]) -> dict[str, Any]:
    design_items = _list_of_dicts(arguments.get("designItems"))
    if not design_items:
        return _insufficient("classify_r13_component_requirements", arguments, "r13_design_items_missing")

    matrix = [_classification_record(item, index) for index, item in enumerate(design_items, 1)]
    checks: list[dict[str, Any]] = []
    incomplete = False
    for index, item in enumerate(matrix, 1):
        supervision_known = item["supervisionRequirementKnown"] is True
        type_test_known = item["typeTestRequirementKnown"] is True
        incomplete = incomplete or not supervision_known or not type_test_known
        checks.extend(
            [
                check(
                    f"component_{index}_supervision_requirement_known",
                    supervision_known,
                    item.get("requiresManufacturingSupervision"),
                    "boolean_requirement",
                ),
                check(
                    f"component_{index}_type_test_requirement_known",
                    type_test_known,
                    item.get("requiresTypeTest"),
                    "boolean_requirement",
                ),
            ]
        )
    output = result(
        "classify_r13_component_requirements",
        "evidence_insufficient" if incomplete else "passed",
        facts={"designItemCount": len(design_items), "requirementMatrix": matrix},
        checks=checks,
        rule_version=str(arguments.get("ruleVersion") or R13_RULE_VERSION),
    )
    output["requirementMatrix"] = matrix
    if incomplete:
        output["warnings"] = ["one_or_more_component_requirements_unclassifiable"]
    return output


def evaluate_r13_supervision_certificate_completeness(arguments: dict[str, Any]) -> dict[str, Any]:
    design_items = _list_of_dicts(arguments.get("designItems"))
    certificates = _list_of_dicts(arguments.get("supervisionCertificates"))
    if not design_items:
        return _insufficient(
            "evaluate_r13_supervision_certificate_completeness",
            arguments,
            "r13_design_items_missing",
        )

    checks: list[dict[str, Any]] = []
    coverage_matrix: list[dict[str, Any]] = []
    incomplete = False
    failed = False
    applicable_count = 0
    for index, item in enumerate(design_items, 1):
        classification = _classification_record(item, index)
        item_id = classification["componentItemId"]
        if not classification["supervisionRequirementKnown"]:
            incomplete = True
            checks.append(
                check(
                    f"component_{index}_supervision_requirement_known",
                    False,
                    classification.get("classificationReason"),
                    "classifiable_from_tsg_d7006_1_2_1",
                )
            )
            coverage_matrix.append(
                {**classification, "result": "evidence_insufficient", "reasonCodes": ["supervision_requirement_unknown"]}
            )
            continue
        if not classification["requiresManufacturingSupervision"]:
            coverage_matrix.append({**classification, "result": "not_applicable", "reasonCodes": []})
            continue

        applicable_count += 1
        granularity = str(classification.get("supervisionGranularity") or "")
        trace_value = _trace_value(item, granularity)
        if not _organization(item.get("manufacturerName")) or not trace_value:
            incomplete = True
            missing = []
            if not _organization(item.get("manufacturerName")):
                missing.append("manufacturerName")
            if not trace_value:
                missing.append("batchNo" if granularity == "batch" else "serialNo")
            checks.append(check(f"component_{index}_supervision_trace_facts", False, missing, "complete"))
            coverage_matrix.append(
                {**classification, "result": "evidence_insufficient", "reasonCodes": ["supervision_trace_facts_missing", *missing]}
            )
            continue

        evaluated = [
            _match_supervision_certificate(item, classification, certificate, granularity, trace_value)
            for certificate in certificates
        ]
        passed_match = next((candidate for candidate in evaluated if candidate["state"] == "passed"), None)
        if passed_match:
            checks.append(
                check(
                    f"component_{index}_supervision_certificate_coverage",
                    True,
                    passed_match.get("certificateId"),
                    {"granularity": granularity, "traceValue": trace_value},
                )
            )
            coverage_matrix.append(
                {
                    **classification,
                    "result": "passed",
                    "matchedCertificateId": passed_match.get("certificateId"),
                    "traceValue": trace_value,
                    "reasonCodes": [],
                }
            )
            continue

        insufficient_match = next((candidate for candidate in evaluated if candidate["state"] == "evidence_insufficient"), None)
        if insufficient_match:
            incomplete = True
            reason_codes = insufficient_match.get("reasonCodes") or ["certificate_link_fields_missing"]
            checks.append(check(f"component_{index}_supervision_certificate_coverage", False, reason_codes, "complete_coverage"))
            coverage_matrix.append(
                {
                    **classification,
                    "result": "evidence_insufficient",
                    "matchedCertificateId": insufficient_match.get("certificateId"),
                    "traceValue": trace_value,
                    "reasonCodes": reason_codes,
                }
            )
            continue

        failed = True
        reason = "supervision_certificate_missing" if not certificates else "supervision_certificate_not_covering_item"
        checks.append(check(f"component_{index}_supervision_certificate_coverage", False, None, {"granularity": granularity, "traceValue": trace_value}))
        coverage_matrix.append(
            {**classification, "result": "failed", "traceValue": trace_value, "reasonCodes": [reason]}
        )

    if failed:
        business_result = "failed"
    elif incomplete:
        business_result = "evidence_insufficient"
    elif applicable_count == 0:
        business_result = "not_applicable"
    else:
        business_result = "passed"
    output = result(
        "evaluate_r13_supervision_certificate_completeness",
        business_result,
        facts={
            "designItemCount": len(design_items),
            "certificateCount": len(certificates),
            "applicableItemCount": applicable_count,
            "coverageMatrix": coverage_matrix,
        },
        checks=checks,
        rule_version=str(arguments.get("ruleVersion") or R13_RULE_VERSION),
    )
    output["coverageMatrix"] = coverage_matrix
    return output


def evaluate_r13_type_test_coverage(arguments: dict[str, Any]) -> dict[str, Any]:
    design_items = _list_of_dicts(arguments.get("designItems"))
    reports = _list_of_dicts(arguments.get("typeTestReports"))
    if not design_items:
        return _insufficient("evaluate_r13_type_test_coverage", arguments, "r13_design_items_missing")

    checks: list[dict[str, Any]] = []
    coverage_matrix: list[dict[str, Any]] = []
    incomplete = False
    failed = False
    applicable_count = 0
    for index, item in enumerate(design_items, 1):
        classification = _classification_record(item, index)
        if not classification["typeTestRequirementKnown"]:
            incomplete = True
            checks.append(
                check(
                    f"component_{index}_type_test_requirement_known",
                    False,
                    classification.get("classificationReason"),
                    "classifiable_from_samr_2021_41_notes_3_4",
                )
            )
            coverage_matrix.append(
                {**classification, "result": "evidence_insufficient", "reasonCodes": ["type_test_requirement_unknown"]}
            )
            continue
        if not classification["requiresTypeTest"]:
            coverage_matrix.append({**classification, "result": "not_applicable", "reasonCodes": []})
            continue

        applicable_count += 1
        if not _organization(item.get("manufacturerName")) or not _component_has_scope_fact(item):
            incomplete = True
            missing = []
            if not _organization(item.get("manufacturerName")):
                missing.append("manufacturerName")
            if not _component_has_scope_fact(item):
                missing.append("specification_or_numeric_scope")
            checks.append(check(f"component_{index}_type_test_scope_facts", False, missing, "complete"))
            coverage_matrix.append(
                {**classification, "result": "evidence_insufficient", "reasonCodes": ["design_scope_facts_missing", *missing]}
            )
            continue

        evaluated = [_match_type_test_report(item, classification, report) for report in reports]
        passed_match = next((candidate for candidate in evaluated if candidate["state"] == "passed"), None)
        if passed_match:
            checks.append(
                check(
                    f"component_{index}_type_test_coverage",
                    True,
                    passed_match.get("reportId"),
                    "product_manufacturer_material_process_and_scope_covered",
                )
            )
            coverage_matrix.append(
                {
                    **classification,
                    "result": "passed",
                    "matchedReportId": passed_match.get("reportId"),
                    "reasonCodes": [],
                }
            )
            continue

        insufficient_match = next((candidate for candidate in evaluated if candidate["state"] == "evidence_insufficient"), None)
        if insufficient_match:
            incomplete = True
            reason_codes = insufficient_match.get("reasonCodes") or ["type_test_scope_fields_missing"]
            checks.append(check(f"component_{index}_type_test_coverage", False, reason_codes, "complete_coverage"))
            coverage_matrix.append(
                {
                    **classification,
                    "result": "evidence_insufficient",
                    "matchedReportId": insufficient_match.get("reportId"),
                    "reasonCodes": reason_codes,
                }
            )
            continue

        failed = True
        reason = "type_test_report_missing" if not reports else "type_test_report_not_covering_item"
        checks.append(check(f"component_{index}_type_test_coverage", False, None, "covering_type_test_report"))
        coverage_matrix.append({**classification, "result": "failed", "reasonCodes": [reason]})

    if failed:
        business_result = "failed"
    elif incomplete:
        business_result = "evidence_insufficient"
    elif applicable_count == 0:
        business_result = "not_applicable"
    else:
        business_result = "passed"
    output = result(
        "evaluate_r13_type_test_coverage",
        business_result,
        facts={
            "designItemCount": len(design_items),
            "reportCount": len(reports),
            "applicableItemCount": applicable_count,
            "coverageMatrix": coverage_matrix,
        },
        checks=checks,
        rule_version=str(arguments.get("ruleVersion") or R13_RULE_VERSION),
    )
    output["coverageMatrix"] = coverage_matrix
    return output


def classify_component_requirement(item: dict[str, Any]) -> dict[str, Any]:
    explicit_supervision = item.get("requiresManufacturingSupervision")
    explicit_type_test = item.get("requiresTypeTest")
    explicit_complete = isinstance(explicit_supervision, bool) and isinstance(explicit_type_test, bool)
    text = _component_text(item)
    category: str | None = None
    supervision: bool | None = None
    type_test: bool | None = None
    granularity: str | None = None
    reason = "component_category_not_in_frozen_r13_directory"
    source_refs: list[str] = []

    if any(marker in text for marker in _NON_COMPONENT_MARKERS):
        category, supervision, type_test = "non_r13_component", False, False
        reason = "known_non_r13_material"
    elif any(marker in text for marker in ("带金属骨架聚乙烯管", "纤维增强聚乙烯管")):
        category, supervision, type_test = "composite_pipe", False, True
        reason = "samr_2021_41_note_4_composite_pipe"
        source_refs = ["SAMR-2021-41-附件1-注四"]
    elif any(marker in text for marker in ("埋弧焊钢管", "螺旋缝埋弧焊", "直缝埋弧焊", "lsaw", "ssaw", "saw钢管")):
        category, supervision, type_test, granularity = "submerged_arc_welded_steel_pipe", True, True, "batch"
        reason = "tsg_d7006_1_2_1_submerged_arc_welded_pipe"
        source_refs = ["TSG-D7006-2020-1.2.1", "TSG-D7006-2020-A1.2", "SAMR-2021-41-附件1-注三"]
    elif "聚乙烯管件" in text or "pe管件" in text:
        category, supervision, type_test = "polyethylene_pipe_fitting", False, True
        reason = "samr_2021_41_note_3_polyethylene_fitting"
        source_refs = ["SAMR-2021-41-附件1-注三"]
    elif ("聚乙烯管" in text or "pe管" in text) and "管件" not in text:
        category, supervision, type_test, granularity = "polyethylene_pipe", True, True, "batch"
        reason = "tsg_d7006_1_2_1_polyethylene_pipe"
        source_refs = ["TSG-D7006-2020-1.2.1", "TSG-D7006-2020-A1.2", "SAMR-2021-41-附件1-注三"]
    elif any(marker in text for marker in ("燃气调压装置", "减温减压装置", "工厂化预制管段", "流量计壳体", "流量计(壳体)", "流量计（壳体）")):
        category, supervision, type_test = _assembly_category(text), True, True
        granularity = "batch" if item.get("supervisionMode") == "batch" or item.get("batchSupervisionEligible") is True else "unit"
        reason = "tsg_d7006_1_2_1_supervised_component_assembly"
        source_refs = ["TSG-D7006-2020-1.2.1", "TSG-D7006-2020-A1.2", "SAMR-2021-41-附件1-注三"]
    elif any(marker in text for marker in ("井口装置", "采油树", "节流压井管汇", "阻火器")):
        category, supervision, type_test = _assembly_category(text), False, True
        reason = "samr_2021_41_note_4_type_test_only_assembly"
        source_refs = ["SAMR-2021-41-附件1-注四"]
    elif "热扩" in text and ("无缝钢管" in text or "无缝管" in text):
        category, supervision, type_test = "hot_expanded_seamless_steel_pipe", False, True
        reason = "samr_2021_41_note_4_hot_expanded_seamless_pipe"
        source_refs = ["SAMR-2021-41-附件1-注四"]
    elif any(marker in text for marker in ("有色金属管", "球墨铸铁管", "复合管")) and "管件" not in text:
        category, supervision, type_test = _first_category(
            text,
            (("有色金属管", "nonferrous_metal_pipe"), ("球墨铸铁管", "ductile_iron_pipe"), ("复合管", "composite_pipe")),
        ), False, True
        reason = "samr_2021_41_note_4_type_test_only_pipe"
        source_refs = ["SAMR-2021-41-附件1-注四"]
    elif "无缝钢管" in text or "无缝管" in text:
        category, supervision, type_test = "seamless_steel_pipe", False, True
        reason = "samr_2021_41_note_3_licensed_pipe"
        source_refs = ["SAMR-2021-41-附件1-注三"]
    elif any(marker in text for marker in ("焊接钢管", "焊管", "直缝钢管", "螺旋钢管")):
        category, supervision, type_test = "welded_steel_pipe", None, True
        reason = "welded_pipe_process_needed_to_exclude_submerged_arc_supervision"
        source_refs = ["TSG-D7006-2020-1.2.1", "SAMR-2021-41-附件1-注三"]
    elif "钢管" in text or text.endswith("管"):
        category, supervision, type_test = "pressure_pipe_unspecified", None, True
        reason = "pipe_material_or_process_needed_for_supervision_classification"
        source_refs = ["TSG-D7006-2020-1.2.1", "SAMR-2021-41-附件1-注三注四"]
    elif "复合管件" in text or ("非金属管件" in text and "聚乙烯" not in text):
        category, supervision, type_test = "type_test_only_pipe_fitting", False, True
        reason = "samr_2021_41_note_4_type_test_only_fitting"
        source_refs = ["SAMR-2021-41-附件1-注四"]
    elif any(marker in text for marker in ("弯头", "三通", "四通", "异径", "管帽", "管件", "接头")):
        category, supervision, type_test = "pressure_pipe_fitting", False, True
        reason = "samr_2021_41_note_3_licensed_fitting"
        source_refs = ["SAMR-2021-41-附件1-注三"]
    elif "阀" in text:
        category, supervision, type_test = "pressure_piping_valve", False, True
        reason = "samr_2021_41_notes_3_4_pressure_piping_valve"
        source_refs = ["SAMR-2021-41-附件1-注三注四"]
    elif "法兰" in text and any(marker in text for marker in ("钢制锻造", "钢制锻制", "锻制法兰", "锻造法兰")):
        category, supervision, type_test = "pressure_piping_flange", False, True
        reason = "samr_2021_41_note_3_steel_forged_flange"
        source_refs = ["SAMR-2021-41-附件1-注三"]
    elif "法兰" in text:
        category, supervision, type_test = "pressure_piping_flange_unspecified", False, None
        reason = "flange_material_and_manufacturing_method_needed_for_type_test_classification"
        source_refs = ["SAMR-2021-41-附件1-注三"]
    elif any(marker in text for marker in ("旋转补偿器", "非金属膨胀节")):
        category, supervision, type_test = "type_test_only_compensator", False, True
        reason = "samr_2021_41_note_4_type_test_only_compensator"
        source_refs = ["SAMR-2021-41-附件1-注四"]
    elif "金属波纹膨胀节" in text:
        category, supervision, type_test = "metal_bellows_expansion_joint", False, True
        reason = "samr_2021_41_note_3_licensed_compensator"
        source_refs = ["SAMR-2021-41-附件1-注三"]
    elif "补偿器" in text or "膨胀节" in text:
        category, supervision, type_test = "compensator_unspecified", False, None
        reason = "compensator_structure_needed_for_type_test_classification"
        source_refs = ["SAMR-2021-41-附件1-注三注四"]
    elif "密封元件" in text or "密封件" in text:
        category, supervision, type_test = "pressure_piping_sealing_element", False, True
        reason = "samr_2021_41_note_4_sealing_element"
        source_refs = ["SAMR-2021-41-附件1-注四"]
    elif "防腐管道元件" in text or ("防腐" in text and "管道元件" in text):
        category, supervision, type_test = "anti_corrosion_piping_component", False, True
        reason = "samr_2021_41_note_4_anti_corrosion_component"
        source_refs = ["SAMR-2021-41-附件1-注四"]
    elif "元件组合装置" in text:
        category, supervision, type_test = "component_assembly_unspecified", None, True
        reason = "assembly_subtype_needed_for_supervision_classification"
        source_refs = ["TSG-D7006-2020-1.2.1", "SAMR-2021-41-附件1-注三注四"]

    if isinstance(explicit_supervision, bool):
        supervision = explicit_supervision
        source_refs.append("structured_business_fact:requiresManufacturingSupervision")
    if isinstance(explicit_type_test, bool):
        type_test = explicit_type_test
        source_refs.append("structured_business_fact:requiresTypeTest")
    if explicit_complete and category is None:
        category = str(item.get("regulatoryCategory") or "explicit_business_classification")
        reason = "requirements_supplied_by_structured_business_fact"

    return {
        "regulatoryCategory": category,
        "requiresManufacturingSupervision": supervision,
        "supervisionRequirementKnown": isinstance(supervision, bool),
        "supervisionGranularity": granularity if supervision is True else None,
        "requiresTypeTest": type_test,
        "typeTestRequirementKnown": isinstance(type_test, bool),
        "classificationReason": reason,
        "sourceClauseRefs": list(dict.fromkeys(source_refs)),
    }


def _classification_record(item: dict[str, Any], index: int) -> dict[str, Any]:
    item_id = str(item.get("componentItemId") or item.get("itemId") or f"R13-ITEM-{index}")
    return {
        "componentItemId": item_id,
        "componentType": item.get("componentType") or item.get("productName"),
        "manufacturerName": item.get("manufacturerName"),
        "specification": item.get("specification"),
        "batchNo": item.get("batchNo"),
        "serialNo": item.get("serialNo"),
        **classify_component_requirement(item),
    }


def _match_supervision_certificate(
    item: dict[str, Any],
    classification: dict[str, Any],
    certificate: dict[str, Any],
    granularity: str,
    trace_value: str,
) -> dict[str, Any]:
    certificate_id = str(
        certificate.get("certificateId")
        or certificate.get("certificateNo")
        or certificate.get("documentVersionId")
        or ""
    )
    cert_class = classify_component_requirement(certificate)
    item_org = _organization(item.get("manufacturerName"))
    cert_org = _organization(certificate.get("manufacturerName") or certificate.get("manufacturer"))
    if cert_org and item_org != cert_org:
        return {"state": "failed", "certificateId": certificate_id, "reasonCodes": ["manufacturer_mismatch"]}
    if not cert_org:
        return {"state": "evidence_insufficient", "certificateId": certificate_id, "reasonCodes": ["certificate_manufacturer_missing"]}
    category_match = _category_matches(classification.get("regulatoryCategory"), cert_class.get("regulatoryCategory"))
    if category_match is False:
        return {"state": "failed", "certificateId": certificate_id, "reasonCodes": ["product_category_mismatch"]}
    if category_match is None:
        return {"state": "evidence_insufficient", "certificateId": certificate_id, "reasonCodes": ["certificate_product_category_missing"]}
    conclusion_state = _conclusion_state(certificate)
    if conclusion_state != "passed":
        return {
            "state": conclusion_state,
            "certificateId": certificate_id,
            "reasonCodes": ["certificate_conclusion_missing" if conclusion_state == "evidence_insufficient" else "certificate_conclusion_not_accepted"],
        }
    covered_values = _trace_values(certificate, granularity)
    if not covered_values:
        return {
            "state": "evidence_insufficient",
            "certificateId": certificate_id,
            "reasonCodes": ["certificate_batch_missing" if granularity == "batch" else "certificate_serial_missing"],
        }
    if _normalized(trace_value) not in {_normalized(value) for value in covered_values}:
        return {"state": "failed", "certificateId": certificate_id, "reasonCodes": ["certificate_trace_value_mismatch"]}
    if not certificate_id:
        return {"state": "evidence_insufficient", "certificateId": None, "reasonCodes": ["certificate_number_missing"]}
    return {"state": "passed", "certificateId": certificate_id, "reasonCodes": []}


def _match_type_test_report(
    item: dict[str, Any],
    classification: dict[str, Any],
    report_item: dict[str, Any],
) -> dict[str, Any]:
    report_id = str(
        report_item.get("scopeItemId")
        or report_item.get("reportId")
        or report_item.get("reportNo")
        or report_item.get("certificateNo")
        or report_item.get("documentVersionId")
        or ""
    )
    reasons_missing: list[str] = []
    reasons_mismatch: list[str] = []
    report_class = classify_component_requirement(report_item)
    category_match = _category_matches(classification.get("regulatoryCategory"), report_class.get("regulatoryCategory"))
    if category_match is False:
        reasons_mismatch.append("product_category_mismatch")
    elif category_match is None:
        reasons_missing.append("report_product_category_missing")

    item_org = _organization(item.get("manufacturerName"))
    report_org = _organization(
        report_item.get("manufacturerName")
        or report_item.get("manufacturer")
        or report_item.get("applicantName")
    )
    if not report_org:
        reasons_missing.append("report_manufacturer_missing")
    elif report_org != item_org:
        reasons_mismatch.append("manufacturer_mismatch")

    if not str(report_item.get("testOrganization") or report_item.get("testOrg") or "").strip():
        reasons_missing.append("type_test_organization_missing")
    conclusion_state = _conclusion_state(report_item)
    if conclusion_state == "failed":
        reasons_mismatch.append("type_test_conclusion_not_accepted")
    elif conclusion_state == "evidence_insufficient":
        reasons_missing.append("type_test_conclusion_missing")

    report_status = _normalized(report_item.get("status") or report_item.get("certificateStatus"))
    if report_status and report_status in {_normalized(value) for value in _INVALID_STATUSES}:
        reasons_mismatch.append("type_test_report_invalid_status")

    _compare_optional_text_scope(item, report_item, "material", ("materials", "materialScope", "material"), reasons_missing, reasons_mismatch)
    _compare_optional_text_scope(item, report_item, "structure", ("structures", "structureScope", "structure"), reasons_missing, reasons_mismatch)
    _compare_optional_text_scope(item, report_item, "manufacturingProcess", ("manufacturingProcesses", "processScope", "manufacturingProcess"), reasons_missing, reasons_mismatch)

    item_diameter = _number(item.get("nominalDiameterMM") or item.get("nominalDiameter") or item.get("diameterMM"))
    item_pressure = _item_pressure_mpa(item)
    report_text = _normalized(
        " ".join(
            str(report_item.get(key) or "")
            for key in ("specificationScope", "specification", "scopeDescription", "productName")
        )
    )
    exact_specification = _normalized(item.get("specification"))
    scope_evaluated = False
    if item_diameter is not None:
        scope_evaluated = True
        state = _number_in_range(
            item_diameter,
            report_item.get("nominalDiameterMinMM") or report_item.get("diameterMinMM"),
            report_item.get("nominalDiameterMaxMM") or report_item.get("diameterMaxMM"),
        )
        if state is None and exact_specification and exact_specification in report_text:
            state = True
        if state is None:
            reasons_missing.append("type_test_diameter_scope_missing")
        elif not state:
            reasons_mismatch.append("type_test_diameter_not_covered")
    if item_pressure is not None:
        scope_evaluated = True
        state = _number_in_range(
            item_pressure,
            report_item.get("nominalPressureMinMPa") or report_item.get("pressureMinMPa"),
            report_item.get("nominalPressureMaxMPa") or report_item.get("pressureMaxMPa"),
        )
        if state is None and exact_specification and exact_specification in report_text:
            state = True
        if state is None:
            reasons_missing.append("type_test_pressure_scope_missing")
        elif not state:
            reasons_mismatch.append("type_test_pressure_not_covered")
    if exact_specification and not scope_evaluated:
        scope_evaluated = True
        if not report_text:
            reasons_missing.append("type_test_specification_scope_missing")
        elif exact_specification not in report_text and report_text not in exact_specification:
            reasons_mismatch.append("type_test_specification_not_covered")
    if not scope_evaluated:
        reasons_missing.append("design_component_scope_missing")
    if not report_id:
        reasons_missing.append("type_test_report_number_missing")

    if reasons_mismatch:
        return {"state": "failed", "reportId": report_id or None, "reasonCodes": list(dict.fromkeys(reasons_mismatch))}
    if reasons_missing:
        return {
            "state": "evidence_insufficient",
            "reportId": report_id or None,
            "reasonCodes": list(dict.fromkeys(reasons_missing)),
        }
    return {"state": "passed", "reportId": report_id, "reasonCodes": []}


def _compare_optional_text_scope(
    item: dict[str, Any],
    report_item: dict[str, Any],
    item_key: str,
    report_keys: tuple[str, ...],
    missing: list[str],
    mismatch: list[str],
) -> None:
    actual = _normalized(item.get(item_key))
    if not actual:
        return
    values: list[Any] = []
    for key in report_keys:
        value = report_item.get(key)
        if isinstance(value, (list, tuple, set)):
            values.extend(value)
        elif value not in {None, ""}:
            values.append(value)
    normalized_values = [_normalized(value) for value in values if _normalized(value)]
    if not normalized_values:
        missing.append(f"type_test_{item_key}_scope_missing")
    elif not any(actual == value or actual in value or value in actual for value in normalized_values):
        mismatch.append(f"type_test_{item_key}_not_covered")


def _component_has_scope_fact(item: dict[str, Any]) -> bool:
    return any(
        value not in {None, ""}
        for value in (
            item.get("specification"),
            item.get("nominalDiameterMM"),
            item.get("nominalDiameter"),
            item.get("nominalPressureMPa"),
            item.get("pressureMPa"),
            item.get("pressureClass"),
        )
    )


def _trace_value(item: dict[str, Any], granularity: str) -> str | None:
    value = item.get("batchNo") if granularity == "batch" else item.get("serialNo") or item.get("productSerialNo")
    text = str(value or "").strip()
    return text or None


def _trace_values(certificate: dict[str, Any], granularity: str) -> list[str]:
    keys = ("coveredBatchNos", "batchNos", "batchNo") if granularity == "batch" else (
        "coveredSerialNos",
        "serialNos",
        "serialNo",
        "productSerialNo",
    )
    values: list[str] = []
    for key in keys:
        value = certificate.get(key)
        if isinstance(value, (list, tuple, set)):
            values.extend(str(item) for item in value if item not in {None, ""})
        elif value not in {None, ""}:
            values.extend(item.strip() for item in re.split(r"[,，;；/\n]+", str(value)) if item.strip())
    return list(dict.fromkeys(values))


def _conclusion_state(value: dict[str, Any]) -> str:
    conclusion = value.get("conclusion") or value.get("inspectionConclusion") or value.get("testConclusion")
    normalized = _normalized(conclusion)
    if not normalized:
        return "evidence_insufficient"
    if any(token in normalized for token in (_normalized(item) for item in _ACCEPTED_CONCLUSIONS)):
        return "passed"
    return "failed"


def _category_matches(left: Any, right: Any) -> bool | None:
    if not left or not right:
        return None
    left_text, right_text = str(left), str(right)
    if left_text == right_text:
        return True
    generic_categories = {
        "pressure_pipe_unspecified",
        "welded_steel_pipe",
        "pressure_pipe_fitting",
        "component_assembly_unspecified",
        "compensator_unspecified",
    }
    if left_text in generic_categories or right_text in generic_categories:
        return None
    return False


def _number_in_range(actual: Decimal, minimum: Any, maximum: Any) -> bool | None:
    low, high = _number(minimum), _number(maximum)
    if low is None and high is None:
        return None
    return (low is None or actual >= low) and (high is None or actual <= high)


def _number(value: Any) -> Decimal | None:
    direct = decimal(value)
    if direct is not None:
        return direct
    match = re.search(r"-?\d+(?:\.\d+)?", str(value or ""))
    return decimal(match.group(0)) if match else None


def _item_pressure_mpa(item: dict[str, Any]) -> Decimal | None:
    explicit = _number(item.get("nominalPressureMPa") or item.get("pressureMPa"))
    if explicit is not None:
        return explicit
    pressure_class = str(item.get("pressureClass") or "").strip()
    if not pressure_class:
        return None
    pn_match = re.search(r"\bPN\s*(\d+(?:\.\d+)?)\b", pressure_class, flags=re.IGNORECASE)
    if pn_match:
        pn_value = decimal(pn_match.group(1))
        return pn_value / Decimal(10) if pn_value is not None else None
    if "mpa" in pressure_class.lower():
        return _number(pressure_class)
    return None


def _component_text(item: dict[str, Any]) -> str:
    return _normalized(
        " ".join(
            str(item.get(key) or "")
            for key in (
                "regulatoryCategory",
                "componentType",
                "productType",
                "productName",
                "material",
                "structure",
                "manufacturingProcess",
                "specification",
                "scopeDescription",
            )
        )
    )


def _assembly_category(text: str) -> str:
    if "燃气调压装置" in text:
        return "gas_pressure_regulating_device"
    if "减温减压装置" in text:
        return "desuperheating_decompression_device"
    if "工厂化预制管段" in text:
        return "factory_prefabricated_pipe_section"
    if "流量计" in text:
        return "flowmeter_shell"
    if "节流压井管汇" in text:
        return "choke_kill_manifold"
    if "阻火器" in text:
        return "flame_arrester"
    return "wellhead_christmas_tree"


def _first_category(text: str, choices: tuple[tuple[str, str], ...]) -> str:
    return next(category for marker, category in choices if marker in text)


def _organization(value: Any) -> str:
    normalized = normalize_value(value, "organization_name")
    for suffix in ("有限责任公司", "股份有限公司", "有限公司"):
        if normalized.endswith(suffix):
            normalized = normalized[: -len(suffix)]
            break
    return normalized


def _normalized(value: Any) -> str:
    return normalize_value(value, "text")


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _insufficient(tool_name: str, arguments: dict[str, Any], reason: str) -> dict[str, Any]:
    output = result(
        tool_name,
        "evidence_insufficient",
        facts={"input": arguments, "reason": reason},
        checks=[],
        rule_version=str(arguments.get("ruleVersion") or R13_RULE_VERSION),
    )
    output["warnings"] = [reason]
    return output
