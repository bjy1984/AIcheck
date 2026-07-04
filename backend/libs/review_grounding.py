from __future__ import annotations

import re
from typing import Any


POSITIVE_CLAIM_RE = re.compile(r"(满足|符合|匹配|覆盖|一致|有效|真实|通过|已确认|具备|齐全|完整)")
CODE_TOKEN_RE = re.compile(r"\b(?:[A-Z]{1,8}[A-Z0-9]*[-/][A-Z0-9][A-Z0-9./-]{2,}|[A-Z]{1,8}\d{4,}[A-Z0-9./-]*)\b", re.IGNORECASE)
DATE_TOKEN_RE = re.compile(r"\d{4}\s*(?:[-/.年]\s*\d{1,2})?(?:[-/.月]\s*\d{1,2}\s*日?)?")
ORG_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]{2,}(?:有限公司|设计院|研究院|监督管理局|公司|单位)")
PERSON_TOKEN_RE = re.compile(r"(?:焊工|姓名|人员|审核|编制|校核|负责人|许可人员)\s*[:：]?\s*([\u4e00-\u9fff]{2,4})(?=证书|持证|有效|资格|,|，|。|\s|$)")

GROUNDING_TERMS = {
    "有效期",
    "持证项目",
    "焊接方法",
    "焊接工艺",
    "姓名",
    "单位",
    "许可证",
    "炉批号",
    "材料牌号",
    "规格",
    "材质",
    "检验结论",
}

STRICT_GROUNDING_REQUIREMENTS = [
    "Only use facts present in groundedOcrEvidence, evidenceLinkIds, ruleResults, and kbRefs.",
    "Do not infer names, dates, validity, project coverage, certificate authenticity, seal text, or table values that are not present in evidence.",
    "If evidence is missing or low confidence, set groundingStatus to insufficient_evidence and suggestedAction to human_confirm.",
    "Every finding must include evidenceRefs from supplied evidenceLinkIds or explicit page/bbox evidence.",
    "Return JSON only with findings, unsupportedClaims, and groundingStatus; no free-text answer.",
]


def build_grounded_review_input(state: dict[str, Any], document_version_ids: set[str] | list[str] | tuple[str, ...]) -> dict[str, Any]:
    version_ids = {str(item) for item in document_version_ids if item}
    fields = [
        _field_evidence(item)
        for item in state.get("extracted_fields", [])
        if str(item.get("documentVersionId") or "") in version_ids
    ]
    parse_results = [
        item
        for item in state.get("ocr_parse_results", [])
        if str(item.get("documentVersionId") or "") in version_ids
    ]
    tables = [_table_evidence(table, result) for result in parse_results for table in _dict_items(result.get("tables"))]
    seals = [_seal_evidence(seal, result) for result in parse_results for seal in _dict_items(result.get("seals"))]
    fragments = [
        _fragment_evidence(fragment, result)
        for result in parse_results
        for fragment in _dict_items(result.get("fragments"))
    ][:80]
    evidence_links = [
        _evidence_link(item)
        for item in state.get("evidence_links", [])
        if str(item.get("documentVersionId") or "") in version_ids
    ]
    quality = [
        {
            "parseResultId": result.get("parseResultId") or result.get("id"),
            "documentVersionId": result.get("documentVersionId"),
            "status": result.get("status"),
            "quality": result.get("quality") or {},
            "diagnostics": result.get("diagnostics") or [],
        }
        for result in parse_results
    ]
    low_confidence = [
        item
        for item in [*fields, *fragments]
        if _safe_float(item.get("confidence"), default=1.0) < 0.85
    ]
    missing_position = [
        item
        for item in [*fields, *tables, *seals, *fragments]
        if item.get("bbox") in {None, ""}
    ]
    evidence_texts = _evidence_texts(fields, tables, seals, fragments, evidence_links)
    grounding_status = "grounded" if evidence_texts and evidence_links else "insufficient_evidence"
    return {
        "schemaVersion": "EvidenceGroundedReviewInput@1.0.0",
        "documentVersionIds": sorted(version_ids),
        "groundingStatus": grounding_status,
        "fields": fields[:80],
        "tables": tables[:20],
        "seals": seals[:20],
        "fragments": fragments,
        "evidenceLinks": evidence_links[:80],
        "quality": quality,
        "evidenceTextCorpus": evidence_texts[:240],
        "summary": {
            "fieldCount": len(fields),
            "tableCount": len(tables),
            "sealCount": len(seals),
            "fragmentCount": len(fragments),
            "evidenceLinkCount": len(evidence_links),
            "lowConfidenceEvidenceCount": len(low_confidence),
            "missingPositionEvidenceCount": len(missing_position),
            "groundingStatus": grounding_status,
        },
        "reviewWarnings": _grounding_warnings(grounding_status, low_confidence, missing_position),
    }


