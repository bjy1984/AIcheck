from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from apps.ocr_service.welder_certificate_tool import extract_welder_certificate_from_ocr_result


RUNTIME_TOOL_DESCRIPTORS: list[dict[str, Any]] = [
    {
        "name": "get_document_ocr_result",
        "capability": (
            "读取 OCR 文本、结构化字段、表格、印章和签名识别结果。"
        ),
        "inputSchema": {"documentVersionIds": ["string"]},
    },
    {
        "name": "recognize_document_seals",
        "capability": "读取 OCR 结果中的印章候选、印章文字、位置和置信度。",
        "inputSchema": {"documentVersionIds": ["string"], "expectedIssuer": "string?"},
    },
    {
        "name": "extract_structured_fields",
        "capability": (
            "按资料类型抽取证件编号、档案编号、发证机关、有效期、"
            "作业项目等结构化字段。"
        ),
        "inputSchema": {"documentVersionIds": ["string"], "materialTypeCode": "string?"},
    },
    {
        "name": "extract_welder_certificate",
        "capability": (
            "从焊工资格证 OCR 结果中抽取证件编号、档案编号、"
            "发证机关和作业项目。"
        ),
        "inputSchema": {"documentVersionIds": ["string"]},
    },
    {
        "name": "verify_license_or_certificate",
        "capability": (
            "综合结构化字段、有效期、印章识别和 OCR 质量信号"
            "核验证照或人员证书风险。"
        ),
        "inputSchema": {"documentVersionIds": ["string"], "materialTypeCode": "string?"},
    },
    {
        "name": "verify_welder_certificate_authenticity",
        "capability": (
            "综合焊工证字段、作业项目有效期、发证机关和印章识别结果，"
            "输出真实性风险信号。"
        ),
        "inputSchema": {"documentVersionIds": ["string"]},
    },
]


def runtime_tool_catalog() -> list[dict[str, Any]]:
    return [dict(item) for item in RUNTIME_TOOL_DESCRIPTORS]


