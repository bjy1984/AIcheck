from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from apps.ocr_service.welder_certificate_tool import extract_welder_certificate_from_ocr_result
from apps.api.cnse_routes import query_cnse_organizations, query_cnse_persons
from libs.integrations.cnse_client import (
    CnseConfigurationError,
    CnseProtocolError,
    CnseRecognitionError,
    CnseRequestError,
    normalize_id_number,
    normalize_keyword,
)
from libs.review_orchestrator.deterministic_tools import (
    DETERMINISTIC_TOOL_DESCRIPTORS,
    DETERMINISTIC_TOOL_NAMES,
    dispatch_deterministic_tool,
)
from libs.review_tools import BUSINESS_TOOL_DESCRIPTORS, BUSINESS_TOOL_NAMES, dispatch_business_tool


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
        "name": "recognize_signatures_and_seals",
        "capability": "读取文档中的签字、签章、印章文字、位置和置信度。",
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
        "name": "extract_document_fields",
        "capability": "读取指定文档版本的已解析结构化字段，并保留页码、坐标和置信度。",
        "inputSchema": {"documentVersionIds": ["string"], "fieldCodes": ["string?"]},
    },
    {
        "name": "extract_table_records",
        "capability": "读取指定文档版本的表格及标准化行记录。",
        "inputSchema": {"documentVersionIds": ["string"], "businessSchemas": ["string?"]},
    },
    {
        "name": "locate_evidence_fragment",
        "capability": "按查询词定位字段或原文片段，生成带文件版本、页码、坐标和置信度的证据引用。",
        "inputSchema": {"documentVersionIds": ["string"], "queryTerms": ["string"], "minConfidence": "number?"},
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
    {
        "name": "search_cnse_organizations",
        "capability": (
            "查询全国特种设备公示信息平台的单位许可信息。"
            "输入单位名称，返回公示登记记录、许可项目、发证机关和有效期。"
        ),
        "inputSchema": {"keyword": "string"},
    },
    {
        "name": "search_cnse_persons",
        "capability": (
            "查询全国特种设备公示信息平台的从业人员资格信息。"
            "输入身份证号，返回姓名、作业项目、发证机关和有效期等公示记录。"
        ),
        "inputSchema": {"idNumber": "string"},
    },
] + DETERMINISTIC_TOOL_DESCRIPTORS + BUSINESS_TOOL_DESCRIPTORS


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
    if tool_name in DETERMINISTIC_TOOL_NAMES:
        result = dispatch_deterministic_tool(tool_name, args)
        result["toolCallId"] = runtime_tool_call_id()
        return result
    if tool_name in BUSINESS_TOOL_NAMES:
        result = dispatch_business_tool(tool_name, args)
        result["toolCallId"] = runtime_tool_call_id()
        return result
    if tool_name == "get_document_ocr_result":
        return get_document_ocr_result(state, args, context=context)
    if tool_name == "recognize_document_seals":
        return recognize_document_seals(state, args, context=context)
    if tool_name == "recognize_signatures_and_seals":
        return recognize_signatures_and_seals(state, args, context=context)
    if tool_name == "extract_document_fields":
        return extract_document_fields(state, args, context=context)
    if tool_name == "extract_table_records":
        return extract_table_records(state, args, context=context)
    if tool_name == "locate_evidence_fragment":
        return locate_evidence_fragment(state, args, context=context)
    if tool_name in {"extract_structured_fields", "extract_welder_certificate"}:
        result = extract_structured_fields(state, args, context=context)
        result["toolName"] = tool_name
        return result
    if tool_name in {"verify_license_or_certificate", "verify_welder_certificate_authenticity"}:
        result = verify_license_or_certificate(state, args, context=context)
        result["toolName"] = tool_name
        return result
    if tool_name == "search_cnse_organizations":
        return search_cnse_organizations_tool(args)
    if tool_name == "search_cnse_persons":
        return search_cnse_persons_tool(args)
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


