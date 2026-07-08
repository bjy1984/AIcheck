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

PURE_LLM_REVIEW_REQUIREMENTS = [
    "This run is configured as pure_llm: OCR evidence is not loaded or required.",
    "Do not claim document text, seal text, table values, bbox/page evidence, certificate authenticity, validity, or project coverage was verified by OCR.",
    "Use project context, ruleResults, kbRefs, and explicitly supplied non-OCR context only.",
    "Set groundingStatus to insufficient_evidence and suggestedAction to human_confirm.",
    "Every finding is advisory and must require human confirmation; do not issue a final business approval or correction.",
    "Return JSON only with findings, unsupportedClaims, and groundingStatus; no free-text answer.",
]

LOW_CONFIDENCE_THRESHOLD = 0.85
MAX_TABLE_MARKDOWN_CHARS = 6000
MAX_TABLE_ROWS = 60
MAX_TABLE_CELLS = 160

CRITICAL_QUALITY_FLAG_HINTS = (
    "missing",
    "low_conf",
    "low-confidence",
    "uncertain",
    "visual_candidate",
    "visual-only",
    "text_only",
    "requires_",
    "not_found",
)


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
    low_confidence = _low_confidence_items(fields, tables, seals, fragments)
    missing_position = [
        item
        for item in [*fields, *tables, *seals, *fragments]
        if not _has_position(item)
    ]
    evidence_texts = _evidence_texts(fields, tables, seals, fragments, evidence_links)
    table_content_missing = [item for item in tables if not _table_has_content(item)]
    seal_text_risk = [item for item in seals if _seal_text_has_risk(item)]
    critical_quality = _critical_quality_items(fields, tables, seals, fragments, quality)
    blocking_issues = _blocking_grounding_issues(
        evidence_texts=evidence_texts,
        evidence_links=evidence_links,
        low_confidence=low_confidence,
        missing_position=missing_position,
        table_content_missing=table_content_missing,
        seal_text_risk=seal_text_risk,
        critical_quality=critical_quality,
    )
    grounding_status = "grounded" if not blocking_issues else "insufficient_evidence"
    return {
        "schemaVersion": "EvidenceGroundedReviewInput@1.0.0",
        "documentVersionIds": sorted(version_ids),
        "groundingStatus": grounding_status,
        "blockingIssues": blocking_issues,
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
            "tableContentMissingCount": len(table_content_missing),
            "sealTextRiskCount": len(seal_text_risk),
            "criticalQualityFlagCount": len(critical_quality),
            "blockingIssueCount": len(blocking_issues),
            "groundingStatus": grounding_status,
        },
        "reviewWarnings": _grounding_warnings(
            grounding_status,
            low_confidence,
            missing_position,
            blocking_issues,
        ),
    }


