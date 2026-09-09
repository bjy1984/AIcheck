from __future__ import annotations

import hashlib
import os
import re
from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import uuid4

from libs.integrations.cnse_client import (
    CnseConfigurationError,
    CnseProtocolError,
    CnseRecognitionError,
    CnseRequestError,
    normalize_id_number,
    normalize_keyword,
)
from libs.integrations.external_registry_queries import (
    query_cnse_organizations,
    query_cnse_persons,
    query_standard_search,
    query_standard_status,
)
from libs.integrations.std_samr_client import (
    StdSamrConfigurationError,
    StdSamrProtocolError,
    StdSamrRequestError,
    normalize_standard_ref,
    parse_review_date,
)
from libs.ocr.welder_certificate_tool import extract_welder_certificate_from_ocr_result
from libs.review_orchestrator.deterministic_tools import (
    DETERMINISTIC_TOOL_DESCRIPTORS,
    DETERMINISTIC_TOOL_NAMES,
    business_today,
    dispatch_deterministic_tool,
    normalize_roman,
    parse_date,
)
from libs.review_tools import BUSINESS_TOOL_DESCRIPTORS, BUSINESS_TOOL_NAMES, dispatch_business_tool
from libs.review_workstations import workstation_argument_scope_error

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
            "输入身份证号，返回该人员全部公示证书（licenses）、其中的焊工项目与现行项目，"
            "以及平台首条记录；有效期按到期日计算，不依赖平台 validFlag。"
        ),
        "inputSchema": {"idNumber": "string"},
    },
    {
        "name": "verify_org_license",
        "capability": (
            "按单位名称查全国特种设备公示信息平台，输出该单位的登记状态（有效期、发证机关）；"
            "有许可明细时比对许可证编号，输出 verified_match / verified_mismatch / not_found / unable_to_verify。"
        ),
        "inputSchema": {"name": "string", "expectedLicenseNo": "string?"},
    },
    {
        "name": "verify_welder_on_platform",
        "capability": (
            "把焊工证或焊工名册上的项目代号与全国特种设备公示信息平台的全部焊工证书逐项比对，"
            "输出 consistent / mismatch / not_returned / platform_error，并按施焊日期判断证书是否现行。"
        ),
        "inputSchema": {
            "idNumber": "string",
            "expectedItems": ["string"],
            "workDate": "string?",
            "holderName": "string?",
        },
    },
    {
        "name": "lookup_standard_status",
        "capability": (
            "查询全国标准信息公共服务平台（std.samr.gov.cn）的标准版本状态、"
            "实施日期、废止日期和替代关系；用于核验引用标准是否现行有效。"
        ),
        "inputSchema": {"standardRef": "string", "reviewDate": "string?"},
    },
    {
        "name": "search_samr_standards",
        "capability": (
            "在全国标准信息公共服务平台按关键词检索标准条目，"
            "返回标准号、名称、状态和详情链接。"
        ),
        "inputSchema": {"query": "string", "page": "integer?"},
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
    if scope_error := workstation_argument_scope_error(context.get("reviewRun") or {}, args):
        return {"toolCallId": runtime_tool_call_id(), "toolName": tool_name,
                "status": "rejected", "errorCode": scope_error}
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
    if tool_name == "verify_welder_on_platform":
        return verify_welder_on_platform_tool(args)
    if tool_name == "verify_org_license":
        return verify_org_license_tool(args)
    if tool_name == "lookup_standard_status":
        return lookup_standard_status_tool(args)
    if tool_name == "search_samr_standards":
        return search_samr_standards_tool(args)
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
    detection = seal_detection_capability()
    payload = {
        "toolCallId": runtime_tool_call_id(),
        "toolName": "recognize_document_seals",
        "status": "succeeded",
        "sealCount": len(seals),
        "expectedIssuer": expected_issuer or None,
        "matchedIssuerSealCount": sum(1 for item in seals if item.get("matchesExpectedIssuer")),
        "seals": seals[:20],
        "detectionEnabled": detection["enabled"],
        "detectionPipelines": detection["pipelines"],
    }
    # 印章是监检判定的关键证据。检测管线全部关闭时找不到印章，说明的是「没查」而不是
    # 「没有」，必须让下游能区分——否则会把未检测直接当成缺章判不符合。
    if not detection["enabled"] and not seals:
        payload["status"] = "capability_disabled"
        payload["sealCount"] = None
        payload["warnings"] = [
            "seal_detection_disabled:未启用任何印章检测管线，本结果不能作为「无印章」的依据。"
        ]
    return payload


def seal_detection_capability() -> dict[str, Any]:
    """当前启用了哪些印章检测管线。"""
    pipelines = {
        "paddlex": env_flag("AICHECK_ENABLE_PADDLEX_SEAL_PIPELINE"),
        "agentdesign": env_flag("AICHECK_ENABLE_AGENTDESIGN_SEAL_OCR"),
    }
    return {"enabled": any(pipelines.values()), "pipelines": pipelines}


def env_flag(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() == "true"


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
        # 印章检测未启用时向上透传，避免把「没查印章」当成「没有印章」。
        "status": seal_result["status"],
        "signatureCount": len(signatures),
        "sealCount": seal_result["sealCount"],
        "matchedIssuerSealCount": seal_result["matchedIssuerSealCount"],
        "signatures": signatures[:40],
        "seals": seal_result["seals"],
        "detectionEnabled": seal_result["detectionEnabled"],
        "detectionPipelines": seal_result["detectionPipelines"],
        **({"warnings": seal_result["warnings"]} if seal_result.get("warnings") else {}),
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
    review_run = context.get("reviewRun")
    if review_run is not None:
        allowed = {str(item) for item in review_run.get("inputDocumentVersionIds") or [] if item}
        requested = requested & allowed if requested else allowed
    results = [item for item in state.get("ocr_parse_results", []) if isinstance(item, dict)]
    if requested or review_run is not None:
        results = [item for item in results if str(item.get("documentVersionId") or "") in requested]
    return apply_field_corrections_to_parse_results(state, results, context=context)


def apply_field_corrections_to_parse_results(
    state: dict[str, Any],
    results: list[dict[str, Any]],
    *,
    context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """把监检人员对 OCR 抽取字段的修正覆盖到解析结果上。

    修正记录在 `fact_corrections` 中以 fieldId 为键；这里按 fieldName 匹配解析结果里的
    字段，使所有读 OCR 的确定性工具都看到修正后的值。仅对本项目本节点生效，
    不跨节点传播（业务口径：节点独立）。返回副本，不改动持久化状态。
    """
    review_run = (context or {}).get("reviewRun") or {}
    project_id = str(review_run.get("projectId") or "")
    node_id = review_run.get("nodeId")
    if not project_id or node_id is None:
        return results
    corrections = [
        item
        for item in state.get("fact_corrections", []) or []
        if item.get("status") == "active"
        and item.get("fieldId")
        and item.get("projectId") == project_id
        and int(item.get("nodeId") or 0) == int(node_id)
    ]
    if not corrections:
        return results

    by_version: dict[str, dict[str, Any]] = {}
    for item in corrections:
        by_version.setdefault(str(item.get("documentVersionId") or ""), {})[
            str(item.get("fieldName") or "")
        ] = item

    patched: list[dict[str, Any]] = []
    for result in results:
        overrides = by_version.get(str(result.get("documentVersionId") or "")) or {}
        if not overrides:
            patched.append(result)
            continue
        clone = deepcopy(result)
        for field in clone.get("fields") or []:
            if not isinstance(field, dict):
                continue
            correction = overrides.get(str(field.get("fieldName") or field.get("name") or ""))
            if not correction:
                continue
            field["originalValue"] = field.get("value") if "value" in field else field.get("fieldValue")
            for key in ("value", "fieldValue", "text"):
                if key in field:
                    field[key] = correction.get("correctedValue")
            field["humanCorrected"] = True
            field["correctionId"] = correction.get("id")
        clone["humanCorrectedFieldCount"] = sum(
            1 for f in clone.get("fields") or [] if isinstance(f, dict) and f.get("humanCorrected")
        )
        patched.append(clone)
    return patched


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
    suffix = datetime.now(UTC).strftime("%H%M%S")
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
    licenses = [item for item in (result.get("licenses") or []) if isinstance(item, dict)]
    lookup = result.get("licenseLookup") if isinstance(result.get("licenseLookup"), dict) else {}
    reference = parse_date(arguments.get("referenceDate")) or business_today()
    welder_licenses = [item for item in licenses if _is_welder_license(item)]
    current_welder = [item for item in welder_licenses if _license_is_current(item, reference)]
    if lookup.get("status") == "completed":
        summary = (
            f"公示平台返回 {len(licenses)} 条证书，其中焊工项目 {len(welder_licenses)} 条、"
            f"截至 {reference.isoformat()} 现行 {len(current_welder)} 条；最终登记状态以公示平台结果为准。"
        )
    else:
        summary = (
            "公示平台只返回首条记录，全部证书列表未取到（"
            f"{lookup.get('status') or 'not_attempted'}）；未返回焊接项目不能判为无证，需人工到平台复核。"
        )
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
        "licenses": licenses,
        "licenseLookup": lookup,
        "welderLicenses": welder_licenses,
        "currentWelderLicenses": current_welder,
        "referenceDate": reference.isoformat(),
        "requiresHumanConfirmation": True,
        "summary": summary,
    }


_WELDER_CODE_RE = re.compile(r"\b(SMAW|GTAW|GMAW|FCAW|SAW|PAW|OFW|ESW|EGW|SW|LBW|EBW|TIG|MIG|MAG)\b", re.IGNORECASE)


def _is_welder_license(item: dict[str, Any]) -> bool:
    text = " ".join(str(item.get(key) or "") for key in ("czxm", "cyzl", "zslb"))
    return bool(_WELDER_CODE_RE.search(text)) or "焊" in text


def _platform_date(value: Any, *, month_end: bool = False) -> date | None:
    """平台日期有三种写法：2029-04-30、2025-05（老证只到月）、2025年05月至2029年04月（取后一段）。"""
    text = str(value or "").strip()
    if "至" in text:
        text = text.split("至")[-1].strip()
    parsed = parse_date(text)
    if parsed is not None:
        return parsed
    match = re.fullmatch(r"(\d{4})[-/.年](\d{1,2})月?", text)
    if not match:
        return None
    year, month = int(match.group(1)), int(match.group(2))
    if not 1 <= month <= 12:
        return None
    if not month_end:
        return date(year, month, 1)
    next_month = date(year + (month // 12), (month % 12) + 1, 1)
    return next_month - timedelta(days=1)


def _license_is_current(item: dict[str, Any], reference: date) -> bool:
    """现行 = 到期日不早于参考日；平台 validFlag 对已到期记录仍为 1，不能用。"""
    valid_until = _platform_date(item.get("yxrqz") or item.get("yxrq"), month_end=True)
    if valid_until is None:
        return False
    valid_from = _platform_date(item.get("yxrqs"))
    if valid_from is not None and valid_from > reference:
        return False
    return valid_until >= reference


def _normalize_welder_item(code: str) -> str:
    text = normalize_roman(str(code or ""))
    text = text.translate(str.maketrans("／－（）", "/-()"))
    return re.sub(r"\s+", "", text).upper()


def _split_welder_items(code: str) -> list[str]:
    parts = re.split(r"[和、;；,，]|\band\b", str(code or ""))
    return [_normalize_welder_item(part) for part in parts if part and part.strip()]


def verify_org_license_tool(arguments: dict[str, Any]) -> dict[str, Any]:
    """P10 N-19：制造/安装单位许可在公示平台的核实，结果与 R12 人工核验记录同形。"""
    from libs.review_orchestrator.r12_registry import auto_verify_candidates

    tool_name = "verify_org_license"
    name = str(arguments.get("name") or arguments.get("organizationName") or "").strip()
    if not name:
        return _cnse_tool_failure(tool_name, error_code="VALIDATION_ERROR", message="请输入单位名称。")
    candidate = {
        "candidateId": str(arguments.get("candidateId") or "ORG-" + hashlib.sha256(f"{name}|{arguments.get('expectedLicenseNo') or ''}".encode()).hexdigest()[:12].upper()),
        "organizationName": name,
        "licenseNo": str(arguments.get("expectedLicenseNo") or arguments.get("licenseNo") or ""),
    }
    verification = (auto_verify_candidates([candidate]) or [{}])[0]
    outcome = str(verification.get("outcome") or "unable_to_verify")
    return {
        "toolCallId": runtime_tool_call_id(),
        "toolName": tool_name,
        "status": "succeeded" if not verification.get("platformError") else "failed",
        "outcome": outcome,
        "verification": verification,
        "requiresHumanConfirmation": outcome != "verified_match",
        "summary": {
            "verified_match": "平台登记的许可证编号与证书一致。",
            "verified_mismatch": "平台登记的许可证编号与证书不一致，需人工核对。",
            "not_found": "公示平台按单位名称未查到该单位，需人工核对单位名称与平台。",
        }.get(outcome, "平台已返回单位登记状态，许可证编号与范围需人工核对。"),
    }


def verify_welder_on_platform_tool(arguments: dict[str, Any]) -> dict[str, Any]:
    """三方比对的平台一侧：证书/名册项目代号 vs 平台全部焊工证书。

    结论只有四种：consistent（每个期望项目都在平台现行证书里）、mismatch（平台有焊工证但
    期望项目不在其中或已到期）、not_returned（平台没有返回任何焊工证书，或全表没取到）、
    platform_error（平台不可用）。not_returned 与 platform_error 都不是"证书为假"，
    规则层只能据此输出需人工确认。
    """
    tool_name = "verify_welder_on_platform"
    base = search_cnse_persons_tool({"idNumber": arguments.get("idNumber"), "referenceDate": arguments.get("workDate")})
    if base.get("status") != "succeeded":
        return {
            **base,
            "toolName": tool_name,
            "status": "succeeded",
            "verdict": "platform_error",
            "matchedItems": [],
            "missingItems": [],
            "requiresHumanConfirmation": True,
            "summary": f"公示平台查询失败（{base.get('errorCode')}），无法比对，需人工到平台复核。",
        }
    expected_raw = arguments.get("expectedItems") or []
    if isinstance(expected_raw, str):
        expected_raw = [expected_raw]
    expected: list[str] = []
    for item in expected_raw:
        expected.extend(_split_welder_items(str(item)))
    expected = list(dict.fromkeys(item for item in expected if item))
    reference = parse_date(arguments.get("workDate")) or business_today()
    platform_items: dict[str, dict[str, Any]] = {}
    for lic in base.get("welderLicenses") or []:
        for code in _split_welder_items(str(lic.get("czxm") or "")):
            record = platform_items.setdefault(code, {"code": code, "current": False, "licenses": []})
            record["licenses"].append({
                "certificateNo": lic.get("zsbh"),
                "issuer": lic.get("fzjg"),
                "validFrom": lic.get("yxrqs"),
                "validUntil": lic.get("yxrqz") or lic.get("yxrq"),
                "employer": lic.get("khdw"),
            })
            if _license_is_current(lic, reference):
                record["current"] = True
    matched = [code for code in expected if code in platform_items and platform_items[code]["current"]]
    expired = [code for code in expected if code in platform_items and not platform_items[code]["current"]]
    missing = [code for code in expected if code not in platform_items]
    holder = str(arguments.get("holderName") or "").strip()
    platform_name = str(base.get("personName") or "").strip()
    name_matches = (not holder) or (holder == platform_name)
    lookup_status = (base.get("licenseLookup") or {}).get("status")
    if lookup_status != "completed" and not platform_items or not platform_items:
        verdict = "not_returned"
    elif expected and not missing and not expired and name_matches:
        verdict = "consistent"
    elif not expected:
        verdict = "consistent" if name_matches else "mismatch"
    else:
        verdict = "mismatch"
    summary_bits = [f"平台焊工证书 {len(platform_items)} 项（现行 {sum(1 for r in platform_items.values() if r['current'])} 项）"]
    if matched:
        summary_bits.append(f"一致 {len(matched)} 项")
    if expired:
        summary_bits.append(f"已到期 {len(expired)} 项")
    if missing:
        summary_bits.append(f"平台未见 {len(missing)} 项")
    if not name_matches:
        summary_bits.append(f"姓名不一致（证书 {holder} / 平台 {platform_name}）")
    if lookup_status != "completed":
        summary_bits.append("全表未取到，只比对了首条记录")
    return {
        "toolCallId": runtime_tool_call_id(),
        "toolName": tool_name,
        "status": "succeeded",
        "verdict": verdict,
        "referenceDate": reference.isoformat(),
        "expectedItems": expected,
        "matchedItems": matched,
        "expiredItems": expired,
        "missingItems": missing,
        "platformItems": list(platform_items.values()),
        "personName": platform_name,
        "holderName": holder or None,
        "nameMatches": name_matches,
        "licenseLookup": base.get("licenseLookup"),
        "licenseCount": len(base.get("licenses") or []),
        "requiresHumanConfirmation": verdict != "consistent",
        "summary": "；".join(summary_bits) + "。平台记录作为证据保留，最终以平台原始页面为准。",
    }


def lookup_standard_status_tool(arguments: dict[str, Any]) -> dict[str, Any]:
    tool_name = "lookup_standard_status"
    try:
        normalize_standard_ref(str(arguments.get("standardRef") or ""))
        review_date = parse_review_date(arguments.get("reviewDate"))
        standard_ref = str(arguments.get("standardRef") or "").strip()
    except StdSamrConfigurationError as exc:
        message = str(exc) if "reviewDate" in str(exc) else "请输入有效的标准编号。"
        return _cnse_tool_failure(
            tool_name,
            error_code="VALIDATION_ERROR",
            message=message,
        )
    try:
        result = query_standard_status(standard_ref, review_date)
    except StdSamrConfigurationError:
        return _cnse_tool_failure(
            tool_name,
            error_code="STD_SAMR_SERVICE_MISCONFIGURED",
            message="全国标准信息公共服务平台查询服务配置无效。",
        )
    except (StdSamrRequestError, StdSamrProtocolError):
        return _cnse_tool_failure(
            tool_name,
            error_code="STD_SAMR_UPSTREAM_FAILED",
            message="全国标准信息公共服务平台暂不可用，请稍后重试。",
        )
    references = result.get("standardReferences") if isinstance(result.get("standardReferences"), list) else []
    verdict = str(result.get("verdict") or "")
    summary_map = {
        "current": "官方平台显示该标准版本现行有效。",
        "superseded": "官方平台显示该标准版本已废止或被代替，请改用现行执行标准。",
        "not_yet_effective": "官方平台显示该标准版本尚未实施。",
        "ambiguous": "官方平台返回多条结果，需人工确认版本。",
        "not_found": "官方平台未检索到该标准编号，可能未收录（如 TSG）或编号有误。",
    }
    return {
        "toolCallId": runtime_tool_call_id(),
        "toolName": tool_name,
        "status": "succeeded",
        "result": result,
        "citedRef": result.get("citedRef"),
        "canonicalRef": result.get("canonicalRef"),
        "verdict": verdict,
        "standardReferences": references,
        "matched": result.get("matched"),
        "currentExecution": result.get("currentExecution"),
        "requiresHumanConfirmation": True,
        "summary": summary_map.get(verdict, "已查询全国标准信息公共服务平台版本状态。"),
    }


def search_samr_standards_tool(arguments: dict[str, Any]) -> dict[str, Any]:
    tool_name = "search_samr_standards"
    try:
        from libs.integrations.std_samr_client import normalize_query

        query = normalize_query(str(arguments.get("query") or ""))
        page_raw = arguments.get("page", 1)
        page = int(page_raw) if page_raw is not None else 1
        if isinstance(page, bool) or not 1 <= page <= 100_000:
            raise StdSamrConfigurationError("page must be a positive integer")
    except StdSamrConfigurationError as exc:
        message = str(exc) if "page" in str(exc) else "请输入有效的检索关键词。"
        return _cnse_tool_failure(
            tool_name,
            error_code="VALIDATION_ERROR",
            message=message,
        )
    try:
        result = query_standard_search(query, page=page)
    except StdSamrConfigurationError:
        return _cnse_tool_failure(
            tool_name,
            error_code="STD_SAMR_SERVICE_MISCONFIGURED",
            message="全国标准信息公共服务平台查询服务配置无效。",
        )
    except (StdSamrRequestError, StdSamrProtocolError):
        return _cnse_tool_failure(
            tool_name,
            error_code="STD_SAMR_UPSTREAM_FAILED",
            message="全国标准信息公共服务平台暂不可用，请稍后重试。",
        )
    rows = result.get("rows") if isinstance(result.get("rows"), list) else []
    return {
        "toolCallId": runtime_tool_call_id(),
        "toolName": tool_name,
        "status": "succeeded",
        "result": result,
        "query": result.get("query"),
        "total": result.get("total"),
        "rowCount": len(rows),
        "rows": rows[:10],
        "requiresHumanConfirmation": True,
        "summary": "已检索全国标准信息公共服务平台，最终版本状态以官方详情为准。",
    }
