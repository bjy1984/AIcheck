from __future__ import annotations

import json
import re
from typing import Any

from libs.review_orchestrator.r12_agent import extract_component_items, stable_payload_hash
from libs.review_orchestrator.r13_facts import (
    _business_rows,
    _common_document_fields,
    _file_name,
    _normalized_business_row,
    _present,
    _record_evidence,
    _unique_evidence_refs,
    _unique_records,
    _value,
)

R14_NODE_ID = 14

_REPORT_TYPE_MARKERS = {
    "spectral_analysis": ("spectral", "spectrum", "pmi", "光谱", "材质鉴别"),
    "hardness_test": ("hardness", "硬度"),
    "metallographic_test": ("metallograph", "metallographic", "金相"),
    "nondestructive_testing": ("nondestructive", "ndt", "无损", "射线", "超声", "磁粉", "渗透"),
    "pressure_test": ("pressuretest", "hydrostatic", "hydraulic", "耐压", "液压", "水压", "气压"),
}


def build_r14_business_facts(state: dict[str, Any], review_run: dict[str, Any]) -> dict[str, Any]:
    design_items = extract_component_items(
        state,
        review_run,
        id_namespace="R14",
        include_certificate_items=False,
        design_only=True,
    )
    requested_versions = {str(item) for item in review_run.get("inputDocumentVersionIds") or [] if item}
    pipeline_characteristics: list[dict[str, Any]] = []
    factory_reports: list[dict[str, Any]] = []
    special_reports: list[dict[str, Any]] = []
    for parse_result in state.get("ocr_parse_results", []):
        if not isinstance(parse_result, dict):
            continue
        version_id = str(parse_result.get("documentVersionId") or "")
        if requested_versions and version_id not in requested_versions:
            continue
        pipeline_characteristics.extend(_extract_pipeline_characteristics(state, parse_result))
        document_kind, inspection_types = _r14_document_kind(state, parse_result)
        if document_kind == "factory_inspection_report":
            factory_reports.extend(_extract_r14_reports(state, parse_result, "factory_inspection_report", inspection_types))
        elif document_kind == "special_inspection_report":
            special_reports.extend(_extract_r14_reports(state, parse_result, "special_inspection_report", inspection_types))

    pipeline_characteristics = _unique_records(pipeline_characteristics, "pipelineCharacteristicId")
    factory_reports = _unique_records(factory_reports, "reportId")
    special_reports = _unique_records(special_reports, "reportId")
    evidence_refs = _unique_evidence_refs(
        [
            *[item.get("evidence") for item in design_items],
            *[item.get("evidence") for item in pipeline_characteristics],
            *[item.get("evidence") for item in factory_reports],
            *[item.get("evidence") for item in special_reports],
        ]
    )
    claimed_facts: list[dict[str, Any]] = []
    for fact_type, records, value_keys in (
        ("design_item", design_items, ("componentType", "specification")),
        ("pipeline_characteristic", pipeline_characteristics, ("lineNo", "pressureClass", "designPressureMPa")),
        ("factory_report", factory_reports, ("reportNo", "productName")),
        ("special_report", special_reports, ("reportNo", "reportType")),
    ):
        for index, item in enumerate(records, 1):
            evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
            evidence_id = evidence.get("evidenceRefId") or evidence.get("id")
            claimed_facts.append(
                {
                    "factId": f"r14-{fact_type}-{index}",
                    "value": next((item.get(key) for key in value_keys if _present(item.get(key))), None),
                    "documentVersionId": item.get("documentVersionId"),
                    "evidenceRefIds": [evidence_id] if evidence_id else [],
                    "confidence": evidence.get("confidence"),
                    "conflicted": bool(item.get("conflicted")),
                }
            )
    return {
        "r14": {
            "designItems": design_items,
            "pipelineCharacteristics": pipeline_characteristics,
            "factoryInspectionReports": factory_reports,
            "specialInspectionReports": special_reports,
        },
        "judgment": {"claimedFacts": claimed_facts, "evidenceRefs": evidence_refs},
        "evidence": {
            "pageNo": [item.get("pageNo") for item in evidence_refs],
            "bboxOrQuotedText": [item.get("bbox") or item.get("quotedText") for item in evidence_refs],
            "ocrConfidence": [item.get("confidence") for item in evidence_refs],
            "conflictStatus": (
                "no_conflict_detected"
                if claimed_facts and not any(item.get("conflicted") for item in claimed_facts)
                else "unknown"
            ),
        },
    }


