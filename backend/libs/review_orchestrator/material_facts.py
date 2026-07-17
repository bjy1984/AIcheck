from __future__ import annotations

import re
from typing import Any

from libs.review_orchestrator.r12_agent import extract_component_items, stable_payload_hash
from libs.review_orchestrator.r13_facts import (
    _common_document_fields,
    _file_name,
    _normalized_business_row,
    _present,
    _record_evidence,
    _unique_evidence_refs,
    _unique_records,
    _value,
)


def extract_material_design_items(
    state: dict[str, Any],
    review_run: dict[str, Any],
    *,
    namespace: str,
) -> list[dict[str, Any]]:
    return [
        _enrich_material_design_item(item)
        for item in extract_component_items(
            state,
            review_run,
            id_namespace=namespace,
            include_certificate_items=False,
            design_only=True,
        )
    ]


def iter_requested_parse_results(state: dict[str, Any], review_run: dict[str, Any]):
    requested = {str(item) for item in review_run.get("inputDocumentVersionIds") or [] if item}
    for parse_result in state.get("ocr_parse_results", []):
        if not isinstance(parse_result, dict):
            continue
        version_id = str(parse_result.get("documentVersionId") or "")
        if requested and version_id not in requested:
            continue
        yield parse_result


def material_document_kind(state: dict[str, Any], parse_result: dict[str, Any]) -> str | None:
    metadata = parse_result.get("metadata") if isinstance(parse_result.get("metadata"), dict) else {}
    version_id = str(parse_result.get("documentVersionId") or "")
    fields = [
        item
        for item in [*(parse_result.get("fields") or []), *(parse_result.get("fragments") or [])]
        if isinstance(item, dict)
    ]
    text = " ".join(str(item.get("fieldValue") or item.get("value") or item.get("text") or "") for item in fields)
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
    routes = (
        ("quality_certificate", ("qualitycertificate", "产品质量证明", "质量证明书", "材质证明", "质保书")),
        ("arrival_acceptance_record", ("arrivalacceptance", "到货验收", "进场验收", "材料验收记录", "元件验收记录")),
        ("sampling_witness_record", ("samplingwitness", "抽样见证", "取样见证", "抽样复验见证")),
        ("material_retest_report", ("materialretest", "材料复验报告", "材质复验报告", "复验报告")),
        ("material_ndt_report", ("materialndt", "材料无损检测报告", "母材无损检测", "原材料无损检测")),
    )
    for kind, markers in routes:
        if any(_norm(marker) in hints for marker in markers):
            return kind
    return None


def extract_quality_certificates(state: dict[str, Any], parse_result: dict[str, Any]) -> list[dict[str, Any]]:
    return _extract_records(state, parse_result, namespace="R16QC", record_kind="quality_certificate")


def extract_arrival_acceptance_records(state: dict[str, Any], parse_result: dict[str, Any]) -> list[dict[str, Any]]:
    return _extract_records(state, parse_result, namespace="R17AR", record_kind="arrival_acceptance")


def extract_sampling_witness_records(state: dict[str, Any], parse_result: dict[str, Any]) -> list[dict[str, Any]]:
    return _extract_records(state, parse_result, namespace="R17WR", record_kind="sampling_witness")


def extract_material_retest_reports(state: dict[str, Any], parse_result: dict[str, Any]) -> list[dict[str, Any]]:
    return _extract_records(state, parse_result, namespace="R18RR", record_kind="material_retest")


def extract_material_ndt_reports(state: dict[str, Any], parse_result: dict[str, Any]) -> list[dict[str, Any]]:
    return _extract_records(state, parse_result, namespace="R18NR", record_kind="material_ndt")


