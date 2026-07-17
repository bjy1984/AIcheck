from __future__ import annotations

import json
import re
from typing import Any

from libs.review_orchestrator.r12_agent import extract_component_items, stable_payload_hash


R13_NODE_ID = 13


def build_r13_business_facts(state: dict[str, Any], review_run: dict[str, Any]) -> dict[str, Any]:
    design_items = extract_component_items(
        state,
        review_run,
        id_namespace="R13",
        include_certificate_items=False,
        design_only=True,
    )
    supervision_certificates: list[dict[str, Any]] = []
    type_test_reports: list[dict[str, Any]] = []
    requested_versions = {str(item) for item in review_run.get("inputDocumentVersionIds") or [] if item}
    for parse_result in state.get("ocr_parse_results", []):
        if not isinstance(parse_result, dict):
            continue
        version_id = str(parse_result.get("documentVersionId") or "")
        if requested_versions and version_id not in requested_versions:
            continue
        document_kind = _r13_document_kind(state, parse_result)
        if document_kind == "manufacturing_supervision_certificate":
            supervision_certificates.extend(_extract_supervision_certificates(state, parse_result))
        elif document_kind == "type_test_report":
            type_test_reports.extend(_extract_type_test_reports(state, parse_result))

    supervision_certificates = _unique_records(supervision_certificates, "certificateId")
    type_test_reports = _unique_records(type_test_reports, "scopeItemId")
    evidence_refs = _unique_evidence_refs(
        [
            *[item.get("evidence") for item in design_items],
            *[item.get("evidence") for item in supervision_certificates],
            *[item.get("evidence") for item in type_test_reports],
        ]
    )
    claimed_facts = []
    for fact_type, records, value_keys in (
        ("design_item", design_items, ("componentType", "specification")),
        ("supervision_certificate", supervision_certificates, ("certificateNo", "productName")),
        ("type_test_report", type_test_reports, ("reportNo", "productName")),
    ):
        for index, item in enumerate(records, 1):
            evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
            evidence_id = evidence.get("evidenceRefId") or evidence.get("id")
            claimed_facts.append(
                {
                    "factId": f"r13-{fact_type}-{index}",
                    "value": next((item.get(key) for key in value_keys if _present(item.get(key))), None),
                    "documentVersionId": item.get("documentVersionId"),
                    "evidenceRefIds": [evidence_id] if evidence_id else [],
                    "confidence": evidence.get("confidence"),
                    "conflicted": bool(item.get("conflicted")),
                }
            )

    return {
        "r13": {
            "designItems": design_items,
            "supervisionCertificates": supervision_certificates,
            "typeTestReports": type_test_reports,
        },
        "judgment": {"claimedFacts": claimed_facts, "evidenceRefs": evidence_refs},
        "evidence": {
            "pageNo": [item.get("pageNo") for item in evidence_refs],
            "bboxOrQuotedText": [item.get("bbox") or item.get("quotedText") for item in evidence_refs],
            "ocrConfidence": [item.get("confidence") for item in evidence_refs],
            "conflictStatus": "no_conflict_detected" if claimed_facts and not any(item.get("conflicted") for item in claimed_facts) else "unknown",
        },
    }


