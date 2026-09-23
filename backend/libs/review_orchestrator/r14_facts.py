from __future__ import annotations

import json
import re
from typing import Any

from libs.regulatory_tables import product_inspection_rules
from libs.review_input_data import current_selected_parse_results
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
    pipeline_characteristics: list[dict[str, Any]] = []
    factory_reports: list[dict[str, Any]] = []
    special_reports: list[dict[str, Any]] = []
    for parse_result in current_selected_parse_results(state, {}, context={"reviewRun": review_run}):
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
            "productInspectionRules": product_inspection_rules(),
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


# 单线图/轴测图图签：标签、值、标签、值横着排，下面接材料表（BOM）。
# 2026-09-11 生产实测（地上甲类储罐区2（含泵区）施工图.pdf，MINERU-TABLE-39BA985054E4A97E）：
#
#     设计压力 | 0.275 | 操作压力 | 0.413 | 管路起点 | LP7103 | 管路等级 | M1E | 压力管道级别 | GC2 | BOM A
#     设计温度 | 60°C  | 操作温度 | 常温  | 管路终点 | ST7102 | 介质名称 | …   | 损伤比例     | RT10%
#
# 表格解析把第一行当成表头，于是「设计压力」这个键底下装的是别的列，按行读出 28 条
# 假管线。这里按格子读：标签后面那一格就是它的值，整张表只描述**一条**管线。
_TITLE_BLOCK_LABELS: dict[str, str] = {
    "管线号": "lineNo", "管道编号": "lineNo", "管线编号": "lineNo",
    "管路起点": "lineStart", "起点": "lineStart",
    "管路终点": "lineEnd", "终点": "lineEnd",
    "压力管道级别": "pipelineGrade", "管道级别": "pipelineGrade", "管道等级": "pipelineGrade",
    "管路等级": "pipingClass",
    "设计压力": "designPressureMPa", "操作压力": "operatingPressureMPa",
    "设计温度": "designTemperatureC", "操作温度": "operatingTemperatureC",
    "介质名称": "medium", "介质": "medium", "输送介质": "medium",
    "损伤比例": "ndtRatio", "探伤比例": "ndtRatio", "检测比例": "ndtRatio",
    "材质": "material", "公称压力": "pressureClass",
}
_TITLE_BLOCK_MIN_LABELS = 3
_NUMBER_PREFIX = re.compile(r"^\s*(-?\d+(?:\.\d+)?)")


def _table_cell_rows(table: dict[str, Any]) -> list[list[str]]:
    """按行、按列排好的格子文本。优先 cells（已经解开 colspan），没有再拆 html。"""
    cells = [item for item in table.get("cells") or [] if isinstance(item, dict) and item.get("text") not in (None, "")]
    if cells:
        rows: dict[int, list[tuple[int, str]]] = {}
        for item in cells:
            rows.setdefault(int(item.get("row") or 0), []).append((int(item.get("col") or 0), str(item["text"]).strip()))
        return [[text for _, text in sorted(rows[index])] for index in sorted(rows)]
    html = str(table.get("html") or "")
    output: list[list[str]] = []
    for row_html in re.findall(r"<tr[^>]*>(.*?)</tr>", html, flags=re.DOTALL):
        texts = [re.sub(r"<[^>]+>", "", cell).strip() for cell in re.findall(r"<td[^>]*>(.*?)</td>", row_html, flags=re.DOTALL)]
        if any(texts):
            output.append(texts)
    return output


def _number_prefix(value: Any) -> str | None:
    """「60°C」「0.275MPa」只留数字；不是数字开头就原样交回去让下游判 None。"""
    match = _NUMBER_PREFIX.match(str(value or ""))
    return match.group(1) if match else None


