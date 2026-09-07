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
        "wallThicknessMm": ("wallThicknessMm", "wallThickness", "壁厚", "公称壁厚", "厚度"),
        "specification": ("specification", "size", "规格", "规格型号", "尺寸"),
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
        if target.startswith(("requires", "listedIn")) or target.endswith("Occurred"):
            value = _boolean_value(value)
        elif target in {"requiredInspectionItems", "requiredRetestItems", "requiredMaterialNdtMethods", "materialTestTriggerReasons", "requiredQuantitativeItems"}:
            value = _list_value(value)
        if _present(value):
            output[target] = value
    _fill_wall_thickness(output)
    _fill_acceptance_limits_from_standard(output)
    return output


_SPEC_THICKNESS_RE = re.compile(r"[×xX*]\s*(\d+(?:\.\d+)?)")


def _fill_wall_thickness(item: dict[str, Any]) -> None:
    """壁厚：显式字段优先，没有就从规格串（φ108×4.5、108*4.5）里取乘号后的那一段。

    为什么要它：GB/T 14976 的 S32168/S32169、GB/T 3087 的 Q345 这些牌号，限值按壁厚分档，
    没有壁厚就选不出档，限值填不出来。
    """
    if _present(item.get("wallThicknessMm")):
        try:
            item["wallThicknessMm"] = float(str(item["wallThicknessMm"]).strip().rstrip("mm ").strip())
            return
        except (TypeError, ValueError):
            item.pop("wallThicknessMm", None)
    spec = str(item.get("specification") or "").strip()
    match = _SPEC_THICKNESS_RE.search(spec)
    if match:
        try:
            item["wallThicknessMm"] = float(match.group(1))
            item["wallThicknessSource"] = "specification"
        except ValueError:
            pass


_THICKNESS_BUCKET_RE = re.compile(r"^(<=|>=|<|>)?\s*(\d+(?:\.\d+)?)\s*mm$")


def _bucket_matches(bucket: str, thickness_mm: float) -> bool:
    match = _THICKNESS_BUCKET_RE.match(str(bucket).strip())
    if not match:
        return False
    operator, raw = match.group(1) or "<=", match.group(2)
    bound = float(raw)
    if operator == "<=":
        return thickness_mm <= bound
    if operator == "<":
        return thickness_mm < bound
    if operator == ">=":
        return thickness_mm >= bound
    return thickness_mm > bound


def _resolve_by_thickness(mapping: Any, thickness_mm: float | None) -> tuple[Any, str | None]:
    """按壁厚在分档表里选一档。取不到壁厚就返回 (None, 原因)——不猜档，宁可空着。"""
    if not isinstance(mapping, dict) or not mapping:
        return None, None
    if thickness_mm is None:
        return None, f"限值按壁厚分档（{'、'.join(str(key) for key in mapping)}），设计项未给壁厚，选不出档"
    for bucket, value in mapping.items():
        if _bucket_matches(bucket, thickness_mm):
            return value, None
    return None, f"壁厚 {thickness_mm}mm 不落在任何分档（{'、'.join(str(key) for key in mapping)}）"


_RANGE_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*[-~～]\s*(\d+(?:\.\d+)?)$")
_BOUND_RE = re.compile(r"^(<=|>=|≤|≥)\s*(\d+(?:\.\d+)?)$")


def _parse_limit_text(text: Any) -> tuple[float | None, float | None]:
    """"120-160" → (120, 160)；"<=230" → (None, 230)；">=515" → (515, None)。"""
    raw = str(text or "").strip()
    match = _RANGE_RE.match(raw)
    if match:
        return float(match.group(1)), float(match.group(2))
    match = _BOUND_RE.match(raw)
    if match:
        return (None, float(match.group(2))) if match.group(1) in {"<=", "≤"} else (float(match.group(2)), None)
    return None, None


