from __future__ import annotations

import re
from typing import Any

from libs.audit_runtime import audit_runtime_config
from libs.review_page_scope import normalize_page_ranges


def _validation_payload(
    *, passed: bool, checked: int,
    failures: list[dict[str, Any]] | None = None,
    warnings: list[dict[str, Any]] | None = None,
    metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "passed": passed, "checked": checked, "failures": failures or [],
        "warnings": warnings or [], "metrics": metrics or {},
    }


def validate_bbox(value: Any) -> bool:
    if not isinstance(value, list | tuple) or len(value) != 4:
        return False
    try:
        x1, y1, x2, y2 = [float(item) for item in value]
    except (TypeError, ValueError):
        return False
    return x2 > x1 and y2 > y1 and x1 >= 0 and y1 >= 0


# 同一个日期：结论里写 2028-09-06，OCR 原文是 2028年9月6日——统一成 YYYYMMDD 再比。
_DATE_TEXT = re.compile(r"(?<!\d)(\d{4})\s*[年\-/.／]\s*(\d{1,2})\s*[月\-/.／]\s*(\d{1,2})\s*日?(?!\d)")
# 标准号（GB 50235-2010、NB/T 47014-2023 规范化后的形状）；它是审查依据，出处是条款引用，不是项目资料。
_STANDARD_TOKEN = re.compile(r"[A-Z]{1,7}\d{2,}")
_CLAUSE_CODE_KEYS = ("standardCode", "sourceStandardCode", "targetStandardCode", "kbDocId")
# 外部登记记录（公示平台）：没有页码与 bbox，定位靠来源与登记页地址。
_REGISTRY_SOURCES = frozenset({"cnse_platform"})


def normalize_claim_text(value: Any) -> str:
    text = _DATE_TEXT.sub(
        lambda match: f"{match.group(1)}{int(match.group(2)):02d}{int(match.group(3)):02d}", str(value or ""))
    return re.sub(r"[\s\u3000:：/／\\\-_.，。,、()（）\[\]【】]+", "", text.upper())


def extract_claim_tokens(draft: dict[str, Any]) -> list[str]:
    text = "\n".join(
        str(draft.get(key) or "")
        for key in ["title", "description", "opinionDraft", "resultText", "suggestedAction"]
    )
    patterns = [
        r"\b[A-Z]{1,6}\s*/?\s*T?\s*\d{2,6}(?:\.\d+)?(?:-\d{4})?\b",
        r"\bTS[A-Z0-9\-]{6,}\b",
        r"\bA\d{6,}\b",
        r"\b\d{4}[年\-/.]\d{1,2}[月\-/.]\d{1,2}日?\b",
        r"\b\d+(?:\.\d+)?\s*(?:%|MPA|MM|℃|级|类)\b",
        r"[\u4e00-\u9fa5]{2,30}(?:公司|院|中心|厂|集团|有限责任公司)",
    ]
    tokens: list[str] = []
    for pattern in patterns:
        for match in re.findall(pattern, text, flags=re.IGNORECASE):
            token = match if isinstance(match, str) else "".join(match)
            normalized = normalize_claim_text(token)
            if normalized and normalized not in tokens:
                tokens.append(normalized)
    return tokens[:20]


def evidence_text_corpus(evidence_links: list[dict[str, Any]]) -> str:
    values: list[str] = []
    for row in evidence_links:
        for key in ["quotedText", "quote", "text", "fieldName", "fieldValue", "fileName", "standardCode", "reportNo", "conclusion"]:
            if row.get(key):
                values.append(str(row.get(key)))
        for item in row.get("matchedEvidenceItems") or []:
            values.append(str(item))
    return normalize_claim_text("\n".join(values))