def _extract_supervision_certificates(state: dict[str, Any], parse_result: dict[str, Any]) -> list[dict[str, Any]]:
    common, evidence_items = _common_document_fields(state, parse_result)
    rows = _business_rows(parse_result)
    records = rows or [{}]
    output = []
    for index, row in enumerate(records, 1):
        merged = {**common, **_normalized_business_row(row)}
        certificate_no = _value(
            merged,
            "certificateNo",
            "certificate_no",
            "supervisionCertificateNo",
            "监检证书编号",
            "证书编号",
        )
        product_name = _value(merged, "productName", "product_name", "componentType", "产品名称", "元件名称")
        record_key = {
            "documentVersionId": common["documentVersionId"],
            "certificateNo": certificate_no,
            "productName": product_name,
            "rowIndex": index if rows else None,
        }
        certificate_id = "R13SC-" + stable_payload_hash(record_key)[7:19].upper()
        evidence = _record_evidence(
            evidence_items,
            common["documentVersionId"],
            f"R13EV-{certificate_id.removeprefix('R13SC-')}",
            certificate_no or product_name or "制造监督检验证书",
            row=row if rows else None,
            fallback_page=common.get("pageNo") or 1,
        )
        output.append(
            {
                "certificateId": certificate_id,
                "certificateNo": certificate_no,
                "productName": product_name,
                "componentType": product_name,
                "manufacturerName": _value(merged, "manufacturerName", "manufacturer", "制造单位", "生产单位"),
                "specification": _value(merged, "specification", "specificationScope", "规格", "规格型号"),
                "material": _value(merged, "material", "materialGrade", "材料", "材质", "材料牌号"),
                "manufacturingProcess": _value(merged, "manufacturingProcess", "manufacturing_process", "process", "制造工艺"),
                "structure": _value(merged, "structure", "structureType", "结构", "结构型式"),
                "batchNo": _value(merged, "batchNo", "lotNo", "批号", "批次号", "炉批号"),
                "serialNo": _value(merged, "serialNo", "productSerialNo", "产品编号", "出厂编号", "序列号"),
                "conclusion": _value(merged, "conclusion", "inspectionConclusion", "监检结论", "检验结论"),
                "issueDate": _value(merged, "issueDate", "issue_date", "签发日期", "发证日期"),
                "supervisionOrganization": _value(merged, "supervisionOrganization", "supervision_organization", "inspectionOrganization", "监检机构", "检验机构"),
                "documentVersionId": common["documentVersionId"],
                "documentId": common.get("documentId"),
                "fileName": common.get("fileName"),
                "pageNo": evidence.get("pageNo"),
                "evidence": evidence,
            }
        )
    return output


def _extract_type_test_reports(state: dict[str, Any], parse_result: dict[str, Any]) -> list[dict[str, Any]]:
    common, evidence_items = _common_document_fields(state, parse_result)
    rows = _business_rows(parse_result)
    records = rows or [{}]
    output = []
    for index, row in enumerate(records, 1):
        merged = {**common, **_normalized_business_row(row)}
        report_no = _value(
            merged,
            "reportNo",
            "report_no",
            "certificateNo",
            "certificate_no",
            "型式试验报告编号",
            "型式试验证书编号",
            "报告编号",
            "证书编号",
        )
        product_name = _value(merged, "productName", "product_name", "componentType", "产品名称", "元件名称")
        scope_key = {
            "documentVersionId": common["documentVersionId"],
            "reportNo": report_no,
            "productName": product_name,
            "rowIndex": index if rows else None,
        }
        report_id = "R13TR-" + stable_payload_hash({"documentVersionId": common["documentVersionId"], "reportNo": report_no})[7:19].upper()
        scope_item_id = "R13SCOPE-" + stable_payload_hash(scope_key)[7:19].upper()
        evidence = _record_evidence(
            evidence_items,
            common["documentVersionId"],
            f"R13EV-{scope_item_id.removeprefix('R13SCOPE-')}",
            report_no or product_name or "型式试验",
            row=row if rows else None,
            fallback_page=common.get("pageNo") or 1,
        )
        output.append(
            {
                "reportId": report_id,
                "scopeItemId": scope_item_id,
                "reportNo": report_no,
                "certificateNo": _value(merged, "certificateNo", "certificate_no", "型式试验证书编号", "证书编号"),
                "productName": product_name,
                "componentType": product_name,
                "manufacturerName": _value(merged, "manufacturerName", "manufacturer", "制造单位", "申请单位", "委托单位"),
                "testOrganization": _value(merged, "testOrganization", "test_organization", "testOrg", "型式试验机构", "检验机构", "试验机构"),
                "specification": _value(merged, "specification", "规格", "规格型号"),
                "specificationScope": _value(merged, "specificationScope", "scopeDescription", "覆盖范围", "规格范围"),
                "material": _value(merged, "material", "materialGrade", "材料", "材质", "材料牌号"),
                "structure": _value(merged, "structure", "structureType", "结构", "结构型式"),
                "manufacturingProcess": _value(merged, "manufacturingProcess", "manufacturing_process", "process", "制造工艺", "工艺"),
                "nominalDiameterMinMM": _value(merged, "nominalDiameterMinMM", "nominal_diameter_min_mm", "diameterMinMM", "最小公称直径", "DN下限"),
                "nominalDiameterMaxMM": _value(merged, "nominalDiameterMaxMM", "nominal_diameter_max_mm", "diameterMaxMM", "最大公称直径", "DN上限"),
                "nominalPressureMinMPa": _value(merged, "nominalPressureMinMPa", "nominal_pressure_min_mpa", "pressureMinMPa", "最小公称压力", "PN下限"),
                "nominalPressureMaxMPa": _value(merged, "nominalPressureMaxMPa", "nominal_pressure_max_mpa", "pressureMaxMPa", "最大公称压力", "PN上限"),
                "conclusion": _value(merged, "conclusion", "testConclusion", "型式试验结论", "试验结论", "检验结论"),
                "status": _value(merged, "status", "certificateStatus", "证书状态"),
                "validFrom": _value(merged, "validFrom", "valid_from", "有效期起"),
                "validUntil": _value(merged, "validUntil", "valid_until", "有效期至"),
                "standardRef": _value(merged, "standardRef", "standardNo", "依据标准", "标准编号"),
                "documentVersionId": common["documentVersionId"],
                "documentId": common.get("documentId"),
                "fileName": common.get("fileName"),
                "pageNo": evidence.get("pageNo"),
                "evidence": evidence,
            }
        )
    return output


