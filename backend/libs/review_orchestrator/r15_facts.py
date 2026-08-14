from __future__ import annotations

import re
from typing import Any

from libs.review_orchestrator.r12_agent import (
    extract_component_items,
    extract_r12_license_candidates,
    stable_payload_hash,
)
from libs.review_orchestrator.r13_facts import (
    _business_rows,
    _common_document_fields,
    _extract_supervision_certificates,
    _extract_type_test_reports,
    _file_name,
    _normalized_business_row,
    _present,
    _r13_document_kind,
    _record_evidence,
    _unique_evidence_refs,
    _unique_records,
    _value,
)

R15_NODE_ID = 15


def build_r15_business_facts(state: dict[str, Any], review_run: dict[str, Any]) -> dict[str, Any]:
    design_items = [
        _enrich_r15_design_item(item)
        for item in extract_component_items(
            state,
            review_run,
            id_namespace="R15",
            include_certificate_items=False,
            design_only=True,
        )
    ]
    license_candidates = extract_r12_license_candidates(state, review_run, id_namespace="R15")
    latest_by_candidate: dict[str, dict[str, Any]] = {}
    for record in review_run.get("manualRegistryVerifications") or []:
        if not isinstance(record, dict):
            continue
        for verification in record.get("verifications") or []:
            if isinstance(verification, dict) and verification.get("candidateId"):
                latest_by_candidate[str(verification["candidateId"])] = verification

    supervision_certificates: list[dict[str, Any]] = []
    type_test_reports: list[dict[str, Any]] = []
    arrival_records: list[dict[str, Any]] = []
    complete_machine_records: list[dict[str, Any]] = []
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
        inspection_kind = _r15_inspection_kind(state, parse_result)
        if inspection_kind:
            records = _extract_inspection_records(state, parse_result, inspection_kind)
            if inspection_kind == "arrival":
                arrival_records.extend(records)
            else:
                complete_machine_records.extend(records)

    supervision_certificates = _unique_records(supervision_certificates, "certificateId")
    type_test_reports = _unique_records(type_test_reports, "scopeItemId")
    arrival_records = _unique_records(arrival_records, "recordId")
    complete_machine_records = _unique_records(complete_machine_records, "recordId")
    evidence_refs = _unique_evidence_refs(
        [
            *[item.get("evidence") for item in design_items],
            *[item.get("evidence") for item in license_candidates],
            *[item.get("evidence") for item in supervision_certificates],
            *[item.get("evidence") for item in type_test_reports],
            *[item.get("evidence") for item in arrival_records],
            *[item.get("evidence") for item in complete_machine_records],
        ]
    )
    claimed_facts: list[dict[str, Any]] = []
    for fact_type, records, value_keys in (
        ("design_item", design_items, ("componentType", "manufacturingCountry")),
        ("manufacturing_license", license_candidates, ("licenseNo", "organizationName")),
        ("supervision_certificate", supervision_certificates, ("certificateNo", "productName")),
        ("type_test_report", type_test_reports, ("reportNo", "productName")),
        ("arrival_inspection", arrival_records, ("recordNo", "productName")),
        ("complete_machine_inspection", complete_machine_records, ("recordNo", "productName")),
    ):
        for index, item in enumerate(records, 1):
            evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
            evidence_id = evidence.get("evidenceRefId") or evidence.get("id")
            claimed_facts.append(
                {
                    "factId": f"r15-{fact_type}-{index}",
                    "value": next((item.get(key) for key in value_keys if _present(item.get(key))), None),
                    "documentVersionId": item.get("documentVersionId"),
                    "evidenceRefIds": [evidence_id] if evidence_id else [],
                    "confidence": evidence.get("confidence") or item.get("ocrConfidence"),
                    "conflicted": bool(item.get("conflicted")),
                }
            )

    return {
        "r15": {
            "designItems": design_items,
            "manufacturingLicenseCandidates": license_candidates,
            "manualRegistryVerifications": list(latest_by_candidate.values()),
            "supervisionCertificates": supervision_certificates,
            "typeTestReports": type_test_reports,
            "arrivalInspectionRecords": arrival_records,
            "completeMachineInspectionRecords": complete_machine_records,
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


def _enrich_r15_design_item(item: dict[str, Any]) -> dict[str, Any]:
    row = item.get("sourceRow") if isinstance(item.get("sourceRow"), dict) else {}
    output = dict(item)
    aliases: dict[str, tuple[str, ...]] = {
        "manufacturingCountry": (
            "manufacturingCountry",
            "countryOfManufacture",
            "manufacturerCountry",
            "制造国家",
            "制造国",
            "制造地国家",
        ),
        "manufacturingLocation": (
            "manufacturingLocation",
            "manufacturerAddress",
            "制造地点",
            "制造地址",
            "生产地点",
        ),
        "isForeignManufactured": (
            "isForeignManufactured",
            "manufacturerIsOverseas",
            "是否境外制造",
            "境外制造",
        ),
        "manufacturingSupervisionCompletedOverseas": (
            "manufacturingSupervisionCompletedOverseas",
            "境外完成制造监检",
            "是否已境外制造监检",
        ),
        "shippedWithBoilerOrPressureVessel": (
            "shippedWithBoilerOrPressureVessel",
            "随锅炉压力容器整机配套",
            "随整机配套",
        ),
        "manufacturingInspectionRoute": (
            "manufacturingInspectionRoute",
            "制造监检路径",
            "检验路径",
        ),
    }
    for target, keys in aliases.items():
        if output.get(target) not in {None, ""}:
            continue
        value = _row_value(row, *keys)
        if target in {
            "isForeignManufactured",
            "manufacturingSupervisionCompletedOverseas",
            "shippedWithBoilerOrPressureVessel",
        }:
            value = _optional_boolean(value)
        if value not in {None, ""}:
            output[target] = value
    return output


def _extract_inspection_records(
    state: dict[str, Any],
    parse_result: dict[str, Any],
    route: str,
) -> list[dict[str, Any]]:
    common, evidence_items = _common_document_fields(state, parse_result)
    rows = _business_rows(parse_result)
    records = rows or [{}]
    output: list[dict[str, Any]] = []
    for index, row in enumerate(records, 1):
        merged = {**common, **_normalized_business_row(row)}
        record_no = _value(
            merged,
            "recordNo",
            "record_no",
            "reportNo",
            "certificateNo",
            "检验记录编号",
            "检验证书编号",
            "报告编号",
            "证书编号",
        )
        product_name = _value(merged, "productName", "product_name", "componentType", "产品名称", "元件名称")
        record_key = {
            "documentVersionId": common["documentVersionId"],
            "recordNo": record_no,
            "productName": product_name,
            "route": route,
            "rowIndex": index if rows else None,
        }
        record_id = "R15INSP-" + stable_payload_hash(record_key)[7:19].upper()
        evidence = _record_evidence(
            evidence_items,
            common["documentVersionId"],
            f"R15EV-{record_id.removeprefix('R15INSP-')}",
            record_no or product_name or ("到岸检验" if route == "arrival" else "随整机检验"),
            row=row if rows else None,
            fallback_page=common.get("pageNo") or 1,
        )
        output.append(
            {
                "recordId": record_id,
                "recordNo": record_no,
                "reportNo": _value(merged, "reportNo", "report_no", "报告编号"),
                "certificateNo": _value(merged, "certificateNo", "certificate_no", "证书编号"),
                "inspectionRoute": route,
                "productName": product_name,
                "componentType": product_name,
                "manufacturerName": _value(merged, "manufacturerName", "manufacturer", "制造单位", "生产单位"),
                "specification": _value(merged, "specification", "规格", "规格型号"),
                "batchNo": _value(merged, "batchNo", "lotNo", "批号", "批次号", "炉批号"),
                "serialNo": _value(merged, "serialNo", "productSerialNo", "产品编号", "出厂编号", "序列号"),
                "inspectionOrganization": _value(merged, "inspectionOrganization", "inspectionOrg", "检验机构", "监检机构"),
                "conclusion": _value(merged, "conclusion", "inspectionConclusion", "检验结论", "监检结论"),
                "issueDate": _value(merged, "issueDate", "issue_date", "检验日期", "签发日期"),
                "documentVersionId": common["documentVersionId"],
                "documentId": common.get("documentId"),
                "fileName": common.get("fileName"),
                "pageNo": evidence.get("pageNo"),
                "evidence": evidence,
            }
        )
    return output


def _r15_inspection_kind(state: dict[str, Any], parse_result: dict[str, Any]) -> str | None:
    metadata = parse_result.get("metadata") if isinstance(parse_result.get("metadata"), dict) else {}
    version_id = str(parse_result.get("documentVersionId") or "")
    text = " ".join(
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
            text[:5000],
        )
    )
    compact = _compact(hints)
    if any(marker in compact for marker in (_compact("随整机检验"), _compact("整机安全性能检验"), "completemachineinspection")):
        return "complete_machine"
    if any(marker in compact for marker in (_compact("到岸检验"), _compact("口岸检验"), _compact("使用地检验"), "arrivalinspection")):
        return "arrival"
    return None


def _row_value(row: dict[str, Any], *keys: str) -> Any:
    normalized = {_compact(key): value for key, value in row.items()}
    for key in keys:
        value = normalized.get(_compact(key))
        if value not in {None, ""}:
            return value
    return None


def _optional_boolean(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    normalized = _compact(value)
    if normalized in {"true", "yes", "required", "是", "需要", "适用", "1", "境外"}:
        return True
    if normalized in {"false", "no", "notrequired", "否", "不需要", "不适用", "0", "境内"}:
        return False
    return None


def _compact(value: Any) -> str:
    return re.sub(r"[\s\W_]+", "", str(value or "").lower(), flags=re.UNICODE)