def apply_grounding_guardrails(drafts: list[dict[str, Any]], grounding_input: dict[str, Any]) -> list[dict[str, Any]]:
    evidence_links = [item for item in grounding_input.get("evidenceLinks") or [] if isinstance(item, dict)]
    default_refs = [_evidence_ref(item) for item in evidence_links[:3]]
    evidence_texts = [str(item) for item in grounding_input.get("evidenceTextCorpus") or [] if str(item).strip()]
    input_status = str(grounding_input.get("groundingStatus") or "insufficient_evidence")
    guarded: list[dict[str, Any]] = []
    for draft in drafts or []:
        item = dict(draft)
        refs = item.get("evidenceRefs") if isinstance(item.get("evidenceRefs"), list) else []
        if not refs and default_refs:
            refs = default_refs
        item["evidenceRefs"] = refs
        item["evidenceLinkIds"] = [ref.get("evidenceLinkId") for ref in refs if isinstance(ref, dict) and ref.get("evidenceLinkId")]
        item["requiresHumanConfirmation"] = True
        if item.get("suggestedAction") not in {"human_confirm", "request_correction"}:
            item["suggestedAction"] = "human_confirm"
        unsupported = unsupported_claims(
            " ".join(str(item.get(key) or "") for key in ["title", "description"]),
            evidence_texts,
        )
        if unsupported or input_status != "grounded":
            item["unsupportedClaims"] = unsupported
            item["groundingStatus"] = "insufficient_evidence"
            item["suggestedAction"] = "human_confirm"
            item["confidence"] = min(_safe_float(item.get("confidence"), default=0.5), 0.5)
            item["title"] = "证据不足，需人工确认"
            item["description"] = "当前 OCR 证据不足以支撑模型输出的业务结论，已降级为待人工确认；请核对原件、OCR 文本、表格、印章和证据链。"
            item.setdefault("llmGroundingWarnings", []).append(
                {
                    "code": "UNSUPPORTED_LLM_CLAIM" if unsupported else "INSUFFICIENT_OCR_EVIDENCE",
                    "message": "LLM output was downgraded because supplied OCR evidence did not support a business conclusion.",
                }
            )
        else:
            item["groundingStatus"] = "grounded"
            item.setdefault("unsupportedClaims", [])
        guarded.append(item)
    return guarded