def build_material_judgment(records_by_type: list[tuple[str, list[dict[str, Any]], tuple[str, ...]]]) -> dict[str, Any]:
    all_records = [record for _, records, _ in records_by_type for record in records]
    evidence_refs = _unique_evidence_refs([record.get("evidence") for record in all_records])
    claimed_facts: list[dict[str, Any]] = []
    for fact_type, records, value_keys in records_by_type:
        for index, record in enumerate(records, 1):
            evidence = record.get("evidence") if isinstance(record.get("evidence"), dict) else {}
            evidence_id = evidence.get("evidenceRefId") or evidence.get("id")
            claimed_facts.append(
                {
                    "factId": f"{fact_type}-{index}",
                    "value": next((record.get(key) for key in value_keys if _present(record.get(key))), None),
                    "documentVersionId": record.get("documentVersionId"),
                    "evidenceRefIds": [evidence_id] if evidence_id else [],
                    "confidence": evidence.get("confidence") or record.get("ocrConfidence"),
                    "conflicted": bool(record.get("conflicted")),
                }
            )
    return {
        "judgment": {"claimedFacts": claimed_facts, "evidenceRefs": evidence_refs},
        "evidence": {
            "pageNo": [item.get("pageNo") for item in evidence_refs],
            "bboxOrQuotedText": [item.get("bbox") or item.get("quotedText") for item in evidence_refs],
            "ocrConfidence": [item.get("confidence") for item in evidence_refs],
            "conflictStatus": "no_conflict_detected" if claimed_facts and not any(item.get("conflicted") for item in claimed_facts) else "unknown",
        },
    }


