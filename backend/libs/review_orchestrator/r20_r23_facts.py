from __future__ import annotations

import re
from typing import Any

from libs.review_orchestrator.material_facts import (
    build_material_judgment,
    deduplicate,
    extract_material_design_items,
    extract_quality_certificates,
    iter_requested_parse_results,
)
from libs.review_orchestrator.r12_agent import stable_payload_hash
from libs.review_orchestrator.r13_facts import (
    _common_document_fields,
    _extract_type_test_reports,
    _file_name,
    _normalized_business_row,
    _present,
    _record_evidence,
    _value,
)


def build_r20_business_facts(state: dict[str, Any], review_run: dict[str, Any]) -> dict[str, Any]:
    design_items = extract_material_design_items(state, review_run, namespace="R20")
    type_test_reports: list[dict[str, Any]] = []
    technical_reviews: list[dict[str, Any]] = []
    material_data_documents: list[dict[str, Any]] = []
    for parse_result in iter_requested_parse_results(state, review_run):
        kind = _document_kind(state, parse_result)
        if kind == "type_test_report":
            type_test_reports.extend(_extract_type_test_reports(state, parse_result))
        elif kind == "technical_review_approval":
            technical_reviews.extend(_extract_records(state, parse_result, "R20TR", kind))
        elif kind == "new_material_data":
            material_data_documents.extend(_extract_records(state, parse_result, "R20MD", kind))
    facts = {
        "designItems": design_items,
        "typeTestReports": deduplicate(type_test_reports, "scopeItemId"),
        "technicalReviewApprovals": deduplicate(technical_reviews, "recordId"),
        "materialDataDocuments": deduplicate(material_data_documents, "recordId"),
    }
    _overlay(facts, review_run, "r20")
    judgment = build_material_judgment(
        [
            ("r20-design-item", facts["designItems"], ("materialGrade", "productName")),
            ("r20-type-test", facts["typeTestReports"], ("reportNo", "productName")),
            ("r20-technical-review", facts["technicalReviewApprovals"], ("approvalDocumentNo", "materialGrade")),
            ("r20-material-data", facts["materialDataDocuments"], ("documentNo", "materialGrade")),
        ]
    )
    return {"r20": facts, **judgment}


def build_r21_business_facts(state: dict[str, Any], review_run: dict[str, Any]) -> dict[str, Any]:
    inventory = extract_material_design_items(state, review_run, namespace="R21")
    transfer_records: list[dict[str, Any]] = []
    for parse_result in iter_requested_parse_results(state, review_run):
        kind = _document_kind(state, parse_result)
        if kind == "mark_transfer_record":
            transfer_records.extend(_extract_records(state, parse_result, "R21MT", kind))
        elif kind == "quality_certificate":
            inventory.extend(extract_quality_certificates(state, parse_result))
    records = deduplicate(transfer_records, "recordId")
    facts: dict[str, Any] = {
        "transferRecords": records,
        "materialInventory": deduplicate(inventory, "componentItemId"),
        "markTransferOccurred": True if records else _event_value(inventory, "markTransferOccurred"),
    }
    _overlay(facts, review_run, "r21")
    judgment = build_material_judgment(
        [
            ("r21-transfer-record", facts["transferRecords"], ("recordNo", "batchNo")),
            ("r21-material-inventory", facts["materialInventory"], ("materialGrade", "batchNo")),
        ]
    )
    return {"r21": facts, **judgment}


