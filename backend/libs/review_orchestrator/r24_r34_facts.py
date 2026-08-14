from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from libs.review_orchestrator.material_facts import (
    build_material_judgment,
    deduplicate,
    iter_requested_parse_results,
)
from libs.review_orchestrator.r12_agent import stable_payload_hash
from libs.review_orchestrator.r13_facts import (
    _common_document_fields,
    _file_name,
    _normalized_business_row,
    _record_evidence,
    _value,
)

NODE_CONFIG: dict[str, dict[str, tuple[str, ...]]] = {
    "r24": {"certificates": ("welder_certificate",), "workItems": ("welding_record",)},
    "r25": {"wpsItems": ("wps", "wps_pqr"), "pqrItems": ("pqr", "wps_pqr"), "workItems": ("welding_record", "pipeline_summary")},
    "r26": {"qualityCertificates": ("welding_consumable_certificate",), "designRequirements": ("design_document", "pipeline_summary"), "physicalItems": ("consumable_receipt", "consumable_management")},
    "r27": {"managementRecords": ("consumable_management",)},
    "r28": {"fitUpRecords": ("pipe_fit_up_record",)},
    "r29": {"weldingRecords": ("welding_record",), "certificates": ("welder_certificate",), "wpsItems": ("wps", "wps_pqr"), "pqrItems": ("pqr", "wps_pqr"), "workItems": ("welding_record",)},
    "r30": {"appearanceRecords": ("weld_appearance_record",)},
    "r31": {"repairRecords": ("weld_repair_record",)},
    "r32": {"procedureCards": ("heat_treatment_procedure",), "qualificationReports": ("pqr", "wps_pqr"), "weldItems": ("welding_record", "pipeline_summary")},
    "r33": {"instrumentRecords": ("heat_treatment_instrument",), "temperaturePointLayouts": ("temperature_point_layout",), "weldItems": ("welding_record", "pipeline_summary")},
    "r34": {"heatTreatmentReports": ("heat_treatment_record",), "hardnessReports": ("hardness_report",), "weldItems": ("welding_record", "pipeline_summary")},
}


def build_r24_business_facts(state: dict[str, Any], review_run: dict[str, Any]) -> dict[str, Any]:
    return _build("r24", state, review_run)


def build_r25_business_facts(state: dict[str, Any], review_run: dict[str, Any]) -> dict[str, Any]:
    return _build("r25", state, review_run)


def build_r26_business_facts(state: dict[str, Any], review_run: dict[str, Any]) -> dict[str, Any]:
    return _build("r26", state, review_run)


def build_r27_business_facts(state: dict[str, Any], review_run: dict[str, Any]) -> dict[str, Any]:
    return _build("r27", state, review_run)


def build_r28_business_facts(state: dict[str, Any], review_run: dict[str, Any]) -> dict[str, Any]:
    return _build("r28", state, review_run)


def build_r29_business_facts(state: dict[str, Any], review_run: dict[str, Any]) -> dict[str, Any]:
    return _build("r29", state, review_run)


def build_r30_business_facts(state: dict[str, Any], review_run: dict[str, Any]) -> dict[str, Any]:
    return _build("r30", state, review_run)


def build_r31_business_facts(state: dict[str, Any], review_run: dict[str, Any]) -> dict[str, Any]:
    return _build("r31", state, review_run)


def build_r32_business_facts(state: dict[str, Any], review_run: dict[str, Any]) -> dict[str, Any]:
    return _build("r32", state, review_run)


def build_r33_business_facts(state: dict[str, Any], review_run: dict[str, Any]) -> dict[str, Any]:
    return _build("r33", state, review_run)


def build_r34_business_facts(state: dict[str, Any], review_run: dict[str, Any]) -> dict[str, Any]:
    return _build("r34", state, review_run)


BUILDERS: dict[str, Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]] = {
    f"r{number}": globals()[f"build_r{number}_business_facts"] for number in range(24, 35)
}