def _registry_anchor(anchor: dict[str, Any]) -> bool:
    """公示平台登记记录：来源是已知登记平台、登记页地址在该平台上、有引文，且不冒充文档页内位置。"""
    source = str(anchor.get("source") or "")
    if source not in _REGISTRY_SOURCES or anchor.get("pageNo") not in (0, None) or anchor.get("bbox") is not None:
        return False
    from libs.integrations.external_registry_queries import configured_cnse_origin

    origin = configured_cnse_origin().rstrip("/")
    url = str(anchor.get("sourceUrl") or "")
    return bool(origin) and (url == origin or url.startswith(origin + "/"))


def _clause_reference_codes(
    draft: dict[str, Any], review_run: dict[str, Any] | None, source_state: dict[str, Any] | None,
) -> list[str]:
    """本条发现引用的条款（kbRefs 的 clauseIds、ruleRefs 对应规则结果的 linkedClauseIds）的标准号。

    只认本次运行落库的检索 Trace 里的条款：发现自己写的引用文本不作数。
    """
    run_id = str((review_run or {}).get("reviewRunId") or "")
    if not run_id or not source_state:
        return []
    clauses: dict[tuple[str, str], dict[str, Any]] = {}
    for trace in source_state.get("retrieval_traces") or []:
        if not isinstance(trace, dict) or str(trace.get("reviewRunId") or "") != run_id:
            continue
        trace_id = str(trace.get("retrievalTraceId") or trace.get("id") or "")
        for clause in trace.get("selectedClauses") or []:
            if isinstance(clause, dict) and clause.get("clauseId"):
                clauses[(trace_id, str(clause["clauseId"]))] = clause
    cited: list[dict[str, Any]] = []
    for ref in draft.get("kbRefs") if isinstance(draft.get("kbRefs"), list) else []:
        if isinstance(ref, dict) and isinstance(ref.get("clauseIds"), list):
            trace_id = str(ref.get("retrievalTraceId") or "")
            cited.extend(clauses[(trace_id, str(item))] for item in ref["clauseIds"] if (trace_id, str(item)) in clauses)
    rule_codes = {str(ref.get("ruleCode")) for ref in draft.get("ruleRefs") or [] if isinstance(ref, dict) and ref.get("ruleCode")}
    linked = {
        str(clause_id)
        for result in source_state.get("rule_check_results") or []
        if isinstance(result, dict) and str(result.get("reviewRunId") or "") == run_id
        and str(result.get("ruleCode") or "") in rule_codes
        for clause_id in result.get("linkedClauseIds") or []
    }
    cited.extend(clause for (_, clause_id), clause in clauses.items() if clause_id in linked)
    return [normalize_claim_text(clause[key]) for clause in cited for key in _CLAUSE_CODE_KEYS if clause.get(key)]