def _common_document_fields(
    state: dict[str, Any],
    parse_result: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    version_id = str(parse_result.get("documentVersionId") or "")
    items = [
        item
        for item in [*(parse_result.get("fields") or []), *(parse_result.get("fragments") or [])]
        if isinstance(item, dict)
    ]
    field_values: dict[str, Any] = {}
    for item in items:
        key = str(item.get("fieldCode") or item.get("key") or item.get("name") or "").strip()
        value = item.get("fieldValue") if _present(item.get("fieldValue")) else item.get("value")
        if key and _present(value):
            field_values[key] = _cell_value(value)
    text = "\n".join(_item_text(item) for item in items if _item_text(item))
    common: dict[str, Any] = {
        "documentVersionId": version_id,
        "documentId": parse_result.get("documentId"),
        "fileName": _file_name(state, version_id),
        "pageNo": _first_page(items),
        **field_values,
    }
    for labels in (
        ("证书编号", "报告编号", "certificateNo"),
        ("产品名称", "元件名称", "productName"),
        ("制造单位", "生产单位", "manufacturerName"),
        ("型式试验机构", "试验机构", "testOrganization"),
        ("检验结论", "试验结论", "conclusion"),
        ("规格范围", "覆盖范围", "specificationScope"),
        ("批号", "批次号", "batchNo"),
        ("产品编号", "出厂编号", "serialNo"),
    ):
        if not _value(common, labels[-1]):
            common[labels[-1]] = _labeled_value(text, labels[:-1])
    return common, items


def _r13_document_kind(state: dict[str, Any], parse_result: dict[str, Any]) -> str | None:
    metadata = parse_result.get("metadata") if isinstance(parse_result.get("metadata"), dict) else {}
    version_id = str(parse_result.get("documentVersionId") or "")
    item_text = " ".join(
        _item_text(item)
        for item in [*(parse_result.get("fields") or []), *(parse_result.get("fragments") or [])]
        if isinstance(item, dict) and _item_text(item)
    )
    hints = " ".join(
        str(value or "")
        for value in (
            parse_result.get("profileId"),
            parse_result.get("documentType"),
            metadata.get("detectedProfileId"),
            _file_name(state, version_id),
            item_text[:4000],
        )
    )
    compact = _normalize(hints)
    if any(marker in compact for marker in ("manufacturingsupervisioncertificate", "制造监督检验证书", "压力管道元件制造监督检验证书")):
        return "manufacturing_supervision_certificate"
    if any(marker in compact for marker in ("typetestreport", "型式试验证书", "型式试验报告")):
        return "type_test_report"
    return None


def _business_rows(parse_result: dict[str, Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for table in parse_result.get("tables") or []:
        if not isinstance(table, dict):
            continue
        rows = table.get("normalizedRows") or table.get("records") or []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            if _value(row, "productName", "product_name", "componentType", "产品名称", "元件名称", "品名"):
                output.append(row)
    return output


def _record_evidence(
    items: list[dict[str, Any]],
    version_id: str,
    evidence_id: str,
    query: Any,
    *,
    row: dict[str, Any] | None,
    fallback_page: int,
) -> dict[str, Any]:
    normalized_query = _normalize(query)
    ranked = sorted(
        items,
        key=lambda item: (normalized_query in _normalize(_item_text(item)), _confidence(item)),
        reverse=True,
    )
    primary = ranked[0] if ranked else {}
    quoted_text = json.dumps(row, ensure_ascii=False, default=str)[:800] if row else _item_text(primary)
    return {
        "id": evidence_id,
        "evidenceRefId": evidence_id,
        "documentVersionId": version_id,
        "pageNo": primary.get("pageNo") or fallback_page,
        "bbox": primary.get("bbox") or primary.get("polygon") or (row or {}).get("bbox") or (row or {}).get("polygon"),
        "quotedText": quoted_text,
        "confidence": _confidence(primary) or _confidence(row or {}),
    }


def _normalized_business_row(row: dict[str, Any]) -> dict[str, Any]:
    return {str(key): _cell_value(value) for key, value in row.items() if _present(_cell_value(value))}


def _unique_records(items: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for item in items:
        identifier = str(item.get(key) or stable_payload_hash(item))
        output[identifier] = item
    return list(output.values())


def _unique_evidence_refs(items: list[Any]) -> list[dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        identifier = str(item.get("evidenceRefId") or item.get("id") or "")
        if identifier:
            output[identifier] = item
    return list(output.values())


def _value(values: dict[str, Any], *keys: str) -> Any:
    normalized = {_normalize(key): value for key, value in values.items()}
    for key in keys:
        value = normalized.get(_normalize(key))
        if _present(value):
            return _cell_value(value)
    return None


def _cell_value(value: Any) -> Any:
    if isinstance(value, dict):
        for key in ("value", "fieldValue", "text", "rawValue"):
            if _present(value.get(key)):
                return value[key]
    return value


def _present(value: Any) -> bool:
    if value is None or value == "":
        return False
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def _labeled_value(text: str, labels: tuple[str, ...]) -> str | None:
    for line in text.splitlines():
        for label in labels:
            if label not in line:
                continue
            value = re.sub(rf"^.*?{re.escape(label)}\s*[：:]?\s*", "", line).strip()
            if value and value != line.strip():
                return value[:1000]
    return None


def _item_text(item: dict[str, Any]) -> str:
    return str(item.get("text") or item.get("quotedText") or item.get("fieldValue") or item.get("value") or "").strip()


def _confidence(item: dict[str, Any]) -> float:
    try:
        return round(float(item.get("confidence") or item.get("ocrConfidence") or 0), 4)
    except (TypeError, ValueError):
        return 0.0


def _first_page(items: list[dict[str, Any]]) -> int:
    for item in items:
        try:
            return max(1, int(item.get("pageNo") or 1))
        except (TypeError, ValueError):
            continue
    return 1


def _file_name(state: dict[str, Any], version_id: str) -> str | None:
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
        return None
    if version.get("fileName"):
        return str(version["fileName"])
    document_id = str(version.get("documentId") or "")
    document = next(
        (
            item
            for item in state.get("documents", [])
            if isinstance(item, dict) and str(item.get("id") or item.get("documentId") or "") == document_id
        ),
        None,
    )
    return str((document or {}).get("fileName") or (document or {}).get("name") or "") or None


def _normalize(value: Any) -> str:
    return re.sub(r"[\s\W_]+", "", str(value or "").lower(), flags=re.UNICODE)