def build_r22_business_facts(state: dict[str, Any], review_run: dict[str, Any]) -> dict[str, Any]:
    design_items = extract_material_design_items(state, review_run, namespace="R22")
    substitutions: list[dict[str, Any]] = []
    actual_usage: list[dict[str, Any]] = []
    for parse_result in iter_requested_parse_results(state, review_run):
        kind = _document_kind(state, parse_result)
        if kind == "material_substitution_approval":
            substitutions.extend(_extract_records(state, parse_result, "R22SA", kind))
        elif kind in {"material_usage_record", "construction_record"}:
            actual_usage.extend(_extract_records(state, parse_result, "R22AU", kind))
    facts: dict[str, Any] = {
        "substitutionRecords": deduplicate(substitutions, "recordId"),
        "actualMaterialUsage": deduplicate(actual_usage, "recordId"),
        "materialSubstitutionOccurred": True if substitutions else _event_value(design_items, "materialSubstitutionOccurred"),
    }
    _overlay(facts, review_run, "r22")
    judgment = build_material_judgment(
        [
            ("r22-substitution", facts["substitutionRecords"], ("changeNo", "substituteMaterial")),
            ("r22-actual-usage", facts["actualMaterialUsage"], ("scope", "materialGrade")),
        ]
    )
    return {"r22": facts, **judgment}


def build_r23_business_facts(state: dict[str, Any], review_run: dict[str, Any]) -> dict[str, Any]:
    lots: list[dict[str, Any]] = []
    test_records: list[dict[str, Any]] = []
    construction_records: list[dict[str, Any]] = []
    design_refs: list[str] = []
    contract_refs: list[str] = []
    design_basis_seen = False
    contract_basis_seen = False
    for parse_result in iter_requested_parse_results(state, review_run):
        kind = _document_kind(state, parse_result)
        if kind in {"valve_pressure_test_report", "valve_combined_construction_test_record"}:
            extracted = _extract_records(state, parse_result, "R23VR", kind)
            test_records.extend(extracted)
            if kind == "valve_combined_construction_test_record":
                for record in extracted:
                    construction = dict(record)
                    construction["recordId"] = str(record.get("constructionRecordId") or f"{record['recordId']}-CONSTRUCTION")
                    construction["recordNo"] = record.get("constructionRecordId") or record.get("recordNo")
                    construction["recordKind"] = "valve_construction_record"
                    construction_records.append(construction)
            lots.extend(record for record in extracted if any(_present(record.get(key)) for key in ("lotSize", "testedCount", "pipelineGrade")))
        elif kind == "valve_construction_record":
            extracted = _extract_records(state, parse_result, "R23CR", kind)
            construction_records.extend(extracted)
            lots.extend(record for record in extracted if any(_present(record.get(key)) for key in ("lotSize", "testedCount", "pipelineGrade")))
        elif kind == "valve_sampling_record":
            lots.extend(_extract_records(state, parse_result, "R23VL", kind))
        elif kind == "design_document":
            design_basis_seen = True
            design_refs.extend(_standard_refs(parse_result))
        elif kind == "supply_contract":
            contract_basis_seen = True
            contract_refs.extend(_standard_refs(parse_result))
    facts: dict[str, Any] = {
        "designStandardRefs": _unique(design_refs),
        "contractStandardRefs": _unique(contract_refs),
        "designAndContractBasisChecked": design_basis_seen and contract_basis_seen,
        "testLots": deduplicate(lots, "lotId"),
        "constructionRecords": deduplicate(construction_records, "recordId"),
        "testRecords": deduplicate(test_records, "recordId"),
        "standardRequirementProfiles": {},
    }
    _overlay(facts, review_run, "r23")
    judgment = build_material_judgment(
        [
            ("r23-valve-lot", facts["testLots"], ("lotId", "pipelineGrade")),
            ("r23-valve-construction", facts["constructionRecords"], ("recordNo", "valveNo")),
            ("r23-valve-test", facts["testRecords"], ("reportNo", "valveNo")),
        ]
    )
    return {"r23": facts, **judgment}