def _extract_title_block_pipeline(state: dict[str, Any], parse_result: dict[str, Any], table: dict[str, Any]) -> dict[str, Any] | None:
    pairs: dict[str, str] = {}
    labels_seen: set[str] = set()
    for row in _table_cell_rows(table):
        # 一行里至少两个已知标签才算图签行。材料表的表头行（…DN | 数量 | 材质 | 说明）
        # 只有「材质」一个，不收——否则「说明」会被当成材质的值。
        row_pairs: list[tuple[str, str, str]] = []
        index = 0
        while index < len(row) - 1:
            label = row[index].strip()
            field = _TITLE_BLOCK_LABELS.get(label)
            value = row[index + 1].strip()
            if field and value and value not in _TITLE_BLOCK_LABELS:
                row_pairs.append((label, field, value))
                index += 2
                continue
            index += 1
        if len(row_pairs) < 2:
            continue
        for label, field, value in row_pairs:
            labels_seen.add(label)
            pairs.setdefault(field, value)
            pairs.setdefault(label, value)
    if len(labels_seen) < _TITLE_BLOCK_MIN_LABELS:
        return None
    line_no = pairs.get("lineNo")
    if not line_no and pairs.get("lineStart") and pairs.get("lineEnd"):
        # 图上就是用起止点标识这条线的，不是合成的身份。
        line_no = f"{pairs['lineStart']}→{pairs['lineEnd']}"
    if not line_no:
        return None
    version_id = str(parse_result.get("documentVersionId") or "")
    key = {"documentVersionId": version_id, "tableId": table.get("tableId") or table.get("id"), "titleBlock": True}
    record_id = "R14PIPE-" + stable_payload_hash(key)[7:19].upper()
    evidence_id = f"R14EV-{record_id.removeprefix('R14PIPE-')}"
    quoted = "；".join(f"{label}：{pairs[label]}" for label in sorted(labels_seen, key=list(_TITLE_BLOCK_LABELS).index))
    return {
        "pipelineCharacteristicId": record_id,
        "lineNo": line_no,
        "pipelineId": line_no,
        "pipelineGrade": pairs.get("pipelineGrade"),
        "pressureClass": pairs.get("pressureClass"),
        "designPressureMPa": _number_prefix(pairs.get("designPressureMPa")),
        "designTemperatureC": _number_prefix(pairs.get("designTemperatureC")),
        "minimumTestPressureMPa": None,
        "material": pairs.get("material"),
        "documentVersionId": version_id,
        "documentId": parse_result.get("documentId"),
        "fileName": _file_name(state, version_id),
        "pageNo": table.get("pageNo") or 1,
        "tableId": table.get("tableId") or table.get("id"),
        "rowIndex": 0,
        "sourceRow": dict(pairs),
        "sourceLayout": "title_block",
        "evidence": {
            "id": evidence_id,
            "evidenceRefId": evidence_id,
            "documentVersionId": version_id,
            "pageNo": table.get("pageNo") or 1,
            "bbox": table.get("bbox") or table.get("polygon"),
            "quotedText": quoted[:800],
            "confidence": _confidence(table),
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
        # 图签先于按行读：图签命中时整张表只描述一条管线，下面的 BOM 行不是管线。
        title_block = _extract_title_block_pipeline(state, parse_result, table)
        if title_block:
            output.append(title_block)
            continue
        rows = table.get("normalizedRows") or table.get("records") or []
        for row_index, row in enumerate(rows if isinstance(rows, list) else [], 1):
            if not isinstance(row, dict):
                continue
            line_no = _value(row, "lineNo", "pipelineNo", "pipeNo", "管线号", "管道编号")
            pressure_class = _value(row, "pressureClass", "pressureRating", "压力等级", "公称压力")
            design_pressure = _value(row, "designPressureMPa", "designPressure", "设计压力MPa", "设计压力")
            # 没有管线号的行不是管线特性行。原来只要 lineNo / 压力等级 / 设计压力
            # 任一有值就收，而 MinerU 对施工图这类表经常把表头认错一行——列名成了
            # 数据值，`设计压力` 这个键底下是别的列。2026-09-11 生产实测：
            # 地上甲类储罐区2（含泵区）施工图.pdf 因此产出 28 条「管线」，
            # 管线号、级别、材质全是 null，而 designPressureMPa 是
            # 2/4/6/8/10/12/14/16 的等差数列——那是尺寸或序号列，不是设计压力。
            # 这些假管线随后喂给逐管线判定，16MPa 会直接改变管道级别结论。
            # 没有管线号就无法归属，也就无法支撑逐管线判定，宁可不产出。
            if not _present(line_no):
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
                "testMethod": _value(merged, "testMethod", "ndtMethod", "检测方法", "试验方法"),
                "acceptanceLevel": _value(merged, "acceptanceLevel", "验收级别", "验收等级", "合格级别"),
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