def dispatch_runtime_tool(
    state: dict[str, Any],
    tool_name: str,
    arguments: dict[str, Any] | None = None,
    *,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    args = arguments or {}
    context = context or {}
    if tool_name == "get_document_ocr_result":
        return get_document_ocr_result(state, args, context=context)
    if tool_name == "recognize_document_seals":
        return recognize_document_seals(state, args, context=context)
    if tool_name in {"extract_structured_fields", "extract_welder_certificate"}:
        result = extract_structured_fields(state, args, context=context)
        result["toolName"] = tool_name
        return result
    if tool_name in {"verify_license_or_certificate", "verify_welder_certificate_authenticity"}:
        result = verify_license_or_certificate(state, args, context=context)
        result["toolName"] = tool_name
        return result
    return {
        "toolCallId": runtime_tool_call_id(),
        "toolName": tool_name,
        "status": "rejected",
        "errorCode": "RUNTIME_TOOL_NOT_IMPLEMENTED",
        "message": f"Runtime tool {tool_name} is not implemented.",
    }


def get_document_ocr_result(
    state: dict[str, Any],
    arguments: dict[str, Any],
    *,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    parse_results = selected_parse_results(state, arguments, context=context)
    fields = [field for result in parse_results for field in dict_items(result.get("fields"))]
    tables = [table for result in parse_results for table in dict_items(result.get("tables"))]
    seals = [seal for result in parse_results for seal in dict_items(result.get("seals"))]
    fragments = [
        fragment
        for result in parse_results
        for fragment in dict_items(result.get("fragments"))
    ]
    return {
        "toolCallId": runtime_tool_call_id(),
        "toolName": "get_document_ocr_result",
        "status": "succeeded",
        "documentVersionIds": [item.get("documentVersionId") for item in parse_results],
        "fieldCount": len(fields),
        "tableCount": len(tables),
        "sealCount": len(seals),
        "fragmentCount": len(fragments),
        "fields": fields[:80],
        "tables": tables[:20],
        "seals": seals[:20],
        "fragments": fragments[:80],
    }


def recognize_document_seals(
    state: dict[str, Any],
    arguments: dict[str, Any],
    *,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    parse_results = selected_parse_results(state, arguments, context=context)
    expected_issuer = str(arguments.get("expectedIssuer") or "").strip()
    seals = []
    for result in parse_results:
        for seal in dict_items(result.get("seals")):
            item = {
                "documentVersionId": result.get("documentVersionId"),
                "sealId": seal.get("sealId") or seal.get("id"),
                "sealName": seal.get("sealName") or seal.get("name") or seal.get("text"),
                "sealText": seal.get("sealText") or seal.get("text") or seal.get("rawText"),
                "sealType": seal.get("sealType"),
                "pageNo": seal.get("pageNo") or 1,
                "bbox": seal.get("bbox") or seal.get("polygon"),
                "visualConfidence": seal.get("visualConfidence"),
                "ocrConfidence": seal.get("ocrConfidence"),
                "sourceEngine": seal.get("sourceEngine"),
                "qualityFlags": seal.get("qualityFlags") or [],
            }
            item["matchesExpectedIssuer"] = issuer_matches_seal(expected_issuer, item)
            seals.append(item)
    return {
        "toolCallId": runtime_tool_call_id(),
        "toolName": "recognize_document_seals",
        "status": "succeeded",
        "sealCount": len(seals),
        "expectedIssuer": expected_issuer or None,
        "matchedIssuerSealCount": sum(1 for item in seals if item.get("matchesExpectedIssuer")),
        "seals": seals[:20],
    }


def extract_structured_fields(
    state: dict[str, Any],
    arguments: dict[str, Any],
    *,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    parse_results = selected_parse_results(state, arguments, context=context)
    material_type = str(
        arguments.get("materialTypeCode") or arguments.get("documentType") or ""
    ).strip()
    should_extract_welder = material_type in {"", "welder_certificate"} or any(
        str(result.get("documentType") or "") == "welder_certificate"
        for result in parse_results
    )
    welder_results = []
    if should_extract_welder:
        for result in parse_results:
            extraction = extract_welder_certificate_from_ocr_result(result)
            if extraction_has_content(extraction):
                welder_results.append(
                    {
                        "documentVersionId": result.get("documentVersionId"),
                        "parseResultId": result.get("parseResultId") or result.get("id"),
                        **extraction,
                    }
                )
    return {
        "toolCallId": runtime_tool_call_id(),
        "toolName": "extract_structured_fields",
        "status": "succeeded",
        "materialTypeCode": material_type or None,
        "welderCertificateCount": len(welder_results),
        "welderCertificates": welder_results,
    }


def verify_license_or_certificate(
    state: dict[str, Any],
    arguments: dict[str, Any],
    *,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    structured = extract_structured_fields(state, arguments, context=context)
    verifications = []
    for certificate in structured.get("welderCertificates") or []:
        issuer = field_value(certificate, "issuingAuthority")
        seals = recognize_document_seals(
            state,
            {
                "documentVersionIds": [certificate.get("documentVersionId")],
                "expectedIssuer": issuer,
            },
            context=context,
        )
        signals = certificate.get("verificationSignals") or {}
        risks = certificate_risks(signals, seals)
        verifications.append(
            {
                "verificationId": f"VCERT-{uuid4().hex[:8].upper()}",
                "documentVersionId": certificate.get("documentVersionId"),
                "certificateType": "welder_certificate",
                "certificateNo": field_value(certificate, "certificateNo"),
                "archiveNo": field_value(certificate, "archiveNo"),
                "issuingAuthority": issuer,
                "qualifiedItemCount": signals.get("qualifiedItemCount", 0),
                "expiredQualifiedItemCount": signals.get("expiredQualifiedItemCount", 0),
                "sealCount": seals.get("sealCount", 0),
                "matchedIssuerSealCount": seals.get("matchedIssuerSealCount", 0),
                "requiresManualAuthenticityCheck": bool(risks),
                "riskFlags": risks,
            }
        )
    return {
        "toolCallId": runtime_tool_call_id(),
        "toolName": "verify_license_or_certificate",
        "status": "succeeded",
        "verificationCount": len(verifications),
        "verifications": verifications,
    }


def selected_parse_results(
    state: dict[str, Any],
    arguments: dict[str, Any],
    *,
    context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    context = context or {}
    requested = {
        str(item)
        for item in arguments.get("documentVersionIds")
        or context.get("documentVersionIds")
        or context.get("inputDocumentVersionIds")
        or []
        if item
    }
    if not requested and context.get("reviewRun"):
        requested = {
            str(item)
            for item in context["reviewRun"].get("inputDocumentVersionIds") or []
            if item
        }
    results = [item for item in state.get("ocr_parse_results", []) if isinstance(item, dict)]
    if requested:
        results = [
            item
            for item in results
            if str(item.get("documentVersionId") or "") in requested
        ]
    return results


def extraction_has_content(extraction: dict[str, Any]) -> bool:
    fields = extraction.get("fields") if isinstance(extraction, dict) else {}
    rows = extraction.get("qualifiedItems") if isinstance(extraction, dict) else []
    return any(
        isinstance(item, dict) and item.get("value")
        for item in (fields or {}).values()
    ) or bool(rows)


def issuer_matches_seal(expected_issuer: str, seal: dict[str, Any]) -> bool:
    if not expected_issuer:
        return False
    seal_text = str(seal.get("sealText") or seal.get("sealName") or "")
    return bool(seal_text and (expected_issuer in seal_text or seal_text in expected_issuer))


def field_value(certificate: dict[str, Any], public_key: str) -> str | None:
    fields = certificate.get("fields") if isinstance(certificate, dict) else {}
    item = fields.get(public_key) if isinstance(fields, dict) else None
    if isinstance(item, dict) and item.get("value"):
        return str(item["value"])
    return None


def certificate_risks(signals: dict[str, Any], seals: dict[str, Any]) -> list[str]:
    risks = []
    for field in signals.get("missingCoreFields") or []:
        risks.append(f"missing_{field}")
    if int(signals.get("expiredQualifiedItemCount") or 0) > 0:
        risks.append("qualified_item_expired")
    if int(seals.get("sealCount") or 0) <= 0:
        risks.append("issuer_seal_missing")
    elif int(seals.get("matchedIssuerSealCount") or 0) <= 0:
        risks.append("issuer_seal_not_matched")
    return risks


def dict_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def runtime_tool_call_id() -> str:
    suffix = datetime.now(timezone.utc).strftime("%H%M%S")
    return f"RTOOL-{uuid4().hex[:8].upper()}-{suffix}"