def apply_grounding_guardrails(drafts: list[dict[str, Any]], grounding_input: dict[str, Any]) -> list[dict[str, Any]]:
    evidence_links = [item for item in grounding_input.get("evidenceLinks") or [] if isinstance(item, dict)]
    default_refs = [_evidence_ref(item) for item in evidence_links[:3]]
    allowed_link_ids = {str(item.get("id")) for item in evidence_links if item.get("id")}
    allowed_version_ids = {str(item) for item in grounding_input.get("documentVersionIds") or [] if item}
    evidence_texts = [str(item) for item in grounding_input.get("evidenceTextCorpus") or [] if str(item).strip()]
    input_status = str(grounding_input.get("groundingStatus") or "insufficient_evidence")
    grounding_policy = str(grounding_input.get("groundingPolicy") or "evidence_only")
    guarded: list[dict[str, Any]] = []
    for draft in drafts or []:
        item = dict(draft)
        refs = item.get("evidenceRefs") if isinstance(item.get("evidenceRefs"), list) else []
        refs = _valid_evidence_refs(refs, allowed_link_ids, allowed_version_ids)
        if not refs and default_refs:
            refs = default_refs
        item["evidenceRefs"] = refs
        item["evidenceLinkIds"] = [ref.get("evidenceLinkId") for ref in refs if isinstance(ref, dict) and ref.get("evidenceLinkId")]
        item["requiresHumanConfirmation"] = True
        if item.get("suggestedAction") not in {"human_confirm", "request_correction"}:
            item["suggestedAction"] = "human_confirm"
        if grounding_policy == "llm_only_human_review":
            item["unsupportedClaims"] = item.get("unsupportedClaims") if isinstance(item.get("unsupportedClaims"), list) else []
            item["groundingStatus"] = "insufficient_evidence"
            item["suggestedAction"] = "human_confirm"
            item["confidence"] = min(_safe_float(item.get("confidence"), default=0.55), 0.55)
            item["evidenceRefs"] = []
            item["evidenceLinkIds"] = []
            item["sourceMethod"] = "pure_llm_review"
            item.setdefault("llmGroundingWarnings", []).append(
                {
                    "code": "PURE_LLM_REVIEW_NO_OCR_EVIDENCE",
                    "message": "Pure LLM mode is advisory only; no OCR/page/bbox evidence was loaded for this finding.",
                }
            )
            guarded.append(item)
            continue
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
    claim_tokens = _claim_tokens(text)
    if not claim_tokens:
        claims.append({"claim": "positive_business_conclusion", "reason": "positive_claim_without_specific_evidence_token"})
    for token in claim_tokens:
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
    grounding_policy = str(grounding_input.get("groundingPolicy") or "evidence_only")
    if grounding_policy == "llm_only_human_review":
        return {
            "strictGroundingPolicy": "llm_only_human_review",
            "requirements": PURE_LLM_REVIEW_REQUIREMENTS,
            "groundedOcrEvidence": {
                key: grounding_input.get(key)
                for key in [
                    "schemaVersion",
                    "documentVersionIds",
                    "groundingStatus",
                    "blockingIssues",
                    "fields",
                    "tables",
                    "seals",
                    "fragments",
                    "evidenceLinks",
                    "quality",
                    "summary",
                    "reviewWarnings",
                    "groundingPolicy",
                    "auditInputMode",
                ]
            },
            "requiredOutput": {
                "findings": [
                    {
                        "findingType": "string",
                        "severity": "low|medium|high",
                        "title": "string",
                        "description": "string",
                        "evidenceRefs": [],
                        "ruleRefs": [{"ruleCode": "string", "ruleSetVersion": "string"}],
                        "kbRefs": [{"retrievalTraceId": "string", "clauseIds": ["string"]}],
                        "confidence": "0..0.55",
                        "suggestedAction": "human_confirm",
                        "groundingStatus": "insufficient_evidence",
                        "unsupportedClaims": [],
                    }
                ]
            },
        }
    return {
        "strictGroundingPolicy": "evidence_only",
        "requirements": STRICT_GROUNDING_REQUIREMENTS,
        "groundedOcrEvidence": {
            key: grounding_input.get(key)
            for key in [
                "schemaVersion",
                "documentVersionIds",
                "groundingStatus",
                "blockingIssues",
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
    cells = _dict_items(table.get("cells"))
    normalized_rows = _table_rows(table)
    content_markdown = _table_markdown(table, cells, normalized_rows)
    cells_summary = _table_cells_summary(cells)
    return {
        "id": table.get("tableId") or table.get("id"),
        "documentVersionId": result.get("documentVersionId"),
        "tableCode": table.get("businessSchema") or table.get("tableCode") or table.get("tableName"),
        "pageNo": table.get("pageNo") or 1,
        "bbox": table.get("bbox"),
        "structureConfidence": table.get("structureConfidence"),
        "rowCount": _safe_int(table.get("rowCount") or table.get("rows"), default=None),
        "columnCount": _safe_int(table.get("columnCount") or table.get("columns"), default=None),
        "contentMarkdown": content_markdown,
        "normalizedRows": normalized_rows[:MAX_TABLE_ROWS],
        "rows": normalized_rows[:MAX_TABLE_ROWS],
        "cellsSummary": cells_summary,
        "cells": cells_summary,
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


def _valid_evidence_refs(
    refs: list[Any],
    allowed_link_ids: set[str],
    allowed_version_ids: set[str],
) -> list[dict[str, Any]]:
    valid: list[dict[str, Any]] = []
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        link_id = str(ref.get("evidenceLinkId") or "")
        version_id = str(ref.get("documentVersionId") or "")
        if link_id and link_id in allowed_link_ids:
            valid.append(ref)
            continue
        if version_id and version_id in allowed_version_ids and ref.get("pageNo") and _has_bbox(ref.get("bbox")):
            valid.append(ref)
    return valid


def _table_rows(table: dict[str, Any]) -> list[Any]:
    for key in ["normalizedRows", "businessRows", "dataRows", "rows"]:
        rows = table.get(key)
        if not isinstance(rows, list):
            continue
        normalized = [_normalize_table_row(row) for row in rows]
        return [row for row in normalized if row not in ({}, [], "")]
    return []


def _normalize_table_row(row: Any) -> Any:
    if isinstance(row, dict):
        return {
            _truncate(str(key), 80): _truncate(_cell_value_text(value), 240)
            for key, value in row.items()
            if _cell_value_text(value).strip()
        }
    if isinstance(row, list):
        return [_truncate(_cell_value_text(value), 240) for value in row if _cell_value_text(value).strip()]
    return _truncate(_cell_value_text(row), 240)


def _table_markdown(table: dict[str, Any], cells: list[dict[str, Any]], normalized_rows: list[Any]) -> str | None:
    for key in ["contentMarkdown", "markdown"]:
        value = str(table.get(key) or "").strip()
        if value:
            return _truncate(value, MAX_TABLE_MARKDOWN_CHARS)
    value = str(table.get("content") or "").strip()
    if value:
        return _truncate(value, MAX_TABLE_MARKDOWN_CHARS)
    if normalized_rows:
        markdown = _markdown_from_rows(normalized_rows)
        if markdown:
            return _truncate(markdown, MAX_TABLE_MARKDOWN_CHARS)
    if cells:
        markdown = _markdown_from_cells(cells)
        if markdown:
            return _truncate(markdown, MAX_TABLE_MARKDOWN_CHARS)
    return None


def _markdown_from_rows(rows: list[Any]) -> str | None:
    if not rows:
        return None
    if all(isinstance(row, dict) for row in rows):
        headers: list[str] = []
        for row in rows:
            for key in row:
                if str(key) not in headers:
                    headers.append(str(key))
        if not headers:
            return None
        body = [
            [_markdown_cell(str(row.get(header) or "")) for header in headers]
            for row in rows[:MAX_TABLE_ROWS]
            if isinstance(row, dict)
        ]
        return _markdown_table(headers, body)
    body_rows = [
        row if isinstance(row, list) else [row]
        for row in rows[:MAX_TABLE_ROWS]
    ]
    max_cols = max((len(row) for row in body_rows), default=0)
    if max_cols <= 0:
        return None
    headers = [f"列{index + 1}" for index in range(max_cols)]
    body = [
        [_markdown_cell(str(row[index] if index < len(row) else "")) for index in range(max_cols)]
        for row in body_rows
    ]
    return _markdown_table(headers, body)


def _markdown_from_cells(cells: list[dict[str, Any]]) -> str | None:
    positioned = []
    for cell in cells:
        text = _cell_text(cell)
        if not text.strip():
            continue
        row_index = _cell_index(cell, ["rowIndex", "row", "rowNo", "r"])
        col_index = _cell_index(cell, ["columnIndex", "colIndex", "column", "col", "c"])
        if row_index is None or col_index is None:
            continue
        positioned.append((row_index, col_index, text))
    if not positioned:
        return None
    rows = sorted({row for row, _, _ in positioned})
    cols = sorted({col for _, col, _ in positioned})
    if not rows or not cols:
        return None
    grid: dict[tuple[int, int], str] = {}
    for row, col, text in positioned[:MAX_TABLE_CELLS]:
        key = (row, col)
        grid[key] = f"{grid[key]} / {text}" if grid.get(key) else text
    first_row = rows[0]
    headers = [_markdown_cell(grid.get((first_row, col)) or f"列{index + 1}") for index, col in enumerate(cols)]
    body = [
        [_markdown_cell(grid.get((row, col)) or "") for col in cols]
        for row in rows[1:MAX_TABLE_ROWS]
    ]
    if not body:
        body = [[_markdown_cell(grid.get((first_row, col)) or "") for col in cols]]
    return _markdown_table(headers, body)


def _markdown_table(headers: list[str], body: list[list[str]]) -> str | None:
    if not headers:
        return None
    clean_headers = [_markdown_cell(header or f"列{index + 1}") for index, header in enumerate(headers)]
    lines = [
        "| " + " | ".join(clean_headers) + " |",
        "| " + " | ".join(["---"] * len(clean_headers)) + " |",
    ]
    for row in body:
        padded = [row[index] if index < len(row) else "" for index in range(len(clean_headers))]
        lines.append("| " + " | ".join(_markdown_cell(cell) for cell in padded) + " |")
    return "\n".join(lines)


def _table_cells_summary(cells: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summary: list[dict[str, Any]] = []
    for cell in cells[:MAX_TABLE_CELLS]:
        text = _cell_text(cell)
        if not text.strip():
            continue
        summary.append(
            {
                "rowIndex": _cell_index(cell, ["rowIndex", "row", "rowNo", "r"]),
                "columnIndex": _cell_index(cell, ["columnIndex", "colIndex", "column", "col", "c"]),
                "text": _truncate(text, 220),
                "bbox": cell.get("bbox") or cell.get("polygon"),
                "confidence": cell.get("confidence") or cell.get("score"),
                "isHeader": bool(cell.get("isHeader") or cell.get("header")),
            }
        )
    return summary


def _blocking_grounding_issues(
    *,
    evidence_texts: list[str],
    evidence_links: list[dict[str, Any]],
    low_confidence: list[dict[str, Any]],
    missing_position: list[dict[str, Any]],
    table_content_missing: list[dict[str, Any]],
    seal_text_risk: list[dict[str, Any]],
    critical_quality: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    if not evidence_texts:
        issues.append({"code": "OCR_GROUNDING_TEXT_MISSING", "message": "No OCR text is available for grounded review."})
    if not evidence_links:
        issues.append({"code": "OCR_GROUNDING_EVIDENCE_LINK_MISSING", "message": "No document-scoped evidence links are available."})
    if low_confidence:
        issues.append({"code": "OCR_GROUNDING_LOW_CONFIDENCE", "count": len(low_confidence)})
    if missing_position:
        issues.append({"code": "OCR_GROUNDING_POSITION_MISSING", "count": len(missing_position)})
    if table_content_missing:
        issues.append({"code": "OCR_GROUNDING_TABLE_CONTENT_MISSING", "count": len(table_content_missing)})
    if seal_text_risk:
        issues.append({"code": "OCR_GROUNDING_SEAL_TEXT_RISK", "count": len(seal_text_risk)})
    if critical_quality:
        issues.append({"code": "OCR_GROUNDING_QUALITY_FLAGS", "count": len(critical_quality)})
    return issues


def _low_confidence_items(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    low: list[dict[str, Any]] = []
    for group in groups:
        for item in group:
            if not isinstance(item, dict):
                continue
            scores = [
                item.get("confidence"),
                item.get("structureConfidence"),
                item.get("ocrConfidence"),
                item.get("visualConfidence"),
            ]
            converted_scores = [_safe_float(score, default=None) for score in scores if score is not None and score != ""]
            numeric_scores = [score for score in converted_scores if score is not None]
            if numeric_scores and min(numeric_scores) < LOW_CONFIDENCE_THRESHOLD:
                low.append(item)
    return low


def _critical_quality_items(*groups: list[Any]) -> list[dict[str, Any]]:
    critical: list[dict[str, Any]] = []
    for group in groups:
        if not isinstance(group, list):
            continue
        for item in group:
            if not isinstance(item, dict):
                continue
            flags = item.get("qualityFlags")
            if flags is None and isinstance(item.get("quality"), dict):
                flags = item["quality"].get("qualityFlags") or item["quality"].get("flags")
            if not isinstance(flags, list):
                continue
            if any(_quality_flag_is_critical(flag) for flag in flags):
                critical.append(item)
    return critical


def _quality_flag_is_critical(flag: Any) -> bool:
    value = str(flag or "").strip().lower()
    return bool(value and any(hint in value for hint in CRITICAL_QUALITY_FLAG_HINTS))


def _table_has_content(table: dict[str, Any]) -> bool:
    if str(table.get("contentMarkdown") or "").strip():
        return True
    if table.get("normalizedRows") or table.get("cellsSummary"):
        return True
    return False


def _seal_text_has_risk(seal: dict[str, Any]) -> bool:
    flags = [str(flag).lower() for flag in seal.get("qualityFlags") or []]
    if any(_quality_flag_is_critical(flag) for flag in flags):
        return True
    has_text = bool(str(seal.get("sealText") or "").strip())
    has_fields = bool(seal.get("fields"))
    if not has_text and not has_fields:
        return True
    ocr_score = _safe_float(seal.get("ocrConfidence"), default=None)
    if ocr_score is not None and ocr_score < LOW_CONFIDENCE_THRESHOLD:
        return True
    if not has_text and _safe_float(seal.get("visualConfidence"), default=1.0) < LOW_CONFIDENCE_THRESHOLD:
        return True
    return False


def _has_position(item: dict[str, Any]) -> bool:
    return _has_bbox(item.get("bbox"))


def _has_bbox(value: Any) -> bool:
    if not isinstance(value, (list, tuple)) or len(value) < 4:
        return False
    numeric = [_safe_float(item, default=None) for item in value[:4]]
    return all(item is not None for item in numeric)


def _cell_text(cell: dict[str, Any]) -> str:
    for key in ["text", "value", "content", "fieldValue"]:
        value = cell.get(key)
        if value is not None and value != "":
            return str(value)
    return ""


def _cell_value_text(value: Any) -> str:
    if isinstance(value, dict):
        return _cell_text(value) or str(value.get("label") or value.get("name") or "")
    return str(value or "")


def _cell_index(cell: dict[str, Any], keys: list[str]) -> int | None:
    for key in keys:
        if key not in cell:
            continue
        value = _safe_int(cell.get(key), default=None)
        if value is None:
            continue
        if key in {"rowNo", "column"} and value > 0:
            return value - 1
        return value
    return None


def _markdown_cell(value: Any) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ").strip()


def _truncate(value: str, limit: int) -> str:
    text = str(value or "")
    return text if len(text) <= limit else f"{text[:limit]}..."


def _grounding_warnings(
    grounding_status: str,
    low_confidence: list[dict[str, Any]],
    missing_position: list[dict[str, Any]],
    blocking_issues: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    warnings = []
    if grounding_status != "grounded":
        warnings.append({"code": "INSUFFICIENT_OCR_EVIDENCE", "message": "OCR evidence is not sufficiently grounded for automated conclusions."})
    for issue in blocking_issues:
        warnings.append({"code": issue.get("code"), "count": issue.get("count"), "message": issue.get("message")})
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
            for key in ["fields", "rows", "cells", "normalizedRows", "cellsSummary"]:
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


def _safe_float(value: Any, *, default: float | None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, *, default: int | None) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