def _build(node: str, state: dict[str, Any], review_run: dict[str, Any]) -> dict[str, Any]:
    config = NODE_CONFIG[node]
    facts: dict[str, Any] = {key: [] for key in config}
    evidence_groups: list[tuple[str, list[dict[str, Any]], tuple[str, ...]]] = []
    for parse_result in iter_requested_parse_results(state, review_run):
        kind = _document_kind(state, parse_result)
        for target, accepted_kinds in config.items():
            if kind not in accepted_kinds:
                continue
            records = _extract_records(state, parse_result, node.upper(), kind)
            facts[target].extend(records)
    for target in facts:
        facts[target] = deduplicate(facts[target], "recordId")
        evidence_groups.append((f"{node}-{target}", facts[target], ("documentNo", "recordNo", "weldNo", "materialGrade")))
    _overlay(facts, review_run, node)
    if node == "r34":
        facts["hardnessReports"] = _group_hardness_reports(facts["hardnessReports"])
    if node == "r24":
        facts["qualificationCodes"] = list(dict.fromkeys(str(code) for cert in facts["certificates"] for code in cert.get("qualificationCodes") or []))
        facts["workDate"] = review_run.get("workDate") or review_run.get("reviewDate")
        facts["reviewDate"] = review_run.get("reviewDate")
    elif node == "r25":
        facts["processType"] = review_run.get("processType") or "welding"
    elif node == "r26":
        facts["productStandardProfiles"] = review_run.get("productStandardProfiles") or {}
        facts["reviewDate"] = review_run.get("reviewDate")
    elif node == "r27":
        facts["controlRequirements"] = review_run.get("weldingConsumableControlRequirements") or {}
    elif node == "r29":
        facts["qualificationCodes"] = list(dict.fromkeys(str(code) for cert in facts["certificates"] for code in cert.get("qualificationCodes") or []))
        facts["workDate"] = review_run.get("workDate") or review_run.get("reviewDate")
    elif node == "r30":
        facts["photoRequired"] = review_run.get("weldAppearancePhotoRequired")
    elif node == "r31":
        facts["repairOccurred"] = review_run.get("repairOccurred") if "repairOccurred" in review_run else bool(facts["repairRecords"]) or None
    elif node in {"r32", "r34"}:
        facts["profile"] = "heat_treatment_result" if node == "r34" else "heat_treatment_procedure"
    elif node == "r33":
        facts["reviewDate"] = review_run.get("reviewDate")
    judgment = build_material_judgment(evidence_groups)
    return {node: facts, **judgment}


def _extract_records(state: dict[str, Any], parse_result: dict[str, Any], namespace: str, kind: str) -> list[dict[str, Any]]:
    common, evidence_items = _common_document_fields(state, parse_result)
    document_values = _field_values(parse_result)
    rows = _all_rows(parse_result) or [{}]
    output: list[dict[str, Any]] = []
    for index, row in enumerate(rows, 1):
        values = {**document_values, **_normalized_business_row(row)}
        record_id = f"{namespace}-" + stable_payload_hash({"documentVersionId": common["documentVersionId"], "kind": kind, "row": index})[7:19].upper()
        evidence = _record_evidence(evidence_items, common["documentVersionId"], f"{namespace}EV-{record_id[-12:]}", _value(values, "documentNo", "recordNo", "weldNo", "证书编号", "记录编号") or kind, row=row if row else None, fallback_page=common.get("pageNo") or 1)
        record = _mapped(values, kind)
        record.update({"recordId": record_id, "recordKind": kind, "documentVersionId": common["documentVersionId"], "documentId": common.get("documentId"), "fileName": common.get("fileName"), "pageNo": evidence.get("pageNo"), "ocrConfidence": evidence.get("confidence"), "evidence": evidence})
        output.append({key: value for key, value in record.items() if value is not None})
    return output