def _extract_pipeline_characteristics(
    state: dict[str, Any],
    parse_result: dict[str, Any],
) -> list[dict[str, Any]]:
    version_id = str(parse_result.get("documentVersionId") or "")
    output: list[dict[str, Any]] = []
    for table in parse_result.get("tables") or []:
        if not isinstance(table, dict):
            continue
        hints = " ".join(
            [
                str(parse_result.get("profileId") or ""),
                str(parse_result.get("documentType") or ""),
                str(table.get("title") or table.get("tableName") or table.get("businessSchema") or ""),
                " ".join(str(item) for item in table.get("businessSchemas") or []),
                " ".join(str(key) for key in table),
            ]
        )
        compact = _compact(hints)
        if not any(marker in compact for marker in ("管道特性", "管线特性", "pipingcharacteristic", "pipelinecharacteristic")):
            continue
        rows = table.get("normalizedRows") or table.get("records") or []
        for row_index, row in enumerate(rows if isinstance(rows, list) else [], 1):
            if not isinstance(row, dict):
                continue
            line_no = _value(row, "lineNo", "pipelineNo", "pipeNo", "管线号", "管道编号")
            pressure_class = _value(row, "pressureClass", "pressureRating", "压力等级", "公称压力")
            design_pressure = _value(row, "designPressureMPa", "designPressure", "设计压力MPa", "设计压力")
            if not any(_present(value) for value in (line_no, pressure_class, design_pressure)):
                continue
            key = {"documentVersionId": version_id, "tableId": table.get("tableId") or table.get("id"), "rowIndex": row_index}
            record_id = "R14PIPE-" + stable_payload_hash(key)[7:19].upper()
            evidence_id = f"R14EV-{record_id.removeprefix('R14PIPE-')}"
            output.append(
                {
                    "pipelineCharacteristicId": record_id,
                    "lineNo": line_no,
                    "pipelineId": line_no,
                    "pipelineGrade": _value(row, "pipelineGrade", "grade", "管道级别", "管道等级"),
                    "pressureClass": pressure_class,
                    "designPressureMPa": design_pressure,
                    "designTemperatureC": _value(row, "designTemperatureC", "designTemperature", "设计温度"),
                    "minimumTestPressureMPa": _value(
                        row,
                        "minimumTestPressureMPa",
                        "requiredTestPressureMPa",
                        "最低试验压力MPa",
                        "试验压力MPa",
                    ),
                    "material": _value(row, "material", "materialGrade", "材质", "材料牌号"),
                    "documentVersionId": version_id,
                    "documentId": parse_result.get("documentId"),
                    "fileName": _file_name(state, version_id),
                    "pageNo": table.get("pageNo") or 1,
                    "tableId": table.get("tableId") or table.get("id"),
                    "rowIndex": row_index,
                    "sourceRow": row,
                    "evidence": {
                        "id": evidence_id,
                        "evidenceRefId": evidence_id,
                        "documentVersionId": version_id,
                        "pageNo": table.get("pageNo") or 1,
                        "bbox": row.get("bbox") or row.get("polygon") or table.get("bbox") or table.get("polygon"),
                        "quotedText": json.dumps(row, ensure_ascii=False, default=str)[:800],
                        "confidence": _confidence(row) or _confidence(table),
                    },
                }
            )
    return output


