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


def normalize_claim_text(value: Any) -> str:
    text = str(value or "").upper()
    return re.sub(r"[\s\u3000:：/／\\\-_.，。,、()（）\[\]【】]+", "", text)


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
            if (not version_id or type(page_no) is not int or page_no < 1
                    or not validate_bbox(bbox) or not quote):
                failures.append({"code": "EVIDENCE_ANCHOR_NOT_LOCATABLE", "index": draft_index, "refIndex": ref_index, "evidenceLinkId": evidence_link_id})
                continue
            if allowed_versions is not None and version_id not in allowed_versions:
                failures.append({"code": "EVIDENCE_REF_OUTSIDE_RUN", "index": draft_index, "refIndex": ref_index, "evidenceLinkId": evidence_link_id})
                continue
            bounds = page_ranges.get(version_id)
            if bounds and not bounds["start"] <= page_no <= bounds["end"]:
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
                    conflicting = not validate_bbox(ref[key]) or (
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
                          "pageNo": page_no, "bbox": list(bbox), "quotedText": quote}
            if anchor.get("documentId"):
                normalized["documentId"] = anchor["documentId"]
            normalized_refs.append((ref, normalized))
            cited_anchors.append(anchor)
        claim_tokens = extract_claim_tokens(draft)
        if claim_tokens:
            corpus = evidence_text_corpus(cited_anchors)
            missing_tokens = [token for token in claim_tokens if token not in corpus]
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
