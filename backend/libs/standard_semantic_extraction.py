"""Grounded semantic extraction for canonical standard-knowledge records."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

from libs.integrations.litellm_client import LiteLLMClient
from libs.knowledge_retrieval import (
    canonical_standard_text,
    display_standard_number,
    standard_refs_from_text,
)


BACKEND_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = BACKEND_ROOT / "config/standard_canonical_extraction_v1.json"
PROMPT_VERSION = "standard-canonical-extraction-v1"
MODEL_ROUTE = "review-chat"
SOURCE_TYPE = "new_mineru_semantic"

_DATE_VALUE = r"(\d{4}(?:[-./年])\d{1,2}(?:[-./月])\d{1,2}日?)"
_DATE_TOKEN_PATTERN = re.compile(_DATE_VALUE)
_DATE_PATTERNS = {
    "publicationDate": re.compile(rf"发布日期\s*[：:]?\s*{_DATE_VALUE}"),
    "effectiveDate": re.compile(rf"实施日期\s*[：:]?\s*{_DATE_VALUE}"),
}
_AUTHORITY_PATTERN = re.compile(
    r"(?:发布机构|发布部门|批准部门|批准发布部门)\s*[：:]?\s*([^。；;\n]{2,80})"
)
_REPLACEMENT_LABEL_PATTERN = re.compile(r"(?:代替|替代)\s*")
_LIST_FIELDS = {"draftingOrganizations", "draftingPeople", "keywords"}
_RELATION_FIELDS = {"normativeReferences", "replacementRelations"}
_NORMATIVE_KEYS = {
    "standardCode",
    "standardName",
    "clauseNo",
    "pageNo",
    "quotedText",
}
_REPLACEMENT_KEYS = {"relation", "standardCode", "pageNo", "quotedText"}
_EVIDENCE_VALUE_KEYS = {"value", "pageNo", "quotedText"}
_REPLACEMENT_RELATIONS = {"replaces", "replacedBy", "amends", "amendedBy"}
_IDENTITY_BLOCK_TYPES = {
    "cover",
    "document_title",
    "page_header",
}
_GENERIC_IDENTITY_BLOCK_TYPES = {"title", "header"}
_IDENTITY_CONTEXT_TITLES = {"封面", "标准封面", "首页标准题名"}
_IDENTITY_EXCLUSION_MARKERS = ("规范性引用文件", "引用标准", "参考文献", "目录", "术语")
_POSITIVE_IDENTITY_PATTERN = re.compile(r"中华人民共和国[^。；;\n]{0,30}标准")
_IDENTITY_LABEL_PATTERN = re.compile(r"(?:标准编号|标准号|标准代号)\s*[：:]?\s*")
_SCOPE_BOILERPLATE = ("本标准", "标准规定", "规定了", "适用于", "适用", "用于")
_SCOPE_PREDICATE_STRIP_PATTERN = re.compile(
    r"(?P<negation>不(?:应该|应当|应|得|可)?|未|无|禁止|不能|不宜)?"
    r"(?P<predicate>适用(?:于)?|用于)"
)
_SCOPE_PREDICATE_PATTERN = re.compile(r"适用于|适用|用于")
_SCOPE_STRONG_NEGATION_MARKERS = (
    "不应当",
    "不应该",
    "不应",
    "不得",
    "严禁",
    "禁止",
    "不可",
    "不能",
    "不宜",
)
_SCOPE_WEAK_NEGATION_MARKERS = ("不", "未", "无", "非")
_SCOPE_NEGATION_GAP_PATTERN = re.compile(
    r"(?:(?:被|再次|再|仍然|仍|直接|继续|予以|加以|擅自|随意|任意|一律|明确|"
    r"单独|重复|同时|仅|只))*"
)
_SCOPE_MAX_PREDICATE_GAP = 8
_SCOPE_SUBJECT_STOP_PATTERN = re.compile(r"[，,。；;\n]|但(?:是)?|并且|以及|且")
_PROMPT_INSTRUCTION = (
    "Extract only values explicitly supported by the supplied new MinerU pages. "
    "Return one strict JSON object with only requested fields. Omit unknown values. "
    "Evidence-required scalar values use {value,pageNo,quotedText}; relation items "
    "must include a real pageNo and a verbatim quotedText substring from that page."
)


def _schema() -> dict[str, Any]:
    payload = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schemaVersion") != PROMPT_VERSION:
        raise RuntimeError(f"invalid semantic extraction schema: {SCHEMA_PATH}")
    return payload


def semantic_field_names() -> frozenset[str]:
    return frozenset(str(value) for value in _schema()["required"])


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(value or ""))).strip()


def _positive_page_no(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        page_no = int(value)
    except (TypeError, ValueError):
        return None
    return page_no if page_no > 0 else None


def _block_has_selected_mineru_source(block: dict[str, Any]) -> bool:
    if block.get("authority") == "legacy_only":
        return False
    sources = [item for item in block.get("sources") or [] if isinstance(item, dict)]
    selected_source_id = str(block.get("selectedSourceId") or "")
    if selected_source_id:
        return any(
            str(item.get("sourceId") or "") == selected_source_id
            and item.get("sourceType") == "new_mineru"
            for item in sources
        )
    return any(item.get("sourceType") == "new_mineru" for item in sources)


def canonical_page_digest(record: dict[str, Any]) -> dict[int, str]:
    """Return normalized, page-addressable text selected from new MinerU blocks only."""
    pages: dict[int, list[str]] = {}
    for block in record.get("blocks") or []:
        if not isinstance(block, dict) or not _block_has_selected_mineru_source(block):
            continue
        page_no = _positive_page_no(block.get("pageNo"))
        text = _normalize_text(block.get("text"))
        if page_no is None or not text:
            continue
        pages.setdefault(page_no, []).append(text)
    return {
        page_no: _normalize_text("\n".join(values)) for page_no, values in sorted(pages.items())
    }


def _mineru_source_id(record: dict[str, Any]) -> str:
    active_parse_id = str(record.get("activeParseResultId") or "").strip()
    if active_parse_id:
        return active_parse_id
    source_ids = sorted(
        {
            str(source.get("sourceId") or "")
            for block in record.get("blocks") or []
            if isinstance(block, dict)
            for source in block.get("sources") or []
            if isinstance(source, dict)
            and source.get("sourceType") == "new_mineru"
            and str(source.get("sourceId") or "")
        }
    )
    if not source_ids:
        raise ValueError("canonical record has no selected new MinerU source")
    return source_ids[0]


def _normalize_standard_code(value: str) -> str:
    normalized = _normalize_text(value).replace("—", "-").replace("－", "-")
    normalized = re.sub(r"\s*/\s*", "/", normalized)
    normalized = re.sub(r"\s*-\s*", "-", normalized)
    references = standard_refs_from_text(canonical_standard_text(normalized))
    if len(references) == 1:
        reference = references[0]
        return display_standard_number(
            str(reference.get("prefix") or ""),
            str(reference.get("number") or ""),
            str(reference.get("year") or ""),
        )
    return normalized


def _normalize_date(value: str) -> str:
    normalized = _normalize_text(value).replace("年", "-").replace("月", "-").replace("日", "")
    normalized = normalized.replace("/", "-").replace(".", "-")
    year, month, day = normalized.split("-")
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"


def _standard_ref_identity(value: str) -> tuple[str, str, str] | None:
    references = standard_refs_from_text(canonical_standard_text(value))
    if len(references) != 1:
        return None
    reference = references[0]
    return (
        str(reference.get("prefix") or ""),
        str(reference.get("number") or ""),
        str(reference.get("year") or ""),
    )


def _standard_code_is_supported(value: str, quoted_text: str) -> bool:
    claimed = _standard_ref_identity(value)
    if claimed is None:
        return False
    quoted = {
        (
            str(reference.get("prefix") or ""),
            str(reference.get("number") or ""),
            str(reference.get("year") or ""),
        )
        for reference in standard_refs_from_text(canonical_standard_text(quoted_text))
    }
    return claimed in quoted


def _compact_semantic_text(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", _normalize_text(value)).lower()


def _substantive_trigrams(value: str) -> set[str]:
    compact = _compact_semantic_text(value)
    compact = _SCOPE_PREDICATE_STRIP_PATTERN.sub("", compact)
    for boilerplate in _SCOPE_BOILERPLATE:
        compact = compact.replace(boilerplate, "")
    return {compact[index : index + 3] for index in range(max(0, len(compact) - 2))}


def _scope_predicate_polarity(text: str, predicate_start: int) -> str:
    clause_start = 0
    for boundary in _SCOPE_SUBJECT_STOP_PATTERN.finditer(text, 0, predicate_start):
        clause_start = boundary.end()
    prefix = _compact_semantic_text(text[clause_start:predicate_start])

    strong_matches = [
        (prefix.rfind(marker), marker)
        for marker in _SCOPE_STRONG_NEGATION_MARKERS
        if marker in prefix
    ]
    if strong_matches:
        marker_start, marker = max(strong_matches, key=lambda item: item[0])
        gap = prefix[marker_start + len(marker) :]
        if len(gap) <= _SCOPE_MAX_PREDICATE_GAP and _SCOPE_NEGATION_GAP_PATTERN.fullmatch(gap):
            return "negative"
        return "ambiguous"

    weak_matches = [
        (prefix.rfind(marker), marker)
        for marker in _SCOPE_WEAK_NEGATION_MARKERS
        if marker in prefix
    ]
    if weak_matches:
        marker_start, marker = max(weak_matches, key=lambda item: item[0])
        gap = prefix[marker_start + len(marker) :]
        if len(gap) <= _SCOPE_MAX_PREDICATE_GAP and _SCOPE_NEGATION_GAP_PATTERN.fullmatch(gap):
            return "negative"
        return "ambiguous"
    return "positive"


def _scope_predicates(value: str) -> list[dict[str, str]]:
    text = _normalize_text(value)
    predicates: list[dict[str, str]] = []
    for matched in _SCOPE_PREDICATE_PATTERN.finditer(text):
        tail = text[matched.end() :]
        stop = _SCOPE_SUBJECT_STOP_PATTERN.search(tail)
        subject = tail[: stop.start() if stop else len(tail)]
        predicates.append(
            {
                "polarity": _scope_predicate_polarity(text, matched.start()),
                "subject": _compact_semantic_text(subject),
            }
        )
    return predicates


def _aggregate_scope_polarity(predicates: list[dict[str, str]]) -> str:
    polarities = {item["polarity"] for item in predicates}
    if "ambiguous" in polarities:
        return "ambiguous"
    if len(polarities) > 1:
        return "mixed"
    if polarities:
        return next(iter(polarities))
    return "neutral"


def _scope_subject_similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    if left == right:
        return 2.0
    if left in right or right in left:
        return 1.0
    left_tokens = {left[index : index + 3] for index in range(max(0, len(left) - 2))}
    right_tokens = {right[index : index + 3] for index in range(max(0, len(right) - 2))}
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / min(len(left_tokens), len(right_tokens))


def _shared_scope_predicates(
    value_predicates: list[dict[str, str]],
    quote_predicates: list[dict[str, str]],
) -> list[tuple[dict[str, str], dict[str, str]]]:
    candidates = sorted(
        (
            (
                _scope_subject_similarity(value_item["subject"], quote_item["subject"]),
                value_index,
                quote_index,
            )
            for value_index, value_item in enumerate(value_predicates)
            for quote_index, quote_item in enumerate(quote_predicates)
        ),
        reverse=True,
    )
    matched_values: set[int] = set()
    matched_quotes: set[int] = set()
    result: list[tuple[dict[str, str], dict[str, str]]] = []
    for score, value_index, quote_index in candidates:
        if score < 0.5:
            break
        if value_index in matched_values or quote_index in matched_quotes:
            continue
        matched_values.add(value_index)
        matched_quotes.add(quote_index)
        result.append((value_predicates[value_index], quote_predicates[quote_index]))
    return result


def _scope_evidence_signature(value: str, quoted_text: str) -> dict[str, Any]:
    value_predicates = _scope_predicates(value)
    quote_predicates = _scope_predicates(quoted_text)
    value_polarity = _aggregate_scope_polarity(value_predicates)
    quote_polarity = _aggregate_scope_polarity(quote_predicates)
    shared_predicates = _shared_scope_predicates(value_predicates, quote_predicates)
    exact_contradiction = any(
        value_item["subject"]
        and value_item["subject"] == quote_item["subject"]
        and value_item["polarity"] != quote_item["polarity"]
        for value_item in value_predicates
        for quote_item in quote_predicates
    )
    if not value_predicates and not quote_predicates:
        negation_matches = True
    else:
        negation_matches = (
            not any(
                item["polarity"] == "ambiguous" for item in [*value_predicates, *quote_predicates]
            )
            and not exact_contradiction
            and len(shared_predicates) == len(value_predicates)
            and all(
                value_item["polarity"] == quote_item["polarity"]
                for value_item, quote_item in shared_predicates
            )
        )
    return {
        "valuePolarity": value_polarity,
        "quotePolarity": quote_polarity,
        "negationMatches": negation_matches,
        "sharedSubstantiveTokens": sorted(
            _substantive_trigrams(value) & _substantive_trigrams(quoted_text)
        )[:32],
    }


def _scope_is_supported(value: str, quoted_text: str) -> bool:
    evidence = _scope_evidence_signature(value, quoted_text)
    if not evidence["negationMatches"]:
        return False
    if _scope_predicates(value) and _scope_predicates(quoted_text):
        return True
    compact_value = _compact_semantic_text(value)
    compact_quote = _compact_semantic_text(quoted_text)
    if min(len(compact_value), len(compact_quote)) < 4:
        return False
    if compact_value in compact_quote or compact_quote in compact_value:
        return True
    value_tokens = _substantive_trigrams(value)
    quote_tokens = _substantive_trigrams(quoted_text)
    shared = value_tokens & quote_tokens
    required = max(3, (min(len(value_tokens), len(quote_tokens)) + 2) // 3)
    return len(shared) >= required


def _exact_value_is_supported(key: str, value: str, quoted_text: str) -> bool:
    if key == "standardCode":
        return _standard_code_is_supported(value, quoted_text)
    if key in {"publicationDate", "effectiveDate"}:
        try:
            expected = _normalize_date(value)
        except (TypeError, ValueError):
            return False
        return any(
            _normalize_date(matched.group(1)) == expected
            for matched in _DATE_TOKEN_PATTERN.finditer(quoted_text)
        )
    if key in {"issuingAuthority", "standardNameZh", "standardNameEn"}:
        compact_value = _compact_semantic_text(value)
        compact_quote = _compact_semantic_text(quoted_text)
        return bool(compact_value) and compact_value in compact_quote
    if key == "scope":
        return _scope_is_supported(value, quoted_text)
    return True


def _identity_code_candidates(record: dict[str, Any]) -> list[tuple[int, str, str]]:
    candidates: list[tuple[int, str, str]] = []
    blocks = [item for item in record.get("blocks") or [] if isinstance(item, dict)]
    blocks = sorted(
        enumerate(blocks),
        key=lambda pair: (_positive_page_no(pair[1].get("pageNo")) or 10**9, pair[0]),
    )
    for _, block in blocks:
        if not _block_has_selected_mineru_source(block):
            continue
        page_no = _positive_page_no(block.get("pageNo"))
        text = _normalize_text(block.get("text"))
        if page_no is None or not text:
            continue
        spans: list[tuple[str, bool]] = []
        for label in _IDENTITY_LABEL_PATTERN.finditer(text):
            spans.append((text[label.end() : label.end() + 80], True))
        title = _normalize_text(block.get("title"))
        block_type = str(block.get("blockType") or block.get("type") or "").lower()
        raw_section_path = block.get("sectionPath")
        if isinstance(raw_section_path, (list, tuple)):
            section_tail = _normalize_text(raw_section_path[-1] if raw_section_path else "")
        else:
            normalized_path = _normalize_text(raw_section_path)
            section_tail = re.split(r"[/|>]", normalized_path)[-1].strip()
        context_text = " ".join((title, section_tail, text))
        excluded = any(marker in context_text for marker in _IDENTITY_EXCLUSION_MARKERS)
        named_front_matter = any(
            value.endswith(marker)
            for value in (title, section_tail)
            if value
            for marker in _IDENTITY_CONTEXT_TITLES
        )
        generic_identity = (
            block_type in _GENERIC_IDENTITY_BLOCK_TYPES
            and not excluded
            and bool(_POSITIVE_IDENTITY_PATTERN.search(text))
        )
        contextual = block_type in _IDENTITY_BLOCK_TYPES or named_front_matter or generic_identity
        if contextual:
            if title:
                spans.append((title, False))
            spans.append((text, False))
        for span, require_prefix in spans:
            for reference in standard_refs_from_text(span):
                value = display_standard_number(
                    str(reference.get("prefix") or ""),
                    str(reference.get("number") or ""),
                    str(reference.get("year") or ""),
                )
                compact_span = _compact_semantic_text(span)
                compact_value = _compact_semantic_text(value)
                if require_prefix and not compact_span.startswith(compact_value):
                    continue
                if any(
                    f"{relation}{compact_value}" in compact_span for relation in ("代替", "替代")
                ):
                    continue
                candidates.append((page_no, span, value))
    return candidates


def _candidate(
    record: dict[str, Any],
    *,
    value: Any,
    page_no: int | None,
    quoted_text: str,
    extraction_method: str,
) -> dict[str, Any]:
    return {
        "value": value,
        "sourceType": SOURCE_TYPE,
        "sourceId": _mineru_source_id(record),
        "parseResultId": _mineru_source_id(record),
        "documentVersionId": str(record.get("documentVersionId") or ""),
        "pageNo": page_no,
        "quotedText": quoted_text,
        "confidence": 1.0 if extraction_method == "deterministic" else None,
        "needsHumanVerification": False,
        "extractionMethod": extraction_method,
    }


def _append_unique(
    result: dict[str, list[dict[str, Any]]], key: str, candidate: dict[str, Any]
) -> None:
    existing = result.setdefault(key, [])
    if not any(item.get("value") == candidate.get("value") for item in existing):
        existing.append(candidate)


def extract_deterministic_standard_metadata(
    record: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    """Extract exact-format metadata directly from grounded new MinerU text."""
    result: dict[str, list[dict[str, Any]]] = {}
    code_candidates = _identity_code_candidates(record)
    for page_no, page_text in canonical_page_digest(record).items():
        for key, pattern in _DATE_PATTERNS.items():
            matched = pattern.search(page_text)
            if matched:
                _append_unique(
                    result,
                    key,
                    _candidate(
                        record,
                        value=_normalize_date(matched.group(1)),
                        page_no=page_no,
                        quoted_text=matched.group(0),
                        extraction_method="deterministic",
                    ),
                )
        authority = _AUTHORITY_PATTERN.search(page_text)
        if authority:
            value = authority.group(1).strip(" ,，")
            _append_unique(
                result,
                "issuingAuthority",
                _candidate(
                    record,
                    value=value,
                    page_no=page_no,
                    quoted_text=authority.group(0),
                    extraction_method="deterministic",
                ),
            )
        for matched in _REPLACEMENT_LABEL_PATTERN.finditer(page_text):
            target_text = page_text[matched.end() : matched.end() + 80]
            relation_text = page_text[matched.start() : matched.end() + 80]
            references = standard_refs_from_text(target_text)
            if not references:
                continue
            reference = references[0]
            target_code = display_standard_number(
                str(reference.get("prefix") or ""),
                str(reference.get("number") or ""),
                str(reference.get("year") or ""),
            )
            if not _compact_semantic_text(target_text).startswith(
                _compact_semantic_text(target_code)
            ):
                continue
            _append_unique(
                result,
                "replaces",
                _candidate(
                    record,
                    value=target_code,
                    page_no=page_no,
                    quoted_text=relation_text,
                    extraction_method="deterministic",
                ),
            )
    existing_code = _normalize_standard_code(
        str(((record.get("identity") or {}).get("standardCode") or {}).get("value") or "")
    )
    selected_code = next(
        (item for item in code_candidates if existing_code and item[2] == existing_code),
        code_candidates[0] if code_candidates else None,
    )
    if selected_code is not None:
        page_no, quoted_text, value = selected_code
        _append_unique(
            result,
            "standardCode",
            _candidate(
                record,
                value=value,
                page_no=page_no,
                quoted_text=quoted_text,
                extraction_method="deterministic",
            ),
        )
    return result


def _hash_payload(value: Any) -> str:
    normalized = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return "sha256:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def semantic_extraction_hashes(
    record: dict[str, Any], *, requested_fields: set[str] | None = None
) -> dict[str, str]:
    schema = _schema()
    allowed_fields = set(schema["required"])
    selected_fields = sorted(requested_fields if requested_fields is not None else allowed_fields)
    unsupported = set(selected_fields) - allowed_fields
    if unsupported:
        raise ValueError(f"unsupported requested semantic fields: {sorted(unsupported)}")
    prompt_descriptor = {
        "promptVersion": PROMPT_VERSION,
        "instruction": _PROMPT_INSTRUCTION,
        "requestedFields": selected_fields,
        "schema": schema,
    }
    content_descriptor = {
        "documentVersionId": record.get("documentVersionId"),
        "sourceFingerprint": record.get("sourceFingerprint"),
        "pages": canonical_page_digest(record),
    }
    return {
        "promptHash": _hash_payload(prompt_descriptor),
        "contentHash": _hash_payload(content_descriptor),
    }


def standard_extraction_messages(
    record: dict[str, Any],
    deterministic: dict[str, list[dict[str, Any]]],
    *,
    requested_fields: set[str] | None = None,
) -> list[dict[str, str]]:
    schema = _schema()
    fields = sorted(requested_fields if requested_fields is not None else schema["required"])
    payload = {
        "promptVersion": PROMPT_VERSION,
        "requestedFields": fields,
        "evidenceRequired": schema["evidenceRequired"],
        "deterministicValues": {
            key: [item.get("value") for item in values]
            for key, values in sorted(deterministic.items())
            if key in fields
        },
        "pages": canonical_page_digest(record),
    }
    return [
        {"role": "system", "content": _PROMPT_INSTRUCTION},
        {
            "role": "user",
            "content": json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        },
    ]


def _grounded_evidence(
    key: str,
    value: dict[str, Any],
    page_digest: dict[int, str],
) -> tuple[int, str]:
    raw_page_no = value.get("pageNo")
    raw_quoted_text = value.get("quotedText")
    if raw_page_no is None and not raw_quoted_text:
        raise ValueError(f"{key}: pageNo and quotedText are required")
    if isinstance(raw_page_no, bool) or not isinstance(raw_page_no, int) or raw_page_no <= 0:
        raise ValueError(f"{key}: pageNo must be a positive integer")
    page_no = raw_page_no
    if not isinstance(raw_quoted_text, str) or not raw_quoted_text.strip():
        raise ValueError(f"{key}: quotedText must be a non-empty string")
    quoted_text = raw_quoted_text.strip()
    page_text = page_digest.get(page_no)
    if not page_text or _normalize_text(quoted_text) not in _normalize_text(page_text):
        raise ValueError(f"{key}: quotedText is not grounded on page {page_no}")
    return page_no, quoted_text


def _validate_scalar(
    key: str,
    value: Any,
    *,
    evidence_required: bool,
    page_digest: dict[int, str],
) -> None:
    if value is None or value == "" or value == []:
        return
    if evidence_required:
        if not isinstance(value, dict):
            raise ValueError(f"{key}: pageNo and quotedText are required")
        unknown = set(value) - _EVIDENCE_VALUE_KEYS
        if unknown:
            raise ValueError(f"{key}: unsupported properties {sorted(unknown)}")
        scalar_value = value.get("value")
        if not isinstance(scalar_value, str) or not scalar_value.strip():
            raise ValueError(f"{key}: value must be a non-empty string")
        _, quoted_text = _grounded_evidence(key, value, page_digest)
        if not _exact_value_is_supported(key, scalar_value, quoted_text):
            raise ValueError(f"{key} is not supported by quotedText")
        return
    if isinstance(value, dict):
        unknown = set(value) - _EVIDENCE_VALUE_KEYS
        if unknown:
            raise ValueError(f"{key}: unsupported properties {sorted(unknown)}")
        if "pageNo" in value or "quotedText" in value:
            _grounded_evidence(key, value, page_digest)
        value = value.get("value")
    if key in _LIST_FIELDS:
        if not isinstance(value, list) or not all(
            isinstance(item, str) and item.strip() for item in value
        ):
            raise ValueError(f"{key}: value must be a list of non-empty strings")
    elif not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key}: value must be a non-empty string")


def _validate_relations(key: str, value: Any, page_digest: dict[int, str]) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{key}: value must be a list")
    allowed_keys = _NORMATIVE_KEYS if key == "normativeReferences" else _REPLACEMENT_KEYS
    accepted: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        path = f"{key}[{index}]"
        if not isinstance(item, dict):
            raise ValueError(f"{path}: value must be an object")
        unknown = set(item) - allowed_keys
        if unknown:
            raise ValueError(f"{path}: unsupported properties {sorted(unknown)}")
        if (
            not isinstance(item.get("standardCode"), str)
            or not str(item.get("standardCode")).strip()
        ):
            raise ValueError(f"{path}: standardCode must be a non-empty string")
        if _standard_ref_identity(str(item["standardCode"])) is None:
            continue
        for optional_key in ("standardName", "clauseNo"):
            if optional_key in item and not isinstance(item[optional_key], str):
                raise ValueError(f"{path}: {optional_key} must be a string")
        if item.get("standardName") and not _exact_value_is_supported(
            "standardNameZh",
            str(item["standardName"]),
            str(item.get("quotedText") or ""),
        ):
            raise ValueError(f"{path}: standardName is not supported by quotedText")
        if key == "replacementRelations" and item.get("relation") not in _REPLACEMENT_RELATIONS:
            raise ValueError(f"{path}: unsupported replacement relation")
        _, quoted_text = _grounded_evidence(path, item, page_digest)
        if not _standard_code_is_supported(str(item["standardCode"]), quoted_text):
            raise ValueError(f"{path}: standardCode is not supported by quotedText")
        accepted.append(item)
    return accepted


def validate_standard_semantics(
    payload: Any,
    page_digest: dict[int, str],
    *,
    requested_fields: set[str] | None = None,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("model response must be a strict JSON object")
    schema = _schema()
    allowed = set(schema["required"])
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError(f"unsupported semantic field: {sorted(unknown)}")
    if requested_fields is not None:
        unexpected = set(payload) - requested_fields
        if unexpected:
            raise ValueError(f"model returned unrequested semantic fields: {sorted(unexpected)}")
    evidence_required = set(schema["evidenceRequired"])
    validated = dict(payload)
    for key, value in payload.items():
        if key in _RELATION_FIELDS:
            validated[key] = _validate_relations(key, value, page_digest)
        else:
            _validate_scalar(
                key,
                value,
                evidence_required=key in evidence_required,
                page_digest=page_digest,
            )
    return validated


def _model_field_candidate(record: dict[str, Any], key: str, value: Any) -> dict[str, Any] | None:
    if value is None or value == "" or value == []:
        return None
    if isinstance(value, dict):
        scalar_value = value.get("value")
        page_no = _positive_page_no(value.get("pageNo"))
        quoted_text = str(value.get("quotedText") or "")
    else:
        scalar_value = value
        page_no = None
        quoted_text = ""
    candidate = _candidate(
        record,
        value=scalar_value,
        page_no=page_no,
        quoted_text=quoted_text,
        extraction_method="model",
    )
    if key == "scope":
        candidate["semanticEvidence"] = _scope_evidence_signature(
            str(scalar_value or ""),
            quoted_text,
        )
    return candidate


def _normative_candidate(
    record: dict[str, Any],
    item: dict[str, Any],
    *,
    source_standard_code: str,
) -> dict[str, Any]:
    standard_code = _normalize_standard_code(str(item["standardCode"]))
    return {
        **_candidate(
            record,
            value=standard_code,
            page_no=_positive_page_no(item.get("pageNo")),
            quoted_text=str(item.get("quotedText") or ""),
            extraction_method="model",
        ),
        "sourceStandardCode": source_standard_code,
        "targetStandardCode": standard_code,
        "targetStandardName": str(item.get("standardName") or ""),
        "targetClauseNo": str(item.get("clauseNo") or ""),
        "text": str(item.get("quotedText") or ""),
    }


def _replacement_candidate(
    record: dict[str, Any],
    item: dict[str, Any],
    *,
    extraction_method: str,
    source_standard_code: str,
) -> dict[str, Any]:
    standard_code = _normalize_standard_code(str(item["standardCode"]))
    return {
        **_candidate(
            record,
            value=standard_code,
            page_no=_positive_page_no(item.get("pageNo")),
            quoted_text=str(item.get("quotedText") or ""),
            extraction_method=extraction_method,
        ),
        "sourceStandardCode": source_standard_code,
        "targetStandardCode": standard_code,
        "purpose": str(item.get("relation") or "replaces"),
        "text": str(item.get("quotedText") or ""),
    }


def _replacement_relation_identity(item: dict[str, Any]) -> tuple[str, Any]:
    target_identity = _standard_ref_identity(str(item.get("targetStandardCode") or ""))
    return (
        str(item.get("purpose") or ""),
        target_identity
        if target_identity is not None
        else canonical_standard_text(item.get("targetStandardCode")).replace(" ", ""),
    )


def merge_deterministic_and_model_semantics(
    record: dict[str, Any],
    deterministic: dict[str, list[dict[str, Any]]],
    payload: dict[str, Any],
    *,
    requested_fields: set[str] | None = None,
) -> dict[str, Any]:
    hashes = semantic_extraction_hashes(record, requested_fields=requested_fields)
    result: dict[str, Any] = {
        "promptVersion": PROMPT_VERSION,
        "modelRoute": MODEL_ROUTE,
        **hashes,
    }
    allowed = set(_schema()["required"])
    fields = requested_fields if requested_fields is not None else allowed
    for key in sorted(fields - _RELATION_FIELDS):
        deterministic_values = deterministic.get(key) or []
        if deterministic_values:
            result[key] = deterministic_values[0]
            continue
        candidate = _model_field_candidate(record, key, payload.get(key))
        if candidate is not None:
            result[key] = candidate

    deterministic_replacements = deterministic.get("replaces") or []
    if deterministic_replacements and "replacementRelations" in fields:
        result["replaces"] = deterministic_replacements[0]

    selected_code = result.get("standardCode")
    source_standard_code = str(
        (selected_code or {}).get("value")
        or ((record.get("identity") or {}).get("standardCode") or {}).get("value")
        or ""
    ).strip()
    has_relations = (
        bool(payload.get("normativeReferences"))
        or bool(payload.get("replacementRelations"))
        or bool(deterministic_replacements)
    )
    if has_relations and not source_standard_code:
        raise ValueError("relations require source standardCode")

    if "normativeReferences" in fields:
        result["normativeReferences"] = [
            _normative_candidate(
                record,
                item,
                source_standard_code=source_standard_code,
            )
            for item in payload.get("normativeReferences") or []
        ]
    if "replacementRelations" in fields:
        deterministic_relation_candidates = [
            _replacement_candidate(
                record,
                {
                    "standardCode": item["value"],
                    "pageNo": item["pageNo"],
                    "quotedText": item["quotedText"],
                    "relation": "replaces",
                },
                extraction_method="deterministic",
                source_standard_code=source_standard_code,
            )
            for item in deterministic_replacements
        ]
        model_relation_candidates = [
            _replacement_candidate(
                record,
                item,
                extraction_method="model",
                source_standard_code=source_standard_code,
            )
            for item in payload.get("replacementRelations") or []
        ]
        merged_relations = {
            _replacement_relation_identity(item): item for item in model_relation_candidates
        }
        merged_relations.update(
            {
                _replacement_relation_identity(item): item
                for item in deterministic_relation_candidates
            }
        )
        result["replacementRelations"] = [
            merged_relations[key] for key in sorted(merged_relations, key=str)
        ]
    return result


def extract_standard_semantics(
    record: dict[str, Any],
    client: LiteLLMClient,
    *,
    requested_fields: set[str] | None = None,
) -> dict[str, Any]:
    page_digest = canonical_page_digest(record)
    if not page_digest:
        raise ValueError("canonical record has no page-addressable new MinerU text")
    deterministic = extract_deterministic_standard_metadata(record)
    if requested_fields is not None:
        deterministic = {
            key: values
            for key, values in deterministic.items()
            if key in requested_fields
            or (key == "replaces" and "replacementRelations" in requested_fields)
        }
    response = client.chat_sync(
        standard_extraction_messages(
            record,
            deterministic,
            requested_fields=requested_fields,
        ),
        model=MODEL_ROUTE,
        response_format={"type": "json_object"},
        temperature=0,
        max_tokens=8192,
    )
    try:
        payload = json.loads(client.first_message_text(response))
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("model response must be a strict JSON object") from exc
    payload = validate_standard_semantics(
        payload,
        page_digest,
        requested_fields=requested_fields,
    )
    return merge_deterministic_and_model_semantics(
        record,
        deterministic,
        payload,
        requested_fields=requested_fields,
    )