def _extract_r14_reports(
    state: dict[str, Any],
    parse_result: dict[str, Any],
    report_kind: str,
    detected_types: set[str],
) -> list[dict[str, Any]]:
    common, evidence_items = _common_document_fields(state, parse_result)
    rows = _business_rows(parse_result)
    records = rows or [{}]
    output: list[dict[str, Any]] = []
    for index, row in enumerate(records, 1):
        merged = {**common, **_normalized_business_row(row)}
        report_no = _value(merged, "reportNo", "report_no", "certificateNo", "报告编号", "证书编号")
        product_name = _value(merged, "productName", "product_name", "componentType", "产品名称", "元件名称")
        explicit_types = _inspection_types(
            [
                _value(merged, "reportType", "report_type", "inspectionType", "报告类型", "检验类型"),
                _value(merged, "testItems", "test_items", "inspectionItems", "检验项目", "试验项目"),
            ]
        )
        inspection_types = sorted({*detected_types, *explicit_types})
        key = {
            "documentVersionId": common["documentVersionId"],
            "reportNo": report_no,
            "productName": product_name,
            "rowIndex": index if rows else None,
            "reportKind": report_kind,
        }
        report_id = "R14REP-" + stable_payload_hash(key)[7:19].upper()
        evidence = _record_evidence(
            evidence_items,
            common["documentVersionId"],
            f"R14EV-{report_id.removeprefix('R14REP-')}",
            report_no or product_name or report_kind,
            row=row if rows else None,
            fallback_page=common.get("pageNo") or 1,
        )
        output.append(
            {
                "reportId": report_id,
                "reportKind": report_kind,
                "reportType": inspection_types[0] if len(inspection_types) == 1 else None,
                "inspectionTypes": inspection_types,
                "reportNo": report_no,
                "productName": product_name,
                "componentType": product_name,
                "manufacturerName": _value(merged, "manufacturerName", "manufacturer", "制造单位", "生产单位"),
                "lineNo": _value(merged, "lineNo", "line_no", "pipelineNo", "管线号", "管道编号"),
                "specification": _value(merged, "specification", "规格", "规格型号"),
                "grade": _value(merged, "grade", "componentGrade", "component_grade", "strengthGrade", "等级", "性能等级", "强度等级"),
                "material": _value(merged, "material", "materialGrade", "material_grade", "材料", "材质", "材料牌号"),
                "batchNo": _value(merged, "batchNo", "batch_no", "lotNo", "heatNo", "批号", "炉号", "炉批号"),
                "pressureClass": _value(merged, "pressureClass", "pressure_class", "pressureRating", "压力等级", "公称压力"),
                "nominalPressureMPa": _value(merged, "nominalPressureMPa", "nominal_pressure_mpa", "公称压力MPa"),
                "testPressureMPa": _value(merged, "testPressureMPa", "test_pressure_mpa", "actualTestPressureMPa", "试验压力MPa", "试验压力"),
                "testItems": _value(merged, "testItems", "test_items", "inspectionItems", "检验项目", "试验项目"),
                "testResults": _value(merged, "testResults", "test_results", "inspectionResults", "检验结果", "试验结果"),
                "conclusion": _value(merged, "conclusion", "inspectionConclusion", "testConclusion", "检验结论", "试验结论", "结论"),
                "standardRef": _value(merged, "standardRef", "standardNo", "standard_no", "依据标准", "执行标准", "产品标准"),
                "documentVersionId": common["documentVersionId"],
                "documentId": common.get("documentId"),
                "fileName": common.get("fileName"),
                "pageNo": evidence.get("pageNo"),
                "evidence": evidence,
            }
        )
    return output


def _r14_document_kind(
    state: dict[str, Any],
    parse_result: dict[str, Any],
) -> tuple[str | None, set[str]]:
    metadata = parse_result.get("metadata") if isinstance(parse_result.get("metadata"), dict) else {}
    version_id = str(parse_result.get("documentVersionId") or "")
    item_text = " ".join(
        str(item.get("text") or item.get("fieldValue") or item.get("value") or "")
        for item in [*(parse_result.get("fields") or []), *(parse_result.get("fragments") or [])]
        if isinstance(item, dict)
    )
    hints = " ".join(
        str(value or "")
        for value in (
            parse_result.get("profileId"),
            parse_result.get("documentType"),
            metadata.get("detectedProfileId"),
            _file_name(state, version_id),
            item_text[:5000],
        )
    )
    compact = _compact(hints)
    inspection_types = _inspection_types([hints])
    explicit_kind = _compact(
        " ".join(
            str(value or "")
            for value in (
                parse_result.get("profileId"),
                parse_result.get("documentType"),
                metadata.get("detectedProfileId"),
                _file_name(state, version_id),
            )
        )
    )
    if any(marker in explicit_kind for marker in ("factoryinspectionreport", "出厂检验报告", "出厂质量检验报告")):
        return "factory_inspection_report", inspection_types
    if inspection_types or any(marker in compact for marker in ("materialretest", "材料复验", "现场复验")):
        return "special_inspection_report", inspection_types
    if any(marker in compact for marker in ("factoryinspectionreport", "出厂检验报告", "出厂质量证明", "出厂检验")):
        return "factory_inspection_report", inspection_types
    return None, set()


def _inspection_types(values: list[Any]) -> set[str]:
    output: set[str] = set()
    for value in values:
        compact = _compact(value)
        for inspection_type, aliases in _REPORT_TYPE_MARKERS.items():
            if any(_compact(alias) in compact for alias in aliases):
                output.add(inspection_type)
    return output


def _confidence(item: dict[str, Any]) -> float:
    try:
        return round(float(item.get("confidence") or item.get("ocrConfidence") or 0), 4)
    except (TypeError, ValueError):
        return 0.0


def _compact(value: Any) -> str:
    return re.sub(r"[\s\W_]+", "", str(value or "").lower(), flags=re.UNICODE)