def _extract_records(
    state: dict[str, Any],
    parse_result: dict[str, Any],
    namespace: str,
    record_kind: str,
) -> list[dict[str, Any]]:
    common, evidence_items = _common_document_fields(state, parse_result)
    rows = _all_rows(parse_result)
    output: list[dict[str, Any]] = []
    for index, row in enumerate(rows or [{}], 1):
        merged = {**common, **_normalized_business_row(row)}
        record_id = f"{namespace}-" + stable_payload_hash(
            {"documentVersionId": common["documentVersionId"], "rowIndex": index, "recordKind": record_kind}
        )[7:19].upper()
        evidence = _record_evidence(
            evidence_items,
            common["documentVersionId"],
            f"{namespace}EV-{record_id.rsplit('-', 1)[-1]}",
            _value(merged, "recordNo", "reportNo", "changeNo", "valveNo", "记录编号", "报告编号") or record_kind,
            row=row if rows else None,
            fallback_page=common.get("pageNo") or 1,
        )
        record = _mapped_record(merged, record_kind)
        record.update(
            {
                "recordId": record_id,
                "documentVersionId": common["documentVersionId"],
                "documentId": common.get("documentId"),
                "fileName": common.get("fileName"),
                "pageNo": evidence.get("pageNo"),
                "ocrConfidence": evidence.get("confidence"),
                "evidence": evidence,
            }
        )
        output.append({key: value for key, value in record.items() if value is not None})
    return output


def _mapped_record(values: dict[str, Any], kind: str) -> dict[str, Any]:
    data_items = _list_value(_value(values, "dataItems", "materialDataItems", "材料数据项目", "性能数据项目"))
    record: dict[str, Any] = {
        "recordKind": kind,
        "recordNo": _value(values, "recordNo", "记录编号"),
        "reportNo": _value(values, "reportNo", "报告编号", "试验报告编号"),
        "documentNo": _value(values, "documentNo", "文件编号"),
        "documentBodyPresent": _bool(_value(values, "documentBodyPresent", "文件本体完整", "书面文件存在")),
        "materialGrade": _value(values, "materialGrade", "material", "材料牌号", "材质"),
        "productName": _value(values, "productName", "componentType", "产品名称", "元件名称"),
        "conclusion": _value(values, "conclusion", "inspectionConclusion", "试验结论", "评审结论", "检验结论"),
        "approvalDocumentNo": _value(values, "approvalDocumentNo", "approvalNo", "批准文件编号", "批复编号"),
        "approvalOrganization": _value(values, "approvalOrganization", "approvalAuthority", "批准机构", "批准单位"),
        "approvalProcedureCompleted": _bool(_value(values, "approvalProcedureCompleted", "批准手续完成", "批准手续")),
        "technicalReviewPassed": _bool(_value(values, "technicalReviewPassed", "评审通过", "技术评审结论")),
        "dataItems": data_items,
        "originalMark": _value(values, "originalMark", "sourceMark", "原标志", "移植前标志"),
        "transferredMark": _value(values, "transferredMark", "newMark", "移植标志", "移植后标志"),
        "batchNo": _value(values, "batchNo", "lotNo", "批号", "炉批号"),
        "markMethod": _value(values, "markMethod", "transferMethod", "标志方法", "移植方法"),
        "inspector": _value(values, "inspector", "operator", "检查人", "移植人"),
        "identityChainVerified": _bool(_value(values, "identityChainVerified", "标志追溯一致", "标志一致")),
        "confusionControl": _bool(_value(values, "confusionControl", "防混料措施", "分区加工")),
        "harmfulSubstancesAbsent": _bool(_value(values, "harmfulSubstancesAbsent", "有害物质受控", "硫铅氯受控")),
        "specialMaterial": _bool(_value(values, "specialMaterial", "特殊材料")),
        "originalMaterial": _value(values, "originalMaterial", "原材料", "原设计材料"),
        "substituteMaterial": _value(values, "substituteMaterial", "replacementMaterial", "代用材料", "替代材料"),
        "substitutionScope": _value(values, "substitutionScope", "affectedScope", "代用范围", "影响范围"),
        "changeNo": _value(values, "changeNo", "changeDocumentNo", "设计变更单编号", "变更编号"),
        "originalDesignOrganization": _value(values, "originalDesignOrganization", "原设计单位"),
        "approvingOrganization": _value(values, "approvingOrganization", "approvalOrganization", "批准单位", "审批单位"),
        "writtenApprovalPresent": _bool(_value(values, "writtenApprovalPresent", "书面批准", "批准文件存在")),
        "approvalDate": _value(values, "approvalDate", "批准日期", "审批日期"),
        "implementationDate": _value(values, "implementationDate", "firstUseDate", "实施日期", "使用日期"),
        "implemented": _bool(_value(values, "implemented", "actuallyUsed", "已实施", "实际使用")),
        "scope": _value(values, "scope", "lineNo", "componentId", "使用范围", "管线号"),
        "actualMaterial": _value(values, "actualMaterial", "实用材料", "实际材料"),
        "valveNo": _value(values, "valveNo", "serialNo", "阀门编号", "产品编号"),
        "valveType": _value(values, "valveType", "model", "阀门类型", "型号"),
        "nominalDiameterMM": _value(values, "nominalDiameterMM", "dn", "公称直径", "DN"),
        "nominalPressure": _value(values, "nominalPressure", "nominalPressurePN", "pn", "公称压力", "PN"),
        "valveBodyMaterialCategory": _value(values, "valveBodyMaterialCategory", "bodyMaterialCategory", "bodyMaterial", "阀体材料类别", "阀体材料"),
        "maximumAllowableWorkingPressureMPa": _value(values, "maximumAllowableWorkingPressureMPa", "mawpMPa", "38℃最大允许工作压力", "最大允许工作压力"),
        "sealTestLevel": _value(values, "sealTestLevel", "sealTestType", "密封试验类型", "高低压密封"),
        "standardRef": _value(values, "standardRef", "basisStandard", "依据标准", "执行标准"),
        "constructionRecordId": _value(values, "constructionRecordId", "施工记录编号"),
        "pipelineGrade": _value(values, "pipelineGrade", "管道级别"),
        "lotId": _value(values, "lotId", "batchNo", "检验批编号", "批号"),
        "lotSize": _value(values, "lotSize", "populationCount", "quantity", "批数量", "阀门总数"),
        "testedCount": _value(values, "testedCount", "sampledCount", "试验数量", "抽检数量"),
        "nonconformingCount": _value(values, "nonconformingCount", "不合格数量"),
        "shellTest": _test_section(values, "shell"),
        "sealTest": _test_section(values, "seal"),
    }
    return record