def validate_review_evidence_refs(
    drafts: list[dict[str, Any]],
    evidence_links: list[dict[str, Any]],
    *,
    audit_runtime: dict[str, Any] | None = None,
    review_run: dict[str, Any] | None = None,
    source_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    runtime = audit_runtime or audit_runtime_config()
    if runtime.get("requireEvidenceRefs") is False:
        warnings = []
        for draft_index, draft in enumerate(drafts):
            if draft.get("evidenceRefs"):
                warnings.append(
                    {
                        "code": "PURE_LLM_EVIDENCE_REFS_IGNORED",
                        "index": draft_index,
                        "message": "Pure LLM mode does not require evidenceRefs; OCR/page/bbox evidence was not loaded.",
                    }
                )
        warnings.append(
            {
                "code": "PURE_LLM_REVIEW_ADVISORY_ONLY",
                "message": "Evidence validation is advisory because auditInputMode does not require OCR evidence.",
            }
        )
        return _validation_payload(
            passed=True,
            checked=0,
            warnings=warnings,
            metrics={
                "evidenceRefCount": 0,
                "availableEvidenceLinks": len(evidence_links),
                "auditInputMode": runtime.get("mode"),
                "evidenceValidationMode": runtime.get("evidenceValidationMode"),
            },
        )
    failures: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    anchors: dict[str, dict[str, Any]] = {}
    duplicate_ids: set[str] = set()
    for item in evidence_links:
        if not isinstance(item, dict):
            continue
        for key in ("id", "evidenceRefId"):
            anchor_id = str(item.get(key) or "")
            if not anchor_id:
                continue
            if anchor_id in anchors and anchors[anchor_id] is not item:
                duplicate_ids.add(anchor_id)
            else:
                anchors[anchor_id] = item
    allowed_versions = {str(item) for item in review_run.get("inputDocumentVersionIds") or []} if review_run else None
    page_ranges = normalize_page_ranges(
        review_run.get("inputDocumentPageRanges") or {}, list(allowed_versions)
    ) if review_run else {}
    versions = {
        str(item.get("id") or item.get("documentVersionId")): item
        for item in [*((source_state or {}).get("versions") or []),
                     *((source_state or {}).get("document_versions") or [])]
        if isinstance(item, dict)
    }
    documents = {
        str(item.get("id")): item for item in (source_state or {}).get("documents") or []
        if isinstance(item, dict) and item.get("id")
    }
    checked_refs = 0
    normalized_refs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for draft_index, draft in enumerate(drafts):
        refs = draft.get("evidenceRefs") if isinstance(draft.get("evidenceRefs"), list) else []
        if not refs:
            issue = {"code": "NO_EVIDENCE_REFS", "index": draft_index,
                     "message": "Finding has no direct evidence references."}
            if draft.get("groundingStatus") == "insufficient_evidence":
                warnings.append(issue)
            else:
                failures.append(issue)
            continue
        cited_anchors: list[dict[str, Any]] = []
        for ref_index, ref in enumerate(refs):
            checked_refs += 1
            if not isinstance(ref, dict):
                failures.append({"code": "EVIDENCE_REF_NOT_OBJECT", "index": draft_index, "refIndex": ref_index})
                continue
            evidence_link_id = str(ref.get("evidenceLinkId") or ref.get("sourceAnchorId") or "")
            if evidence_link_id in duplicate_ids:
                failures.append({"code": "EVIDENCE_LINK_AMBIGUOUS", "index": draft_index, "refIndex": ref_index, "evidenceLinkId": evidence_link_id})
                continue
            anchor = anchors.get(evidence_link_id) if evidence_link_id else None
            if anchor is None and not evidence_link_id:
                matches = [item for item in anchors.values() if (
                    str(item.get("documentVersionId") or "") == str(ref.get("documentVersionId") or "")
                    and item.get("pageNo") == ref.get("pageNo")
                    and validate_bbox(item.get("bbox"))
                    and validate_bbox(ref.get("bbox"))
                    and [float(value) for value in item["bbox"]] == [float(value) for value in ref["bbox"]]
                    and (not ref.get("quotedText") or str(ref["quotedText"]) == str(item.get("quotedText") or ""))
                )]
                if len(matches) == 1:
                    anchor = matches[0]
                    evidence_link_id = str(anchor.get("id") or anchor.get("evidenceRefId"))
                    if evidence_link_id in duplicate_ids:
                        failures.append({"code": "EVIDENCE_LINK_AMBIGUOUS", "index": draft_index, "refIndex": ref_index})
                        continue
                elif len(matches) > 1:
                    failures.append({"code": "EVIDENCE_LINK_AMBIGUOUS", "index": draft_index, "refIndex": ref_index})
                    continue
            if anchor is None:
                failures.append({"code": "EVIDENCE_LINK_NOT_FOUND", "index": draft_index, "refIndex": ref_index, "evidenceLinkId": evidence_link_id or None})
                continue
            evidence_link_id = str(anchor.get("id") or anchor.get("evidenceRefId"))
            version_id = str(anchor.get("documentVersionId") or "")
            page_no = anchor.get("pageNo")
            bbox = anchor.get("bbox")
            quote = str(anchor.get("quotedText") or anchor.get("quote") or anchor.get("text") or "").strip()
            registry = _registry_anchor(anchor)
            if not version_id or not quote or (not registry and (
                    type(page_no) is not int or page_no < 1 or not validate_bbox(bbox))):
                failures.append({"code": "EVIDENCE_ANCHOR_NOT_LOCATABLE", "index": draft_index, "refIndex": ref_index, "evidenceLinkId": evidence_link_id})
                continue
            if allowed_versions is not None and version_id not in allowed_versions:
                failures.append({"code": "EVIDENCE_REF_OUTSIDE_RUN", "index": draft_index, "refIndex": ref_index, "evidenceLinkId": evidence_link_id})
                continue
            bounds = page_ranges.get(version_id)
            if bounds and not registry and not bounds["start"] <= page_no <= bounds["end"]:
                failures.append({"code": "EVIDENCE_REF_OUTSIDE_PAGE_RANGE", "index": draft_index, "refIndex": ref_index, "evidenceLinkId": evidence_link_id})
                continue
            if source_state is not None:
                version = versions.get(version_id)
                document = documents.get(str((version or {}).get("documentId") or ""))
                if (not version or not document
                        or str(document.get("projectId") or "") != str((review_run or {}).get("projectId") or "")
                        or (anchor.get("documentId") and str(anchor["documentId"]) != str(document["id"]))
                        or ((review_run or {}).get("tenantId") and document.get("tenantId")
                            and str(document["tenantId"]) != str(review_run["tenantId"]))):
                    failures.append({"code": "EVIDENCE_ANCHOR_OUTSIDE_PROJECT", "index": draft_index, "refIndex": ref_index, "evidenceLinkId": evidence_link_id})
                    continue
            conflicting = False
            for key in ("documentVersionId", "pageNo", "bbox", "quotedText", "documentId"):
                if ref.get(key) is None:
                    continue
                if key == "bbox":
                    conflicting = registry or not validate_bbox(ref[key]) or (
                        [float(value) for value in ref[key]] != [float(value) for value in bbox]
                    )
                elif key == "quotedText":
                    conflicting = str(ref[key]) != quote
                else:
                    conflicting = ref[key] != anchor.get(key)
                if conflicting:
                    break
            if conflicting:
                failures.append({"code": "EVIDENCE_REF_ANCHOR_MISMATCH", "index": draft_index, "refIndex": ref_index, "evidenceLinkId": evidence_link_id})
                continue
            normalized = {"evidenceLinkId": evidence_link_id, "documentVersionId": version_id,
                          "pageNo": page_no, "bbox": None if registry else list(bbox), "quotedText": quote}
            if registry:
                normalized.update({"source": anchor["source"], "sourceUrl": anchor["sourceUrl"]})
            if anchor.get("documentId"):
                normalized["documentId"] = anchor["documentId"]
            normalized_refs.append((ref, normalized))
            cited_anchors.append(anchor)
        claim_tokens = extract_claim_tokens(draft)
        if claim_tokens:
            corpus = evidence_text_corpus(cited_anchors)
            missing_tokens = [token for token in claim_tokens if token not in corpus]
            if any(_STANDARD_TOKEN.fullmatch(token) for token in missing_tokens):
                clause_codes = _clause_reference_codes(draft, review_run, source_state)
                missing_tokens = [token for token in missing_tokens
                                  if not (_STANDARD_TOKEN.fullmatch(token) and any(token in code for code in clause_codes))]
            if missing_tokens:
                failures.append({"code": "CLAIM_TO_EVIDENCE_MISMATCH", "index": draft_index,
                                 "missingTokens": missing_tokens[:10],
                                 "message": "Finding contains explicit numbers/dates/certificates/standards/entities not found in cited evidence text."})
    if not failures:
        for ref, normalized in normalized_refs:
            ref.update(normalized)
    return _validation_payload(
        passed=not failures,
        checked=checked_refs,
        failures=failures,
        warnings=warnings,
        metrics={"evidenceRefCount": checked_refs, "availableEvidenceLinks": len(evidence_links)},
    )