def unsupported_claims(text: str, evidence_texts: list[str]) -> list[dict[str, Any]]:
    if not POSITIVE_CLAIM_RE.search(text or ""):
        return []
    evidence = _normalized_text(" ".join(evidence_texts))
    claims: list[dict[str, Any]] = []
    for token in _claim_tokens(text):
        normalized = _normalized_text(token)
        if normalized and normalized not in evidence:
            claims.append({"claim": token, "reason": "not_present_in_supplied_evidence"})
    if not claims and not evidence:
        claims.append({"claim": "positive_business_conclusion", "reason": "no_supplied_evidence"})
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for claim in claims:
        key = str(claim.get("claim"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(claim)
    return unique


def grounding_prompt_block(grounding_input: dict[str, Any]) -> dict[str, Any]:
    return {
        "strictGroundingPolicy": "evidence_only",
        "requirements": STRICT_GROUNDING_REQUIREMENTS,
        "groundedOcrEvidence": {
            key: grounding_input.get(key)
            for key in [
                "schemaVersion",
                "documentVersionIds",
                "groundingStatus",
                "fields",
                "tables",
                "seals",
                "fragments",
                "evidenceLinks",
                "quality",
                "summary",
                "reviewWarnings",
            ]
        },
        "requiredOutput": {
            "findings": [
                {
                    "findingType": "string",
                    "severity": "low|medium|high",
                    "title": "string",
                    "description": "string",
                    "evidenceRefs": [{"evidenceLinkId": "string", "documentVersionId": "string", "pageNo": "number", "bbox": [0, 0, 0, 0]}],
                    "ruleRefs": [{"ruleCode": "string", "ruleSetVersion": "string"}],
                    "kbRefs": [{"retrievalTraceId": "string", "clauseIds": ["string"]}],
                    "confidence": "0..1",
                    "suggestedAction": "human_confirm|request_correction",
                    "groundingStatus": "grounded|insufficient_evidence",
                    "unsupportedClaims": [],
                }
            ]
        },
    }


def _field_evidence(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("id"),
        "documentVersionId": item.get("documentVersionId"),
        "fieldName": item.get("fieldName"),
        "fieldValue": item.get("fieldValue"),
        "pageNo": item.get("pageNo"),
        "bbox": item.get("bbox"),
        "confidence": item.get("confidence"),
        "reviewStatus": item.get("reviewStatus"),
        "evidenceLinkId": item.get("evidenceLinkId"),
        "extractionMethod": item.get("extractionMethod"),
    }


def _table_evidence(table: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": table.get("tableId") or table.get("id"),
        "documentVersionId": result.get("documentVersionId"),
        "tableCode": table.get("businessSchema") or table.get("tableCode") or table.get("tableName"),
        "pageNo": table.get("pageNo") or 1,
        "bbox": table.get("bbox"),
        "structureConfidence": table.get("structureConfidence"),
        "contentMarkdown": table.get("contentMarkdown") or table.get("markdown"),
        "rows": table.get("rows") or [],
        "cells": table.get("cells") or [],
        "sourceEngine": table.get("sourceEngine"),
        "qualityFlags": table.get("qualityFlags") or [],
    }


def _seal_evidence(seal: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": seal.get("sealId") or seal.get("id"),
        "documentVersionId": result.get("documentVersionId"),
        "sealName": seal.get("sealName") or seal.get("name") or seal.get("text"),
        "sealText": seal.get("sealText") or seal.get("text") or seal.get("rawText"),
        "sealType": seal.get("sealType"),
        "fields": seal.get("fields") or [],
        "pageNo": seal.get("pageNo") or 1,
        "bbox": seal.get("bbox") or seal.get("polygon"),
        "visualConfidence": seal.get("visualConfidence"),
        "ocrConfidence": seal.get("ocrConfidence"),
        "sourceEngine": seal.get("sourceEngine"),
        "qualityFlags": seal.get("qualityFlags") or [],
    }


def _fragment_evidence(fragment: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    return {
        "documentVersionId": result.get("documentVersionId"),
        "pageNo": fragment.get("pageNo") or 1,
        "text": fragment.get("text") or fragment.get("fullText"),
        "bbox": fragment.get("bbox") or fragment.get("polygon"),
        "confidence": fragment.get("confidence"),
        "sourceEngine": fragment.get("sourceEngine"),
    }


def _evidence_link(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("id"),
        "objectType": item.get("objectType"),
        "objectId": item.get("objectId"),
        "documentId": item.get("documentId"),
        "documentVersionId": item.get("documentVersionId"),
        "fileName": item.get("fileName"),
        "pageNo": item.get("pageNo"),
        "fieldName": item.get("fieldName"),
        "quotedText": item.get("quotedText"),
        "bbox": item.get("bbox"),
        "confidence": item.get("confidence"),
    }


def _evidence_ref(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "evidenceLinkId": item.get("id"),
        "documentVersionId": item.get("documentVersionId"),
        "pageNo": item.get("pageNo"),
        "bbox": item.get("bbox"),
        "source": "evidence_link",
    }


def _grounding_warnings(grounding_status: str, low_confidence: list[dict[str, Any]], missing_position: list[dict[str, Any]]) -> list[dict[str, Any]]:
    warnings = []
    if grounding_status != "grounded":
        warnings.append({"code": "INSUFFICIENT_OCR_EVIDENCE", "message": "No document-scoped OCR evidence links are available."})
    if low_confidence:
        warnings.append({"code": "LOW_CONFIDENCE_OCR_EVIDENCE", "count": len(low_confidence)})
    if missing_position:
        warnings.append({"code": "OCR_EVIDENCE_POSITION_MISSING", "count": len(missing_position)})
    return warnings


def _evidence_texts(*groups: list[dict[str, Any]]) -> list[str]:
    texts: list[str] = []
    for group in groups:
        for item in group:
            if not isinstance(item, dict):
                continue
            for key in ["fieldName", "fieldValue", "quotedText", "text", "sealName", "sealText", "contentMarkdown", "tableCode"]:
                value = item.get(key)
                if value:
                    texts.append(str(value))
            for key in ["fields", "rows", "cells"]:
                value = item.get(key)
                if value:
                    texts.append(str(value))
    return [text[:1200] for text in texts if text.strip()]


def _claim_tokens(text: str) -> list[str]:
    tokens = {term for term in GROUNDING_TERMS if term in (text or "")}
    tokens.update(match.group(0) for match in CODE_TOKEN_RE.finditer(text or ""))
    tokens.update(match.group(0) for match in DATE_TOKEN_RE.finditer(text or "") if len(match.group(0).strip()) >= 4)
    tokens.update(match.group(0) for match in ORG_TOKEN_RE.finditer(text or ""))
    tokens.update(match.group(1) for match in PERSON_TOKEN_RE.finditer(text or ""))
    return [token for token in tokens if token]


def _normalized_text(value: str) -> str:
    return re.sub(r"[\s,，。:：;；、（）()\[\]【】\"'“”‘’_-]+", "", str(value or "")).lower()


def _dict_items(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _safe_float(value: Any, *, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