def recognize_signatures_and_seals(
    state: dict[str, Any],
    arguments: dict[str, Any],
    *,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    parse_results = selected_parse_results(state, arguments, context=context)
    seal_result = recognize_document_seals(state, arguments, context=context)
    signatures = []
    for parse_result in parse_results:
        for signature in dict_items(parse_result.get("signatures")):
            signatures.append(
                {
                    "documentVersionId": parse_result.get("documentVersionId"),
                    "signatureId": signature.get("signatureId") or signature.get("id"),
                    "role": signature.get("role") or signature.get("signatureRole"),
                    "signerName": signature.get("signerName") or signature.get("name"),
                    "pageNo": signature.get("pageNo") or 1,
                    "bbox": signature.get("bbox") or signature.get("polygon"),
                    "confidence": signature.get("confidence") or signature.get("visualConfidence"),
                }
            )
    return {
        "toolCallId": runtime_tool_call_id(),
        "toolName": "recognize_signatures_and_seals",
        "status": "succeeded",
        "signatureCount": len(signatures),
        "sealCount": seal_result["sealCount"],
        "matchedIssuerSealCount": seal_result["matchedIssuerSealCount"],
        "signatures": signatures[:40],
        "seals": seal_result["seals"],
    }


def extract_document_fields(
    state: dict[str, Any],
    arguments: dict[str, Any],
    *,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    parse_results = selected_parse_results(state, arguments, context=context)
    requested = {str(item) for item in arguments.get("fieldCodes") or [] if item}
    fields = []
    for parse_result in parse_results:
        for field in dict_items(parse_result.get("fields")):
            field_code = str(field.get("fieldCode") or field.get("code") or field.get("name") or "")
            if requested and field_code not in requested:
                continue
            fields.append({"documentVersionId": parse_result.get("documentVersionId"), **field})
    return {
        "toolCallId": runtime_tool_call_id(),
        "toolName": "extract_document_fields",
        "status": "succeeded",
        "fieldCount": len(fields),
        "fields": fields[:200],
    }


def extract_table_records(
    state: dict[str, Any],
    arguments: dict[str, Any],
    *,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    parse_results = selected_parse_results(state, arguments, context=context)
    requested = {str(item) for item in arguments.get("businessSchemas") or [] if item}
    tables = []
    for parse_result in parse_results:
        for table in dict_items(parse_result.get("tables")):
            schemas = {str(item) for item in table.get("businessSchemas") or [] if item}
            if table.get("businessSchema"):
                schemas.add(str(table["businessSchema"]))
            if requested and not requested.intersection(schemas):
                continue
            tables.append({"documentVersionId": parse_result.get("documentVersionId"), **table})
    return {
        "toolCallId": runtime_tool_call_id(),
        "toolName": "extract_table_records",
        "status": "succeeded",
        "tableCount": len(tables),
        "tables": tables[:80],
    }


def locate_evidence_fragment(
    state: dict[str, Any],
    arguments: dict[str, Any],
    *,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    parse_results = selected_parse_results(state, arguments, context=context)
    query_terms = [str(item).strip().lower() for item in arguments.get("queryTerms") or [] if str(item).strip()]
    try:
        minimum = float(arguments.get("minConfidence", 0.0))
    except (TypeError, ValueError):
        minimum = 0.0
    refs = []
    for parse_result in parse_results:
        document_version_id = parse_result.get("documentVersionId")
        candidates = [*dict_items(parse_result.get("fields")), *dict_items(parse_result.get("fragments"))]
        for candidate in candidates:
            quoted_text = str(
                candidate.get("quotedText")
                or candidate.get("text")
                or candidate.get("fieldValue")
                or candidate.get("value")
                or ""
            ).strip()
            confidence = candidate.get("confidence") or candidate.get("ocrConfidence") or 0.0
            try:
                numeric_confidence = float(confidence)
            except (TypeError, ValueError):
                numeric_confidence = 0.0
            if numeric_confidence < minimum:
                continue
            if query_terms and not any(term in quoted_text.lower() for term in query_terms):
                continue
            refs.append(
                {
                    "evidenceRefId": f"EVR-{uuid4().hex[:10].upper()}",
                    "documentVersionId": document_version_id,
                    "pageNo": candidate.get("pageNo") or 1,
                    "bbox": candidate.get("bbox") or candidate.get("polygon"),
                    "quotedText": quoted_text,
                    "confidence": numeric_confidence,
                }
            )
    return {
        "toolCallId": runtime_tool_call_id(),
        "toolName": "locate_evidence_fragment",
        "status": "succeeded",
        "evidenceRefCount": len(refs),
        "evidenceRefs": refs[:200],
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


def _cnse_tool_failure(
    tool_name: str,
    *,
    error_code: str,
    message: str,
) -> dict[str, Any]:
    return {
        "toolCallId": runtime_tool_call_id(),
        "toolName": tool_name,
        "status": "failed",
        "errorCode": error_code,
        "message": message,
    }


def search_cnse_organizations_tool(arguments: dict[str, Any]) -> dict[str, Any]:
    tool_name = "search_cnse_organizations"
    try:
        keyword = normalize_keyword(str(arguments.get("keyword") or ""))
    except CnseConfigurationError:
        return _cnse_tool_failure(
            tool_name,
            error_code="VALIDATION_ERROR",
            message="请输入有效的单位名称。",
        )
    try:
        result = query_cnse_organizations(keyword)
    except CnseConfigurationError:
        return _cnse_tool_failure(
            tool_name,
            error_code="CNSE_SERVICE_MISCONFIGURED",
            message="全国特种设备公示信息查询服务配置无效。",
        )
    except CnseRecognitionError:
        return _cnse_tool_failure(
            tool_name,
            error_code="CNSE_RECOGNITION_FAILED",
            message="全国特种设备公示信息查询平台验证码识别失败，请重试。",
        )
    except (CnseRequestError, CnseProtocolError):
        return _cnse_tool_failure(
            tool_name,
            error_code="CNSE_UPSTREAM_FAILED",
            message="全国特种设备公示信息查询平台暂不可用，请稍后重试。",
        )
    rows = result.get("rows") if isinstance(result.get("rows"), list) else []
    return {
        "toolCallId": runtime_tool_call_id(),
        "toolName": tool_name,
        "status": "succeeded",
        "result": result,
        "keyword": result.get("keyword"),
        "total": result.get("total"),
        "rowCount": len(rows),
        "rows": rows[:10],
        "requiresHumanConfirmation": True,
        "summary": "已查询全国特种设备公示单位信息，最终登记状态以公示平台结果为准。",
    }


def search_cnse_persons_tool(arguments: dict[str, Any]) -> dict[str, Any]:
    tool_name = "search_cnse_persons"
    try:
        id_number = normalize_id_number(str(arguments.get("idNumber") or ""))
    except CnseConfigurationError:
        return _cnse_tool_failure(
            tool_name,
            error_code="VALIDATION_ERROR",
            message="请输入有效的身份证号。",
        )
    try:
        result = query_cnse_persons(id_number)
    except CnseConfigurationError:
        return _cnse_tool_failure(
            tool_name,
            error_code="CNSE_SERVICE_MISCONFIGURED",
            message="全国特种设备公示信息查询服务配置无效。",
        )
    except CnseRecognitionError:
        return _cnse_tool_failure(
            tool_name,
            error_code="CNSE_RECOGNITION_FAILED",
            message="全国特种设备公示信息查询平台验证码识别失败，请重试。",
        )
    except (CnseRequestError, CnseProtocolError):
        return _cnse_tool_failure(
            tool_name,
            error_code="CNSE_UPSTREAM_FAILED",
            message="全国特种设备公示信息查询平台暂不可用，请稍后重试。",
        )
    person = result.get("person") if isinstance(result.get("person"), dict) else {}
    return {
        "toolCallId": runtime_tool_call_id(),
        "toolName": tool_name,
        "status": "succeeded",
        "result": result,
        "idNumber": result.get("idNumber"),
        "personName": person.get("ryxm"),
        "issuer": person.get("fzjg"),
        "qualifiedItems": person.get("czxm"),
        "validUntil": person.get("yxrqz") or person.get("yxrq"),
        "person": person,
        "requiresHumanConfirmation": True,
        "summary": "已查询全国特种设备公示从业人员资格信息，最终登记状态以公示平台结果为准。",
    }