def _mapped(v: dict[str, Any], kind: str) -> dict[str, Any]:
    record: dict[str, Any] = {
        "documentNo": _v(v, "documentNo", "certificateNo", "reportNo", "文件编号", "证书编号", "报告编号"),
        "reportNo": _v(v, "reportNo", "报告编号"),
        "recordNo": _v(v, "recordNo", "记录编号"),
        "lineNo": _v(v, "lineNo", "pipelineNo", "管线号", "管道编号"),
        "weldNo": _v(v, "weldNo", "jointNo", "焊缝编号", "焊口号"),
        "welderName": _v(v, "welderName", "name", "焊工姓名"),
        "welderCertificateNo": _v(v, "welderCertificateNo", "welderCertificateNo", "certificateNo", "焊工证号", "证书编号"),
        "qualificationCodes": _list(_v(v, "qualificationCodes", "qualifiedItems", "welderOperationItemCode", "合格项目", "项目代号")),
        "validFrom": _v(v, "validFrom", "有效期起"),
        "validUntil": _v(v, "validUntil", "expiryDate", "有效期止", "有效期"),
        "personIdentityMatched": _bool(_v(v, "personIdentityMatched", "人证相符")),
        "originalSeen": _bool(_v(v, "originalSeen", "原件核验")),
        "verifiedCopy": _bool(_v(v, "verifiedCopy", "复印件核验")),
        "weldingMethod": _v(v, "weldingMethod", "method", "焊接方法"),
        "materialCategory": _v(v, "materialCategory", "母材类别"),
        "materialGrade": _v(v, "materialGrade", "material", "母材牌号", "材料牌号", "材质"),
        "position": _v(v, "position", "weldingPosition", "焊接位置"),
        "thickness": _v(v, "thickness", "wallThickness", "壁厚"),
        "diameter": _v(v, "diameter", "outerDiameter", "管径", "外径"),
        "fillerMetal": _v(v, "fillerMetal", "填充金属"),
        "processFactors": _list(_v(v, "processFactors", "焊接工艺因素")),
        "wpsNo": _v(v, "wpsNo", "procedureNo", "WPS编号", "作业指导书编号"),
        "pqrNo": _v(v, "pqrNo", "reportNo", "PQR编号", "焊接工艺评定编号"),
        "approved": _bool(_v(v, "approved", "approvalCompleted", "审批生效", "已批准")),
        "qualificationReportNo": _v(v, "qualificationReportNo", "pqrNo", "评定报告编号"),
        "current": _v(v, "current", "weldingCurrent", "电流"),
        "voltage": _v(v, "voltage", "arcVoltage", "电压"),
        "weldingSpeed": _v(v, "weldingSpeed", "travelSpeed", "焊接速度"),
        "interpassTemperature": _v(v, "interpassTemperature", "层间温度"),
        "currentRange": _v(v, "currentRange", "电流范围"), "voltageRange": _v(v, "voltageRange", "电压范围"),
        "weldingSpeedRange": _v(v, "weldingSpeedRange", "焊接速度范围"), "interpassTemperatureRange": _v(v, "interpassTemperatureRange", "层间温度范围"),
        "thicknessRange": _v(v, "thicknessRange", "适用厚度范围", "厚度范围"),
        "currentMin": _v(v, "currentMin", "电流下限"), "currentMax": _v(v, "currentMax", "电流上限"),
        "voltageMin": _v(v, "voltageMin", "电压下限"), "voltageMax": _v(v, "voltageMax", "电压上限"),
        "weldingSpeedMin": _v(v, "weldingSpeedMin", "焊速下限"), "weldingSpeedMax": _v(v, "weldingSpeedMax", "焊速上限"),
        "interpassTemperatureMin": _v(v, "interpassTemperatureMin", "层间温度下限"), "interpassTemperatureMax": _v(v, "interpassTemperatureMax", "层间温度上限"),
        "thicknessMin": _v(v, "thicknessMin", "评定厚度下限"), "thicknessMax": _v(v, "thicknessMax", "评定厚度上限"),
        "brand": _v(v, "brand", "牌号"), "specification": _v(v, "specification", "规格"), "batchNo": _v(v, "batchNo", "lotNo", "批号", "炉批号"),
        "standardRef": _v(v, "standardRef", "productStandard", "执行标准", "依据标准"),
        "chemicalComposition": _dict(_v(v, "chemicalComposition", "化学成分")),
        "mechanicalProperties": _dict(_v(v, "mechanicalProperties", "力学性能")),
        "stockValidUntil": _v(v, "stockValidUntil", "inventoryValidUntil", "库存期限"),
        "retestQualified": _bool(_v(v, "retestQualified", "超期复验合格")),
        "temperature": _v(v, "temperature", "库房温度"), "humidity": _v(v, "humidity", "库房湿度"),
        "dryingTemperature": _v(v, "dryingTemperature", "烘干温度"), "dryingMinutes": _v(v, "dryingMinutes", "烘干时间"),
        "expired": _bool(_v(v, "expired", "过期")), "mixedUse": _bool(_v(v, "mixedUse", "混用")), "conclusion": _v(v, "conclusion", "结论"),
        "misalignment": _v(v, "misalignment", "internalMisalignment", "错边量"), "gap": _v(v, "gap", "rootGap", "组对间隙"), "gapMin": _v(v, "gapMin", "间隙下限"), "gapMax": _v(v, "gapMax", "间隙上限"),
        "bevelAngle": _v(v, "bevelAngle", "坡口角度"), "bevelAngleMin": _v(v, "bevelAngleMin", "坡口角度下限"), "bevelAngleMax": _v(v, "bevelAngleMax", "坡口角度上限"),
        "forcedFitUp": _bool(_v(v, "forcedFitUp", "强行组对", "强力组对")), "designPrestretch": _bool(_v(v, "designPrestretch", "设计预拉伸")),
        "weldMapRef": _v(v, "weldMapRef", "焊缝编号图"), "weldMark": _v(v, "weldMark", "焊缝标识", "钢印标识"), "traceable": _bool(_v(v, "traceable", "可追溯")),
        "inspectionGrade": _v(v, "inspectionGrade", "检验等级"), "jointType": _v(v, "jointType", "接头类型"),
        "crack": _bool(_v(v, "crack", "裂纹")), "lackOfFusion": _bool(_v(v, "lackOfFusion", "未熔合")), "surfacePore": _bool(_v(v, "surfacePore", "表面气孔")), "exposedSlag": _bool(_v(v, "exposedSlag", "外露夹渣")),
        "undercutDepth": _v(v, "undercutDepth", "咬边深度"), "reinforcement": _v(v, "reinforcement", "焊缝余高"), "width": _v(v, "width", "焊缝宽度"), "widthMin": _v(v, "widthMin", "宽度下限"), "widthMax": _v(v, "widthMax", "宽度上限"), "photoRef": _v(v, "photoRef", "照片引用"),
        "repairApplicationNo": _v(v, "repairApplicationNo", "返修申请单号"), "repairProcedureNo": _v(v, "repairProcedureNo", "返修工艺编号"), "repairProcedureApproved": _bool(_v(v, "repairProcedureApproved", "返修工艺批准")), "causeAnalysis": _v(v, "causeAnalysis", "原因分析"), "sameLocationRepairCount": _v(v, "sameLocationRepairCount", "同一部位返修次数"),
        "revisedSpecialMeasures": _bool(_v(v, "revisedSpecialMeasures", "专项返修措施")), "technicalHeadApproved": _bool(_v(v, "technicalHeadApproved", "技术负责人批准")), "postRepairNdtReportNo": _v(v, "postRepairNdtReportNo", "返修后检测报告编号"), "postRepairNdtResult": _v(v, "postRepairNdtResult", "返修后检测结论"),
        "originalInspectionMethod": _v(v, "originalInspectionMethod", "原检测方法"), "postRepairNdtMethod": _v(v, "postRepairNdtMethod", "返修后检测方法"),
        "performedAfterPwht": _bool(_v(v, "performedAfterPwht", "热处理后返修")), "repeatPwhtCompleted": _bool(_v(v, "repeatPwhtCompleted", "重新热处理完成")),
        "materialGroup": _v(v, "materialGroup", "材料组别"), "governingThickness": _v(v, "governingThickness", "控制厚度"), "specifiedMinimumTensileStrength": _v(v, "specifiedMinimumTensileStrength", "规定最小抗拉强度"), "chromiumPercent": _v(v, "chromiumPercent", "铬含量"), "carbonPercent": _v(v, "carbonPercent", "碳含量"),
        "designPwhtRequired": _bool(_v(v, "designPwhtRequired", "设计要求热处理")), "holdingTemperature": _v(v, "holdingTemperature", "保温温度"), "holdingMinutes": _v(v, "holdingMinutes", "保温时间"), "heatingRate": _v(v, "heatingRate", "升温速率"), "coolingRate": _v(v, "coolingRate", "降温速率"),
        "instrumentType": _v(v, "instrumentType", "仪表类型"), "calibrationCertificateNo": _v(v, "calibrationCertificateNo", "校准证书编号", "校验证书编号"), "calibrationValidUntil": _v(v, "calibrationValidUntil", "校准有效期"),
        "curveContinuous": _bool(_v(v, "curveContinuous", "曲线完整无中断")), "curveRef": _v(v, "curveRef", "温度时间曲线"),
        "hardnessMethod": _v(v, "hardnessMethod", "硬度方法"), "readings": _list_of_dicts(_v(v, "readings", "hardnessReadings", "硬度测点", "硬度读数")), "hardnessZone": _v(v, "hardnessZone", "zone", "测点区域"), "hardnessValue": _v(v, "hardnessValue", "hardness", "value", "硬度值"), "convertedHBW": _v(v, "convertedHBW", "换算HBW"), "testedJointCount": _v(v, "testedJointCount", "检测接头数"), "lotJointCount": _v(v, "lotJointCount", "批内接头数"), "localHeatTreatment": _bool(_v(v, "localHeatTreatment", "局部热处理")),
        "baseMaterialHardnessHBW": _v(v, "baseMaterialHardnessHBW", "母材硬度"), "designHardnessMaxHBW": _v(v, "designHardnessMaxHBW", "设计硬度上限"),
    }
    return record


