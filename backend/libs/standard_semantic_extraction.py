"""Grounded semantic extraction for canonical standard-knowledge records."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

from libs.integrations.litellm_client import LiteLLMClient


BACKEND_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = BACKEND_ROOT / "config/standard_canonical_extraction_v1.json"
PROMPT_VERSION = "standard-canonical-extraction-v1"
MODEL_ROUTE = "review-chat"
SOURCE_TYPE = "new_mineru_semantic"

_CODE_PATTERN = re.compile(
    r"(?<![A-Z0-9])"
    r"([A-Z]{1,5}(?:\s*/\s*[A-Z])?(?:\s+[A-Z])?\s*"
    r"\d+(?:\.\d+)*\s*[-—－]\s*\d{4})"
    r"(?!\d)"
)
_DATE_VALUE = r"(\d{4}(?:[-./年])\d{1,2}(?:[-./月])\d{1,2}日?)"
_DATE_TOKEN_PATTERN = re.compile(_DATE_VALUE)
_DATE_PATTERNS = {
    "publicationDate": re.compile(rf"发布日期\s*[：:]?\s*{_DATE_VALUE}"),
    "effectiveDate": re.compile(rf"实施日期\s*[：:]?\s*{_DATE_VALUE}"),
}
_AUTHORITY_PATTERN = re.compile(
    r"(?:发布机构|发布部门|批准部门|批准发布部门)\s*[：:]?\s*([^。；;\n]{2,80})"
)
_REPLACEMENT_PATTERN = re.compile(rf"(?:代替|替代)\s*{_CODE_PATTERN.pattern}")
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
    return normalized


def _normalize_date(value: str) -> str:
    normalized = _normalize_text(value).replace("年", "-").replace("月", "-").replace("日", "")
    normalized = normalized.replace("/", "-").replace(".", "-")
    year, month, day = normalized.split("-")
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"


def _exact_value_is_supported(key: str, value: str, quoted_text: str) -> bool:
    if key == "standardCode":
        return _normalize_standard_code(value) in _normalize_standard_code(quoted_text)
    if key in {"publicationDate", "effectiveDate"}:
        try:
            expected = _normalize_date(value)
        except (TypeError, ValueError):
            return False
        return any(
            _normalize_date(matched.group(1)) == expected
            for matched in _DATE_TOKEN_PATTERN.finditer(quoted_text)
        )
    if key == "issuingAuthority":
        return _normalize_text(value) in _normalize_text(quoted_text)
    return True


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
    code_candidates: list[tuple[int, str, str]] = []
    for page_no, page_text in canonical_page_digest(record).items():
        for matched in _CODE_PATTERN.finditer(page_text):
            prefix = page_text[max(0, matched.start() - 12) : matched.start()]
            if re.search(r"(?:代替|替代)\s*$", prefix):
                continue
            code_candidates.append(
                (page_no, matched.group(1), _normalize_standard_code(matched.group(1)))
            )
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
        for matched in _REPLACEMENT_PATTERN.finditer(page_text):
            code_matches = list(_CODE_PATTERN.finditer(matched.group(0)))
            if not code_matches:
                continue
            _append_unique(
                result,
                "replaces",
                _candidate(
                    record,
                    value=_normalize_standard_code(code_matches[-1].group(1)),
                    page_no=page_no,
                    quoted_text=matched.group(0),
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


def _validate_relations(key: str, value: Any, page_digest: dict[int, str]) -> None:
    if value is None:
        return
    if not isinstance(value, list):
        raise ValueError(f"{key}: value must be a list")
    allowed_keys = _NORMATIVE_KEYS if key == "normativeReferences" else _REPLACEMENT_KEYS
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
        for optional_key in ("standardName", "clauseNo"):
            if optional_key in item and not isinstance(item[optional_key], str):
                raise ValueError(f"{path}: {optional_key} must be a string")
        if key == "replacementRelations" and item.get("relation") not in _REPLACEMENT_RELATIONS:
            raise ValueError(f"{path}: unsupported replacement relation")
        _, quoted_text = _grounded_evidence(path, item, page_digest)
        if _normalize_standard_code(str(item["standardCode"])) not in _normalize_standard_code(
            quoted_text
        ):
            raise ValueError(f"{path}: standardCode is not supported by quotedText")


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
    for key, value in payload.items():
        if key in _RELATION_FIELDS:
            _validate_relations(key, value, page_digest)
        else:
            _validate_scalar(
                key,
                value,
                evidence_required=key in evidence_required,
                page_digest=page_digest,
            )
    return payload


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
    return _candidate(
        record,
        value=scalar_value,
        page_no=page_no,
        quoted_text=quoted_text,
        extraction_method="model",
    )


def _normative_candidate(record: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    standard_code = _normalize_standard_code(str(item["standardCode"]))
    return {
        **_candidate(
            record,
            value=standard_code,
            page_no=_positive_page_no(item.get("pageNo")),
            quoted_text=str(item.get("quotedText") or ""),
            extraction_method="model",
        ),
        "sourceStandardCode": str(
            ((record.get("identity") or {}).get("standardCode") or {}).get("value") or ""
        ),
        "targetStandardCode": standard_code,
        "targetClauseNo": str(item.get("clauseNo") or ""),
        "text": str(item.get("quotedText") or ""),
    }


def _replacement_candidate(
    record: dict[str, Any], item: dict[str, Any], *, extraction_method: str
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
        "sourceStandardCode": str(
            ((record.get("identity") or {}).get("standardCode") or {}).get("value") or ""
        ),
        "targetStandardCode": standard_code,
        "purpose": str(item.get("relation") or "replaces"),
        "text": str(item.get("quotedText") or ""),
    }


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

    if "normativeReferences" in fields:
        result["normativeReferences"] = [
            _normative_candidate(record, item) for item in payload.get("normativeReferences") or []
        ]
    if "replacementRelations" in fields:
        if deterministic_replacements:
            result["replacementRelations"] = [
                _replacement_candidate(
                    record,
                    {
                        "standardCode": item["value"],
                        "pageNo": item["pageNo"],
                        "quotedText": item["quotedText"],
                        "relation": "replaces",
                    },
                    extraction_method="deterministic",
                )
                for item in deterministic_replacements
            ]
        else:
            result["replacementRelations"] = [
                _replacement_candidate(record, item, extraction_method="model")
                for item in payload.get("replacementRelations") or []
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
    validate_standard_semantics(
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
