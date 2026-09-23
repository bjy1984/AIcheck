from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from libs.ocr.welder_certificate_tool import TOOL_NAME as WELDER_TOOL_NAME
from libs.ocr.welder_certificate_tool import (
    extract_welder_certificate_from_ocr_result,
    split_welder_cards,
    welder_certificate_ocr_fields,
    welder_certificate_ocr_tables,
)
from libs.review_input_data import latest_usable_selected_parses
from libs.review_orchestrator.jev_tables import business_rows
from libs.review_orchestrator.material_facts import (
    build_material_judgment,
    deduplicate,
)
from libs.review_orchestrator.r12_agent import stable_payload_hash
from libs.review_orchestrator.r13_facts import (
    _common_document_fields,
    _file_name,
    _normalized_business_row,
    _record_evidence,
    _value,
    is_placeholder,
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
    requested = {str(item) for item in review_run.get("inputDocumentVersionIds") or []}
    for parse_result in latest_usable_selected_parses(state, review_run, requested):
        kind = _document_kind(state, parse_result)
        for target, accepted_kinds in config.items():
            if kind not in accepted_kinds:
                continue
            if kind == "welder_certificate":
                records = _welder_card_records(state, parse_result, node.upper(),
                                               review_run.get("jevTableClassifications"))
            else:
                records = _extract_records(state, parse_result, node.upper(), kind,
                                           classifications=review_run.get("jevTableClassifications"))
            facts[target].extend(records)
    for target, records in facts.items():
        facts[target] = deduplicate(records, "recordId")
        evidence_groups.append((f"{node}-{target}", facts[target], ("documentNo", "recordNo", "weldNo", "materialGrade")))
    _overlay(facts, review_run, node)
    if node == "r34":
        facts["hardnessReports"] = _group_hardness_reports(facts["hardnessReports"])
    if node == "r24":
        # 原地改：evidence_groups 里存的是这个列表对象本身（judgment 就是从它建的），
        # 重新赋值只会换掉 facts 里的引用，judgment 仍然拿的是没合并的那份
        # ——2026-09-12 部署后实测：界面上「焊工证 李卫伍」还是三条。
        facts["certificates"][:] = _merge_welder_certificates(facts["certificates"])
        _overlay_platform_welder_codes(state, review_run, facts["certificates"])
        facts["qualificationCodes"] = list(dict.fromkeys(str(code) for cert in facts["certificates"] for code in cert.get("qualificationCodes") or []))
        facts["workDate"] = review_run.get("workDate") or review_run.get("reviewDate")
        facts["reviewDate"] = review_run.get("reviewDate")
    elif node == "r25":
        facts["processType"] = review_run.get("processType") or "welding"
    elif node == "r26":
        # 没人往 review_run 里放这份档案时，从法规数值表生成。
        # 2026-09-07 线上审计前一直是空的：evaluate_welding_consumable 拿不到限值，
        # 成分与力学每一项都报 product_standard_limit_profile_missing，整条判定停在证据不足。
        facts["productStandardProfiles"] = review_run.get("productStandardProfiles") or _consumable_profiles_by_designation()
        facts["reviewDate"] = review_run.get("reviewDate")
    elif node == "r27":
        facts["controlRequirements"] = review_run.get("weldingConsumableControlRequirements") or {}
    elif node == "r29":
        facts["certificates"][:] = _merge_welder_certificates(facts["certificates"])
        _overlay_platform_welder_codes(state, review_run, facts["certificates"])
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


def _merge_welder_certificates(certificates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """一个焊工一条证，不是一行一条证。

    2026-09-12 线上实测节点 24：两名焊工的资料被 OCR 拆成 15 行，每行都成了一条「证书」，
    其中 10 行只有空模板（`有效期: 自 年 月至 年 月`）。界面上「事实与证据 共 17 条」
    全是这种噪声，check_certificate_validity 也被迫对 15 张「证」逐一判有效期。
    按证件号（没有就按姓名）合并：合格项目取并集，有效期取第一条不是占位的。
    """
    merged: dict[str, dict[str, Any]] = {}
    for cert in certificates:
        key = str(cert.get("welderCertificateNo") or cert.get("welderName") or cert.get("recordId"))
        existing = merged.get(key)
        if existing is None:
            item = dict(cert)
            for field in ("validFrom", "validUntil"):
                if is_placeholder(item.get(field)):
                    item.pop(field, None)
            merged[key] = item
            continue
        codes = [*(existing.get("qualificationCodes") or []), *(cert.get("qualificationCodes") or [])]
        existing["qualificationCodes"] = list(dict.fromkeys(code for code in codes if code))
        for field in ("validFrom", "validUntil", "weldingMethod", "materialCategory", "position"):
            if not existing.get(field) and not is_placeholder(cert.get(field)):
                existing[field] = cert.get(field)
        # 证据留有内容的那条：空模板行的引文对人没用。
        if not (existing.get("evidence") or {}).get("quotedText") and (cert.get("evidence") or {}).get("quotedText"):
            existing["evidence"] = cert["evidence"]
    return list(merged.values())


def _overlay_platform_welder_codes(
    state: dict[str, Any], review_run: dict[str, Any], certificates: list[dict[str, Any]]
) -> None:
    """把公示平台登记的合格项目代号覆盖到焊工证事实上（就地改）。

    2026-09-12 线上实测节点 24：OCR 把项目代号认坏成 `CTAF-Fe II-6G-…` / `SHAW-…` /
    `PTAV-…`，解码器全部拒掉，`all_codes_decoded` 实际 0/要求 4，AC-R24-01..04 一律
    证据不足。平台按身份证返回的是登记原文（姜军那条当天核到 verified_match，
    `GTAW-FEII-6G-3/57-FEFS-02/11/12` 等），但它只进了 certificate_facts 那条链，
    r24/r29 的焊工事实是另一个 builder 自己从 OCR 建的，拿不到。这里补上。

    平台不通、查不到、或身份证号不像身份证时原样保留 OCR 值——不冒充、不判无证。
    """
    from libs.review_orchestrator.certificate_platform_verify import verify_certificate_records

    if not certificates:
        return
    records = [
        {
            "certificateNo": cert.get("welderCertificateNo") or cert.get("documentNo") or "",
            "certificateType": "welder_certificate",
            "holder": cert.get("welderName"),
            "documentVersionId": cert.get("documentVersionId"),
            "fileName": cert.get("fileName"),
            "qualificationCodes": list(cert.get("qualificationCodes") or []),
            "validUntil": cert.get("validUntil"),
        }
        for cert in certificates
    ]
    verified = verify_certificate_records(
        state, {"certificateType": "welder_certificate"}, records, review_run=review_run
    )
    for cert, item in zip(certificates, verified):
        verification = item.get("platformVerification")
        if not verification:
            continue
        cert["platformVerification"] = verification
        if verification.get("outcome") != "verified_match":
            continue
        codes = [str(code) for code in item.get("qualificationCodes") or [] if code]
        if codes:
            cert["qualificationCodes"] = codes
            cert.setdefault("sources", {})["qualificationCodes"] = "cnse_platform"
        if item.get("validUntil"):
            cert["validUntil"] = item["validUntil"]
        # 平台那条登记原文也要作为证据挂上：界面据此把「平台已核验」的证书高亮，
        # 监检才分得出哪几条是登记原文、哪几条只是 OCR 读出来的。
        platform_evidence = [ref for ref in item.get("evidence") or [] if isinstance(ref, dict) and ref.get("source") == "cnse_platform"]
        if platform_evidence:
            cert["platformEvidence"] = platform_evidence[-1]


# 焊工证抽取器产出的字段：已落库的旧 OCR 结果里这几项是旧版抽取器算的
# （2026-09-23 本地快照：批准日 2027.04.30、有效期 2027.04.20），一律按原文重抽。
_WELDER_FIELD_CODES = frozenset({"welder_name", "welder_certificate_no", "welder_archive_no", "issuing_authority",
                                 "welder_operation_item_code", "approval_date", "valid_until"})


def _fresh_welder_parse(parse_result: dict[str, Any], fragments: list[dict[str, Any]], *,
                        keep_stored: bool) -> dict[str, Any]:
    """焊工字段和抽取器生成的合格项目表按原文重算；其余已落库的字段与表格按需保留。"""
    extraction = extract_welder_certificate_from_ocr_result({"fragments": fragments})
    fields = [item for item in parse_result.get("fields") or []
              if isinstance(item, dict) and item.get("fieldCode") not in _WELDER_FIELD_CODES] if keep_stored else []
    tables = [item for item in parse_result.get("tables") or []
              if isinstance(item, dict) and item.get("extractionMethod") != WELDER_TOOL_NAME] if keep_stored else []
    return {**parse_result, "fragments": fragments, "fields": [*fields, *welder_certificate_ocr_fields(extraction)],
            "tables": [*tables, *welder_certificate_ocr_tables(extraction)]}


def _welder_card_records(state: dict[str, Any], parse_result: dict[str, Any], namespace: str,
                         classifications: dict[str, Any] | None) -> list[dict[str, Any]]:
    """几个焊工的证合订成一份时，每人一段、只用自己那段抽姓名证号项目。

    整份文件层面的 OCR 字段是对合订本整体抽的，会把甲的姓名配上乙的身份证号
    （2026-09-23 本地快照：李卫伍的记录带着赵相军的证号），名单表的行也认不出属于谁，
    所以分段时两样都不继承；各人的合格项目由公示平台按各自证号补。不足两段时照旧按整份处理，
    但焊工字段按原文重抽，不用旧版抽取器落库的值。
    """
    fragments = [item for item in parse_result.get("fragments") or [] if isinstance(item, dict)]
    segments = split_welder_cards(fragments) if fragments else []
    if len(segments) < 2:
        refreshed = _fresh_welder_parse(parse_result, fragments, keep_stored=True) if fragments else parse_result
        records = _extract_records(state, refreshed, namespace, "welder_certificate", classifications=classifications)
    else:
        records = []
        for index, segment in enumerate(segments, 1):
            records.extend(_extract_records(state, _fresh_welder_parse(parse_result, segment, keep_stored=False),
                                            namespace, "welder_certificate", segment=index))
    # 焊工证抽取器给的 0.78 是启发分数，不是 OCR 置信度；引擎声明不报分时，证据按「未评分」交人工。
    if "provider_confidence_unavailable" in ((parse_result.get("quality") or {}).get("reasons") or []):
        for record in records:
            if isinstance(record.get("evidence"), dict):
                record["evidence"]["confidenceUnavailable"] = True
    return records


def _extract_records(state: dict[str, Any], parse_result: dict[str, Any], namespace: str, kind: str,
                     *, classifications: dict[str, Any] | None = None, segment: int | None = None) -> list[dict[str, Any]]:
    common, evidence_items = _common_document_fields(state, parse_result)
    document_values = _field_values(parse_result)
    rows = business_rows(parse_result, classifications,
                         skip_mechanical=namespace in {"R25", "R29", "R32"}) or [{}]
    output: list[dict[str, Any]] = []
    for index, row in enumerate(rows, 1):
        values = {**document_values, **_normalized_business_row(row)}
        scope = {"documentVersionId": common["documentVersionId"], "kind": kind, "row": index,
                 **({"segment": segment} if segment is not None else {})}
        record_id = f"{namespace}-" + stable_payload_hash(scope)[7:19].upper()
        evidence = _record_evidence(evidence_items, common["documentVersionId"], f"{namespace}EV-{record_id[-12:]}", _value(values, "documentNo", "recordNo", "weldNo", "证书编号", "记录编号") or kind, row=row if row else None, fallback_page=common.get("pageNo") or 1)
        record = _mapped(values, kind)
        # 证据要带文件名与 documentId：界面上「第 1 页」不说是哪份文件，点也点不开。
        evidence.setdefault("fileName", common.get("fileName"))
        evidence.setdefault("documentId", common.get("documentId"))
        if not _has_business_content(record):
            continue
        record.update({"recordId": record_id, "recordKind": kind, "documentVersionId": common["documentVersionId"], "documentId": common.get("documentId"), "fileName": common.get("fileName"), "pageNo": evidence.get("pageNo"), "ocrConfidence": evidence.get("confidence"), "evidence": evidence})
        output.append({key: value for key, value in record.items() if value is not None})
    return output


def _has_business_content(record: dict[str, Any]) -> bool:
    """这一行有没有抽到任何业务内容。

    表格每一行都会变成一条记录，而 OCR 常把表头、空模板、跨页残行也读成行
    （2026-09-13 实测：节点 26 的 56 条事实里 55 条重复、节点 29 的 53 条全是空壳，
    节点 24 两名焊工被拆成 15 行、其中 10 行只有「有效期: 自 年 月至 年 月」）。
    一个业务字段都没有的行不该成为事实——它既核不了，也把真要看的挤下去。
    """
    for key, value in record.items():
        if key in {"recordId", "recordKind", "documentVersionId", "documentId", "fileName", "pageNo", "ocrConfidence", "evidence"}:
            continue
        if isinstance(value, (list, dict)):
            if value:
                return True
            continue
        if value is not None and not is_placeholder(value):
            return True
    return False


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


# 文档类型路由，顺序即优先级。每条是 (kind, 标题标记, 名称标记)：
# - 标题标记：文档自身标注 + 文件名 + 正文前 600 字里出现即算数，是明确的文件抬头；
# - 名称标记：只认文档自身标注与文件名。这些词会出现在目录/核查表里（「附件 4、焊接工艺评定」），
#   在正文里出现只说明这份文件提到过它，不说明它就是它。
# 2026-09-11 按生产 290 份解析结果逐条核对过，注释里的文件名都是真实样本。
_KIND_ROUTES: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    ("welder_certificate", ("weldercertificate", "welderroster", "焊工资格证", "焊工证"), ("焊工名册", "焊工清单")),
    ("pipeline_summary", ("pipelinesummary", "管线汇总表"), ()),
    ("wps_pqr", ("wpspqr", "weldingprocedurequalification", "焊接工艺评定报告和焊接作业指导书", "pqrwps"), ()),
    # 「焊接工艺评定」不带「报告」也成立：不锈钢氩弧焊HP022-2024焊接工艺评定.pdf 标题里就没有「报告」。
    # 但只认文件名/标注——0压力管道安装监检流程指引.docx 的核查表第 9 项、
    # 贵州化工交工资料.pdf 的目录「附件 4、焊接工艺评定」都会让正文命中，那是清单不是评定报告。
    ("pqr", ("pqr", "焊接工艺评定报告"), ("焊接工艺评定",)),
    # 原来这里有个裸 "wps" 标记，会命中评定报告里的「预焊接规程编号 pWPS-2023-01」，
    # 把 9.1金辉焊接工艺评定20.pdf、焊接工艺评定报告.pdf 这两份 PQR 判成 wps，
    # 于是节点 25 的 pqrItems、节点 32 的 qualificationReports 恒为 0。
    ("wps", ("焊接作业指导书", "焊接工艺规程", "焊接工艺卡"), ()),
    ("welding_consumable_certificate", ("weldingconsumablecertificate", "焊接材料质量证明", "焊材质量证明"), ()),
    ("consumable_receipt", ("consumablereceipt", "焊材验收"), ()),
    ("consumable_management", ("consumablemanagement", "焊材库", "焊条烘干", "焊材领用", "焊材回收"), ()),
    ("pipe_fit_up_record", ("pipefitup", "管道组对", "组对检查"), ()),
    ("weld_appearance_record", ("weldappearance", "焊缝外观"), ("外观检查记录",)),
    ("weld_repair_record", ("weldrepair", "焊缝返修", "返修申请"), ()),
    ("heat_treatment_procedure", ("heattreatmentprocedure", "热处理工艺卡", "热处理工艺文件"), ()),
    ("temperature_point_layout", ("temperaturepointlayout", "测温点布置图"), ()),
    ("heat_treatment_instrument", ("heattreatmentinstrument", "热电偶校准", "温控仪校验", "测温记录仪"), ()),
    ("hardness_report", ("hardnessreport", "硬度检测报告", "硬度测试报告"), ()),
    ("heat_treatment_record", ("heattreatmentrecord", "热处理报告", "温度时间曲线"), ()),
    ("welding_record", ("weldingrecord", "焊接施工记录", "施焊记录"), ()),
    ("design_document", ("designdocument", "设计说明", "设计文件"), ("施工图", "设计图纸", "图纸目录")),
)

# 需要同时命中全部标记才成立，先于单标记路由判定。
_COMBINED_KIND_ROUTES: tuple[tuple[str, tuple[str, ...]], ...] = (
    # 评定报告正文必带预焊接工艺规程（pWPS），这类文件同时是 WPS 与 PQR 的来源，
    # 判成 wps_pqr 才能同时喂饱 wpsItems 与 pqrItems。
    ("wps_pqr", ("焊接工艺评定", "预焊接")),
    ("wps_pqr", ("焊接工艺评定", "pwps")),
)

# 国家标准/规范正文不是本工程的施工证据。生产有 60 份 materialTypeCode=standard_reference，
# 老写法按正文关键词把它们判成了 wps / wps_pqr / 焊材质量证明（TSGZ6002-2010《焊接人员考核细则》.pdf、
# GB 50236-2011、JB∕T 3223-2017、NBT 47018-2017），一旦被挂到节点上就会当成质量证明去核。
STANDARD_REFERENCE_MATERIAL_CODES = ("standard_reference",)

# 标题区窗口：文件自己的抬头在开头这一段里。老写法拿正文前 4000 字做匹配，
# 「提到过 X」和「本身就是 X」不分——9.2.焊接工艺卡.pdf 因正文引用
# 「焊接工艺评定报告编号」被判成评定报告。
_TITLE_TEXT_CHARS = 600

# 「X编号」是在引用 X，不是在自称 X：焊接工艺卡上写「焊接工艺评定报告编号 HP/P-2023-01」，
# 是把它依据的评定报告编号填进去。抬头自己带的「报告编号：」不受影响——
# 那是「焊接工艺评定报告」后面跟「报告编号」，不是紧跟着「编号」。
_CITATION_SUFFIX = "编号"


def _marker_hit(marker: str, hints: str) -> bool:
    normalized = _norm(marker)
    if not normalized:
        return False
    start = hints.find(normalized)
    while start >= 0:
        tail = hints[start + len(normalized):]
        if not tail.startswith(_CITATION_SUFFIX):
            return True
        start = hints.find(normalized, start + 1)
    return False


def _document_text(parse_result: dict[str, Any]) -> str:
    return " ".join(
        str(item.get("fieldValue") or item.get("value") or item.get("text") or "")
        for item in [*(parse_result.get("fields") or []), *(parse_result.get("fragments") or [])]
        if isinstance(item, dict)
    )


def _material_type_code(state: dict[str, Any], version_id: str) -> str:
    """文档上人工/流水线标注的物料类型。

    解析结果自己的 materialTypeCode 在生产里恒为 None（2026-09-11 实测 290 份全空），
    真正有值的是 documents 表上的那份，老写法够不着它。
    """
    version = next(
        (
            item
            for item in state.get("versions", [])
            if isinstance(item, dict)
            and str(item.get("id") or item.get("versionId") or item.get("documentVersionId") or "") == version_id
        ),
        None,
    )
    if not version:
        return ""
    document = next(
        (
            item
            for item in state.get("documents", [])
            if isinstance(item, dict) and str(item.get("id") or item.get("documentId") or "") == str(version.get("documentId") or "")
        ),
        None,
    )
    source = document or version
    return " ".join(str(source.get(key) or "") for key in ("materialTypeCode", "materialTypeName"))


def _document_kind(state: dict[str, Any], parse_result: dict[str, Any]) -> str | None:
    metadata = parse_result.get("metadata") if isinstance(parse_result.get("metadata"), dict) else {}
    version_id = str(parse_result.get("documentVersionId") or "")
    material_type = _material_type_code(state, version_id)
    if any(_norm(code) in _norm(material_type) for code in STANDARD_REFERENCE_MATERIAL_CODES):
        return None
    declared = " ".join(
        str(value or "")
        for value in (
            parse_result.get("profileId"),
            parse_result.get("documentType"),
            parse_result.get("materialTypeCode"),
            metadata.get("detectedProfileId"),
            metadata.get("materialTypeCode"),
            material_type,
            _file_name(state, version_id),
        )
    )
    name_hints = _norm(declared)
    title_hints = _norm(declared + " " + _document_text(parse_result)[:_TITLE_TEXT_CHARS])
    for kind, markers in _COMBINED_KIND_ROUTES:
        if all(_marker_hit(marker, title_hints) for marker in markers):
            return kind
    for kind, title_markers, name_markers in _KIND_ROUTES:
        if any(_marker_hit(marker, title_hints) for marker in title_markers):
            return kind
        if any(_marker_hit(marker, name_hints) for marker in name_markers):
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


def _consumable_profiles_by_designation() -> dict[str, Any]:
    """把法规表里的焊材限值摊成 evaluate_welding_consumable 要的形状。

    该工具按「标准号」取档案，再逐项比对成分与力学，所以同一标准下的不同型号必须分开——
    E4303 与 E5015 的抗拉强度差 60MPa，混在一起比会把合格的判成不合格。
    这里把键做成「标准号 + 型号」，同时保留只按标准号的兜底（该标准只有一个型号时才有意义）。
    """
    import re

    from libs.regulatory_tables import welding_consumable_standard_profiles

    out: dict[str, Any] = {}
    for profile in welding_consumable_standard_profiles().values():
        standard = profile["standard"]
        by_designation = profile.get("byDesignation") or {}
        for designation, entry in by_designation.items():
            payload = {
                "standard": standard,
                "designation": designation,
                "chemicalComposition": entry.get("chemicalComposition") or {},
                "mechanicalProperties": entry.get("mechanicalProperties") or {},
                "impactTemperatureC": entry.get("impactTemperatureC"),
                "verified": profile.get("verified", False),
            }
            for key in {standard, f"{standard} {designation}", designation, entry.get("commonName")}:
                if key:
                    out.setdefault(re.sub(r"[^a-z0-9]", "", str(key).lower()), payload)
        if len(by_designation) != 1:
            # 一个标准多个型号时，只按标准号取档案是不安全的——拿掉那个兜底键
            out.pop(re.sub(r"[^a-z0-9]", "", standard.lower()), None)
    return out