def _test_section(values: dict[str, Any], name: str) -> dict[str, Any] | None:
    prefix = "壳体" if name == "shell" else "密封"
    section = {
        "medium": _value(values, f"{name}TestMedium", f"{name}Medium", f"{prefix}试验介质"),
        "pressureMPa": _value(values, f"{name}TestPressureMPa", f"{name}PressureMPa", f"{prefix}试验压力"),
        "holdSeconds": _value(values, f"{name}HoldSeconds", f"{prefix}保压时间秒"),
        "holdMinutes": _value(values, f"{name}HoldMinutes", f"{prefix}保压时间", f"{prefix}持续时间"),
        "result": _value(values, f"{name}TestResult", f"{name}Result", f"{prefix}试验结果"),
        "leakage": _value(values, f"{name}Leakage", f"{prefix}泄漏量"),
        "procedureSteps": _list_value(_value(values, f"{name}ProcedureSteps", f"{prefix}试验步骤", f"{prefix}试验方法")),
    }
    return {key: value for key, value in section.items() if value is not None} or None


def _document_kind(state: dict[str, Any], parse_result: dict[str, Any]) -> str | None:
    metadata = parse_result.get("metadata") if isinstance(parse_result.get("metadata"), dict) else {}
    version_id = str(parse_result.get("documentVersionId") or "")
    text = " ".join(
        str(item.get("fieldValue") or item.get("value") or item.get("text") or "")
        for item in [*(parse_result.get("fields") or []), *(parse_result.get("fragments") or [])]
        if isinstance(item, dict)
    )
    hints = _norm(
        " ".join(
            str(value or "")
            for value in (
                parse_result.get("profileId"),
                parse_result.get("documentType"),
                parse_result.get("materialTypeCode"),
                metadata.get("detectedProfileId"),
                metadata.get("materialTypeCode"),
                _file_name(state, version_id),
                text[:5000],
            )
        )
    )
    has_valve_pressure = any(_norm(marker) in hints for marker in ("valvepressuretest", "阀门耐压试验", "阀门压力试验"))
    has_valve_construction = any(_norm(marker) in hints for marker in ("valveconstruction", "阀门施工记录", "阀门安装记录"))
    if has_valve_pressure and has_valve_construction:
        return "valve_combined_construction_test_record"
    routes = (
        ("type_test_report", ("typetestreport", "型式试验报告", "型式试验证书")),
        ("technical_review_approval", ("technicalreview", "技术评审证书", "技术评审批准", "技术评审意见")),
        ("new_material_data", ("newmaterialdata", "新材料性能数据", "材料性能数据")),
        ("mark_transfer_record", ("marktransfer", "标志移植", "标记移植")),
        ("material_substitution_approval", ("materialsubstitution", "材料代用", "材料替代", "设计变更单")),
        ("valve_pressure_test_report", ("valvepressuretest", "阀门耐压试验", "阀门压力试验")),
        ("valve_sampling_record", ("valvesampling", "阀门抽检", "阀门检验批")),
        ("valve_construction_record", ("valveconstruction", "阀门施工记录", "阀门安装记录")),
        ("material_usage_record", ("materialusage", "材料领用记录", "材料使用记录")),
        ("supply_contract", ("supplycontract", "供货合同", "采购合同")),
        ("design_document", ("designdocument", "设计说明", "设计文件")),
        ("quality_certificate", ("qualitycertificate", "质量证明书", "材质证明")),
        ("construction_record", ("constructionrecord", "施工记录")),
    )
    for kind, markers in routes:
        if any(_norm(marker) in hints for marker in markers):
            return kind
    return None