def _document_kind(state: dict[str, Any], parse_result: dict[str, Any]) -> str | None:
    metadata = parse_result.get("metadata") if isinstance(parse_result.get("metadata"), dict) else {}
    text = " ".join(str(item.get("fieldValue") or item.get("value") or item.get("text") or "") for item in [*(parse_result.get("fields") or []), *(parse_result.get("fragments") or [])] if isinstance(item, dict))
    hints = _norm(" ".join(str(value or "") for value in (parse_result.get("profileId"), parse_result.get("documentType"), parse_result.get("materialTypeCode"), metadata.get("detectedProfileId"), metadata.get("materialTypeCode"), _file_name(state, str(parse_result.get("documentVersionId") or "")), text[:4000])))
    routes = (
        ("welder_certificate", ("weldercertificate", "焊工资格证", "焊工证")), ("pipeline_summary", ("pipelinesummary", "管线汇总表")),
        ("wps_pqr", ("weldingprocedurequalification", "焊接工艺评定报告和焊接作业指导书", "pqrwps")),
        ("wps", ("wps", "焊接作业指导书")), ("pqr", ("pqr", "焊接工艺评定报告")), ("welding_consumable_certificate", ("weldingconsumablecertificate", "焊接材料质量证明", "焊材质量证明")),
        ("consumable_receipt", ("consumablereceipt", "焊材验收")), ("consumable_management", ("consumablemanagement", "焊材库", "焊条烘干", "焊材领用", "焊材回收")),
        ("pipe_fit_up_record", ("pipefitup", "管道组对", "组对检查")), ("weld_appearance_record", ("weldappearance", "焊缝外观", "外观检查记录")),
        ("weld_repair_record", ("weldrepair", "焊缝返修", "返修申请")), ("heat_treatment_procedure", ("heattreatmentprocedure", "热处理工艺卡", "热处理工艺文件")),
        ("temperature_point_layout", ("temperaturepointlayout", "测温点布置图")), ("heat_treatment_instrument", ("heattreatmentinstrument", "热电偶校准", "温控仪校验", "测温记录仪")),
        ("hardness_report", ("hardnessreport", "硬度检测报告", "硬度测试报告")), ("heat_treatment_record", ("heattreatmentrecord", "热处理报告", "温度时间曲线")),
        ("welding_record", ("weldingrecord", "焊接施工记录", "施焊记录")), ("design_document", ("designdocument", "设计说明", "设计文件")),
    )
    for kind, markers in routes:
        if any(_norm(marker) in hints for marker in markers):
            return kind
    return None