def deduplicate(records: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    return _unique_records(records, key)


def _extract_records(
    state: dict[str, Any],
    parse_result: dict[str, Any],
    *,
    namespace: str,
    record_kind: str,
) -> list[dict[str, Any]]:
    common, evidence_items = _common_document_fields(state, parse_result)
    rows = _all_business_rows(parse_result)
    source_records = rows or [{}]
    output: list[dict[str, Any]] = []
    seals = _seal_facts(parse_result)
    signatures = _signature_facts(parse_result)
    table_test_items, table_test_results = _test_facts(parse_result)
    for index, row in enumerate(source_records, 1):
        merged = {**common, **_normalized_business_row(row)}
        trace_key = {
            "documentVersionId": common["documentVersionId"],
            "recordKind": record_kind,
            "certificateNo": _value(merged, "certificateNo", "certificate_no", "证书编号"),
            "reportNo": _value(merged, "reportNo", "report_no", "报告编号"),
            "batchNo": _value(merged, "batchNo", "batch_no", "lotNo", "批号", "批次号", "炉批号"),
            "rowIndex": index if rows else None,
        }
        record_id = f"{namespace}-" + stable_payload_hash(trace_key)[7:19].upper()
        evidence = _record_evidence(
            evidence_items,
            common["documentVersionId"],
            f"{namespace}EV-{record_id.rsplit('-', 1)[-1]}",
            trace_key["certificateNo"] or trace_key["reportNo"] or trace_key["batchNo"] or record_kind,
            row=row if rows else None,
            fallback_page=common.get("pageNo") or 1,
        )
        inspection_items = _list_value(
            _value(merged, "inspectionItems", "testItems", "检验项目", "试验项目", "检测项目")
        ) or table_test_items
        completed_steps = _list_value(_value(merged, "completedSteps", "acceptanceItems", "验收项目", "检查项目"))
        record = {
            "recordId": record_id,
            "certificateId": record_id if record_kind == "quality_certificate" else None,
            "reportId": record_id if "retest" in record_kind or "ndt" in record_kind else None,
            "recordKind": record_kind,
            "certificateNo": _value(merged, "certificateNo", "certificate_no", "qualityCertificateNo", "证书编号", "质保书编号"),
            "recordNo": _value(merged, "recordNo", "record_no", "验收记录编号", "见证记录编号"),
            "reportNo": _value(merged, "reportNo", "report_no", "报告编号", "复验报告编号", "检测报告编号"),
            "manufacturerName": _value(merged, "manufacturerName", "manufacturer", "制造单位", "生产单位"),
            "dealerName": _value(merged, "dealerName", "businessOperator", "经营单位", "供货单位", "经销单位"),
            "productName": _value(merged, "productName", "product_name", "componentType", "产品名称", "元件名称", "品名"),
            "componentType": _value(merged, "componentType", "productName", "元件类型", "产品名称"),
            "specification": _value(merged, "specification", "规格", "规格型号", "型号"),
            "materialGrade": _value(merged, "materialGrade", "material", "grade", "材质", "材料牌号", "牌号"),
            "standardRef": _value(merged, "standardRef", "standardNo", "acceptanceStandard", "执行标准", "标准号", "验收标准"),
            "deliveryCondition": _value(merged, "deliveryCondition", "supplyCondition", "交货状态", "供货状态"),
            "batchNo": _value(merged, "batchNo", "batch_no", "lotNo", "批号", "批次号", "炉批号"),
            "heatNo": _value(merged, "heatNo", "heat_no", "炉号"),
            "serialNo": _value(merged, "serialNo", "serial_no", "产品编号", "出厂编号"),
            "sampleNo": _value(merged, "sampleNo", "sample_no", "样品编号", "试样编号"),
            "quantity": _value(merged, "quantity", "数量", "到货数量", "验收数量"),
            "documentForm": _value(merged, "documentForm", "copyType", "originalOrCopy", "文件形式", "原件复印件", "正副本"),
            "conclusion": _value(merged, "conclusion", "inspectionConclusion", "acceptanceConclusion", "检验结论", "验收结论", "试验结论"),
            "issueDate": _value(merged, "issueDate", "issue_date", "签发日期", "出具日期", "报告日期"),
            "procedureApproved": _boolean_value(_value(merged, "procedureApproved", "approvalProcedureCompliant", "程序已批准", "程序符合")),
            "completedSteps": completed_steps,
            "inspectionItems": inspection_items,
            "testItems": inspection_items,
            "methods": _list_value(_value(merged, "methods", "ndtMethods", "检测方法", "无损检测方法")),
            "testResults": _test_results_from_row(merged) or table_test_results,
            "signatureRoles": _list_value(_value(merged, "signatureRoles", "签字角色", "签署角色")) or signatures,
            "witnessRoles": _list_value(_value(merged, "witnessRoles", "见证人员角色", "见证角色")) or signatures,
            "requiredSignatureRoles": _list_value(_value(merged, "requiredSignatureRoles", "要求签字角色")),
            "isolated": _boolean_value(_value(merged, "isolated", "quarantined", "已隔离", "已封存")),
            "disposition": _value(merged, "disposition", "nonconformanceDisposition", "不合格处置", "处置结论"),
            "releaseApproved": _boolean_value(_value(merged, "releaseApproved", "concessionReleaseApproved", "放行批准", "让步接收批准")),
            **seals,
            "manufacturerQualitySealPresent": bool(
                seals["manufacturerQualitySealPresent"]
                or _boolean_value(_value(merged, "manufacturerQualitySealPresent", "manufacturer_quality_seal", "制造单位质量检验章")) is True
            ),
            "dealerOfficialSealPresent": bool(
                seals["dealerOfficialSealPresent"]
                or _boolean_value(_value(merged, "dealerOfficialSealPresent", "dealer_official_seal", "经营单位公章")) is True
            ),
            "handlerResponsibleSealPresent": bool(
                seals["handlerResponsibleSealPresent"]
                or _boolean_value(_value(merged, "handlerResponsibleSealPresent", "handler_responsible_seal", "经办负责人章")) is True
            ),
            "documentVersionId": common["documentVersionId"],
            "documentId": common.get("documentId"),
            "fileName": common.get("fileName"),
            "pageNo": evidence.get("pageNo"),
            "ocrConfidence": evidence.get("confidence"),
            "evidence": evidence,
        }
        output.append({key: value for key, value in record.items() if value is not None})
    return output


def _enrich_material_design_item(item: dict[str, Any]) -> dict[str, Any]:
    row = item.get("sourceRow") if isinstance(item.get("sourceRow"), dict) else {}
    output = dict(item)
    aliases: dict[str, tuple[str, ...]] = {
        "productName": ("productName", "componentType", "产品名称", "元件名称", "品名"),
        "materialGrade": ("materialGrade", "material", "grade", "材料牌号", "材质", "牌号"),
        "standardRef": ("standardRef", "acceptanceStandard", "productStandard", "执行标准", "验收标准", "产品标准"),
        "deliveryCondition": ("deliveryCondition", "supplyCondition", "交货状态", "供货状态"),
        "batchNo": ("batchNo", "lotNo", "批号", "批次号", "炉批号"),
        "heatNo": ("heatNo", "炉号"),
        "serialNo": ("serialNo", "产品编号", "出厂编号"),
        "physicalMark": ("physicalMark", "实物标识", "材料标识"),
        "physicalMarkBatchNo": ("physicalMarkBatchNo", "实物批号", "标识批号"),
        "physicalHeatNo": ("physicalHeatNo", "实物炉号", "标识炉号"),
        "requiresSamplingRetest": ("requiresSamplingRetest", "samplingRetestRequired", "需要抽样复验", "抽样复验要求"),
        "requiresMaterialRetest": ("requiresMaterialRetest", "materialRetestRequired", "需要材料复验", "材料复验要求"),
        "requiresMaterialNdt": ("requiresMaterialNdt", "materialNdtRequired", "需要材料无损检测", "材料无损检测要求"),
        "requiresNumericAcceptance": ("requiresNumericAcceptance", "需要数值验收", "数值限值适用"),
        "requiredInspectionItems": ("requiredInspectionItems", "specialRequirements", "特殊检验要求", "设计特殊要求"),
        "requiredRetestItems": ("requiredRetestItems", "材料复验项目", "复验项目"),
        "requiredMaterialNdtMethods": ("requiredMaterialNdtMethods", "材料无损检测方法", "无损检测方法"),
        "materialTestTriggerReasons": ("materialTestTriggerReasons", "复验检测触发原因", "触发原因"),
        "requiredQuantitativeItems": ("requiredQuantitativeItems", "数值验收项目"),
        "acceptanceLimits": ("acceptanceLimits", "验收限值"),
        "newMaterialCategory": ("newMaterialCategory", "新材料类别", "材料适用类别"),
        "listedInGBT20801": ("listedInGBT20801", "列入GB/T20801", "GB/T20801已列入"),
        "listedInGBT32270": ("listedInGBT32270", "列入GB/T32270", "GB/T32270已列入"),
        "listedInDedicatedMaterialStandard": (
            "listedInDedicatedMaterialStandard",
            "列入专用材料标准",
            "其他专用材料标准已列入",
        ),
        "materialSubstitutionOccurred": ("materialSubstitutionOccurred", "发生材料代用", "材料代用"),
        "markTransferOccurred": ("markTransferOccurred", "发生标志移植", "标志移植"),
    }
    for target, keys in aliases.items():
        if _present(output.get(target)):
            continue
        value = _row_value(row, *keys)
        if target.startswith("requires") or target.startswith("listedIn") or target.endswith("Occurred"):
            value = _boolean_value(value)
        elif target in {"requiredInspectionItems", "requiredRetestItems", "requiredMaterialNdtMethods", "materialTestTriggerReasons", "requiredQuantitativeItems"}:
            value = _list_value(value)
        if _present(value):
            output[target] = value
    return output


def _all_business_rows(parse_result: dict[str, Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for table in parse_result.get("tables") or []:
        if not isinstance(table, dict):
            continue
        rows = table.get("normalizedRows") or table.get("records") or []
        for row in rows if isinstance(rows, list) else []:
            if isinstance(row, dict):
                output.append(row)
    return output


def _seal_facts(parse_result: dict[str, Any]) -> dict[str, Any]:
    seals = [item for item in parse_result.get("seals") or [] if isinstance(item, dict)]

    def seal_semantics(item: dict[str, Any]) -> tuple[str, str]:
        role = _norm(
            item.get("semanticRole")
            or item.get("sealRole")
            or item.get("ownerRole")
            or item.get("role")
        )
        text = _norm(
            item.get("sealText")
            or item.get("text")
            or item.get("type")
            or item.get("sealType")
        )
        return role, text

    semantics = [seal_semantics(item) for item in seals]

    def is_manufacturer_quality_seal(role: str, text: str) -> bool:
        return role in {"manufacturerqualityseal", "manufacturerinspectionseal", "制造单位质量检验章"} or any(
            marker in text for marker in ("质量检验", "质检", "检验专用", "qualityinspection")
        )

    def is_dealer_official_seal(role: str, text: str) -> bool:
        if role in {"dealerofficialseal", "businessoperatorofficialseal", "supplierofficialseal", "经营单位公章"}:
            return True
        dealer_marker = any(marker in text for marker in ("经营单位", "供货单位", "经销", "dealer", "supplier"))
        official_marker = any(marker in text for marker in ("公章", "officialseal"))
        return dealer_marker and official_marker

    def is_handler_responsible_seal(role: str, text: str) -> bool:
        return role in {"handlerresponsibleseal", "handlerseal", "经办负责人章"} or any(
            marker in text for marker in ("经办负责人", "经办人", "负责人", "handler")
        )

    return {
        "sealPresent": bool(seals),
        "manufacturerQualitySealPresent": any(is_manufacturer_quality_seal(role, text) for role, text in semantics),
        "dealerOfficialSealPresent": any(is_dealer_official_seal(role, text) for role, text in semantics),
        "handlerResponsibleSealPresent": any(is_handler_responsible_seal(role, text) for role, text in semantics),
        "recognizedSeals": seals,
    }


def _signature_facts(parse_result: dict[str, Any]) -> list[str]:
    signatures = [item for item in parse_result.get("signatures") or [] if isinstance(item, dict)]
    return list(dict.fromkeys(str(item.get("role") or item.get("signatureRole") or item.get("label") or "").strip() for item in signatures if str(item.get("role") or item.get("signatureRole") or item.get("label") or "").strip()))


def _test_facts(parse_result: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    items: list[str] = []
    results: dict[str, Any] = {}
    for table in parse_result.get("tables") or []:
        if not isinstance(table, dict):
            continue
        table_name = str(table.get("tableCode") or table.get("name") or "").strip()
        if table_name:
            items.append(table_name)
        rows = table.get("normalizedRows") or table.get("records") or []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            name = _value(row, "itemCode", "itemName", "testItem", "项目", "试验项目", "检测项目", "元素")
            value = _value(row, "value", "resultValue", "actual", "结果", "实测值", "含量")
            if _present(name):
                items.append(str(name))
                if _present(value):
                    results[str(name)] = value
    return list(dict.fromkeys(items)), results


def _test_results_from_row(row: dict[str, Any]) -> dict[str, Any]:
    value = _value(row, "testResults", "inspectionResults", "试验结果", "检测结果")
    return value if isinstance(value, dict) else {}


def _row_value(row: dict[str, Any], *keys: str) -> Any:
    if not isinstance(row, dict):
        return None
    return _value(_normalized_business_row(row), *keys)


def _list_value(value: Any) -> list[Any]:
    if isinstance(value, (list, tuple, set)):
        return list(value)
    if isinstance(value, str):
        return [item.strip() for item in re.split(r"[,，;；、\n]", value) if item.strip()]
    return []


def _boolean_value(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    normalized = _norm(value)
    if normalized in {"true", "yes", "是", "有", "需要", "适用", "已批准", "符合"}:
        return True
    if normalized in {"false", "no", "否", "无", "不需要", "不适用", "未批准", "不符合"}:
        return False
    return None


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", str(value or "").lower())