def _all_rows(parse_result: dict[str, Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for table in parse_result.get("tables") or []:
        if not isinstance(table, dict):
            continue
        rows = table.get("normalizedRows") or table.get("records") or []
        output.extend(row for row in rows if isinstance(row, dict))
    return output


def _standard_refs(parse_result: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for item in [*(parse_result.get("fields") or []), *(parse_result.get("fragments") or [])]:
        if not isinstance(item, dict):
            continue
        text = str(item.get("fieldValue") or item.get("value") or item.get("text") or "")
        values.extend(match.group(0) for match in re.finditer(r"GB\s*/?\s*T\s*(?:13927\s*[-—]\s*2022|26480\s*[-—]\s*2011)", text, re.I))
    return values


def _overlay(facts: dict[str, Any], review_run: dict[str, Any], key: str) -> None:
    candidates = [review_run.get(f"{key}Facts")]
    supplied = review_run.get("businessFacts")
    if isinstance(supplied, dict):
        candidates.append(supplied.get(key))
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        for name, value in candidate.items():
            facts[name] = value


def _event_value(records: list[dict[str, Any]], key: str) -> bool | None:
    values = [_bool(record.get(key)) for record in records if _present(record.get(key))]
    if True in values:
        return True
    if values and all(value is False for value in values):
        return False
    return None


def _list_value(value: Any) -> list[Any]:
    if isinstance(value, str):
        return [item.strip() for item in re.split(r"[,，;；、\n]", value) if item.strip()]
    return list(value) if isinstance(value, (list, tuple, set)) else []


def _bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    compact = _norm(value)
    if compact in {"true", "yes", "是", "有", "已完成", "已批准", "已实施", "已使用", "合格", "通过"}:
        return True
    if compact in {"false", "no", "否", "无", "未完成", "未批准", "未实施", "未使用", "不合格"}:
        return False
    return None


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", str(value or "").lower())