def _field_values(parse_result: dict[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for item in parse_result.get("fields") or []:
        if not isinstance(item, dict):
            continue
        key = item.get("fieldCode") or item.get("key") or item.get("fieldName") or item.get("label")
        value = item.get("fieldValue") if "fieldValue" in item else item.get("value")
        if key and value is not None and value != "":
            values[str(key)] = value
    return _normalized_business_row(values)


def _all_rows(parse_result: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for table in parse_result.get("tables") or []:
        if isinstance(table, dict):
            rows.extend(row for row in table.get("normalizedRows") or table.get("records") or [] if isinstance(row, dict))
    return rows


def _overlay(facts: dict[str, Any], review_run: dict[str, Any], node: str) -> None:
    candidates = [review_run.get(f"{node}Facts")]
    supplied = review_run.get("businessFacts")
    if isinstance(supplied, dict):
        candidates.append(supplied.get(node))
    for candidate in candidates:
        if isinstance(candidate, dict):
            facts.update(candidate)


def _group_hardness_reports(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for record in records:
        key = str(record.get("reportNo") or record.get("documentNo") or record.get("weldNo") or record.get("recordId"))
        target = grouped.setdefault(key, dict(record))
        readings = target.setdefault("readings", list(record.get("readings") or []))
        if record.get("hardnessValue") is not None:
            readings.append({
                "zone": record.get("hardnessZone"),
                "value": record.get("hardnessValue"),
                "convertedHBW": record.get("convertedHBW"),
            })
        for field in ("testedJointCount", "lotJointCount", "localHeatTreatment", "hardnessMethod", "weldNo"):
            if target.get(field) is None and record.get(field) is not None:
                target[field] = record[field]
    return list(grouped.values())


def _v(values: dict[str, Any], *keys: str) -> Any:
    return _value(values, *keys)


def _list(value: Any) -> list[Any]:
    if isinstance(value, str):
        return [item.strip() for item in re.split(r"[,，;；、\n]", value) if item.strip()]
    return list(value) if isinstance(value, (list, tuple, set)) else []


def _dict(value: Any) -> Any:
    return value if isinstance(value, (dict, list)) else {}


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    return [item for item in value or [] if isinstance(item, dict)] if isinstance(value, (list, tuple)) else []


def _bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    text = _norm(value)
    if text in {"true", "yes", "1", "是", "有", "合格", "通过", "已完成", "已批准"}:
        return True
    if text in {"false", "no", "0", "否", "无", "不合格", "未完成", "未批准"}:
        return False
    return None


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", str(value or "").lower())