def _fill_acceptance_limits_from_standard(item: dict[str, Any]) -> None:
    """设计项没带验收限值时，按「执行标准 + 材料牌号」从法规数值表推导。

    为什么要这一步：R16 的数值比对（evaluate_r16_quality_certificate_results）要求调用方
    把 acceptanceLimits 传进来，传不进来就返回 evidence_insufficient。而设计图纸上通常只写
    「GB/T 8163-2018 Q345B」，限值在标准里——2026-09-07 线上审计前，这一步没人做，
    于是质保书上的实测值再离谱也只会被判成"证据不足"。

    只在设计项本身没给限值时才填，人工填的优先；查不到标准或牌号就什么都不做，不猜。
    """
    if _present(item.get("acceptanceLimits")):
        return
    standard = str(item.get("standardRef") or "").strip()
    grade = str(item.get("materialGrade") or "").strip()
    if not standard or not grade:
        return
    from libs.regulatory_tables import pipe_material_limits

    level = str(item.get("qualityLevel") or item.get("质量等级") or "").strip() or None
    found = pipe_material_limits(standard, grade, level)
    if not found:
        return
    mechanical = found.get("mechanical") or {}
    limits: list[dict[str, Any]] = []

    def add(code: str, name: str, *, minimum: Any = None, maximum: Any = None) -> None:
        if minimum is None and maximum is None:
            return
        entry: dict[str, Any] = {"itemCode": code, "name": name, "source": f"{found['standard']} {found['grade']}"}
        if minimum is not None:
            entry["minimum"] = minimum
        if maximum is not None:
            entry["maximum"] = maximum
        limits.append(entry)

    tensile = mechanical.get("tensileMPa")
    if isinstance(tensile, str):
        low, high = _parse_limit_text(tensile)
        add("tensileStrength", "抗拉强度", minimum=low, maximum=high)
    add("tensileStrength", "抗拉强度", minimum=mechanical.get("tensileMPaMin"))
    add("yieldStrength", "屈服强度", minimum=mechanical.get("yieldMPaMin") or mechanical.get("rp02MPaMin"))
    add("elongation", "断后伸长率", minimum=mechanical.get("elongationPctMin") or mechanical.get("elongationPctMinLongitudinal"))
    add("impactEnergy", "冲击吸收能量", minimum=mechanical.get("kv2JMin") or mechanical.get("kv2JMinLongitudinal"))

    # 按壁厚分档的限值（GB/T 14976 的 S32168/S32169/S31252、GB/T 3087 的 Q345 等）。
    # 选不出档就不填，并把原因记下来——宁可停在证据不足，也不猜一档去判不符合。
    thickness = item.get("wallThicknessMm")
    thickness_mm = float(thickness) if isinstance(thickness, (int, float)) else None
    unresolved: list[str] = []
    for key, code, name in (
        ("tensileMPaMinByThickness", "tensileStrength", "抗拉强度"),
        ("yieldMPaMinByThickness", "yieldStrength", "屈服强度"),
        ("rp02MPaMinByThickness", "yieldStrength", "屈服强度"),
    ):
        if key not in mechanical:
            continue
        value, reason = _resolve_by_thickness(mechanical.get(key), thickness_mm)
        if value is not None:
            add(code, name, minimum=value)
        elif reason:
            unresolved.append(f"{name}：{reason}")

    # 硬度区间（GB/T 5310 表 8 的 HBW/HV，13296 表 5 的上限）——质保书上这两项也要核
    hardness = found.get("hardness") or {}
    for key, code, name in (("HBW", "hardnessHBW", "布氏硬度"), ("HV", "hardnessHV", "维氏硬度")):
        low, high = _parse_limit_text(hardness.get(key))
        add(code, name, minimum=low, maximum=high)

    if limits:
        item["acceptanceLimits"] = limits
        item["acceptanceLimitsSource"] = {
            "standard": found["standard"],
            "grade": found["grade"],
            "level": found.get("level"),
            "derivedFrom": "regulatory_tables.pipeMaterialLimits",
            "verified": found.get("verified", False),
        }
        if thickness_mm is not None:
            item["acceptanceLimitsSource"]["wallThicknessMm"] = thickness_mm
    if unresolved:
        item["acceptanceLimitsUnresolved"] = unresolved


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
