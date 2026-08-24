from __future__ import annotations

import hashlib
import html
import json
import re
from difflib import SequenceMatcher
from copy import deepcopy
from pathlib import Path
from typing import Any
from uuid import uuid4

from libs.contracts.responses import server_time


MATERIAL_REVIEW_POINTS = Path(__file__).resolve().parents[1] / "config" / "material_review_points.json"
MAX_LABELS = 16
MAX_EVIDENCE_PER_LABEL = 12
CLASSIFIER_PROMPT_KEY = "document-material-classifier"
CLASSIFIER_PROMPT_VARIABLES = {"materialTypeDefinitionsJson", "ocrMarkdown"}
FORBIDDEN_CLASSIFIER_PROMPT_VARIABLES = {"fileName", "relativeDirectory", "filePath", "extension"}


class AutoGoldValidationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


def production_document_classifier_prompt(repo: Any, business_pack_id: str) -> dict[str, Any] | None:
    matches = [
        item
        for item in repo.state.get("prompt_templates", [])
        if isinstance(item, dict)
        and item.get("promptKey") == CLASSIFIER_PROMPT_KEY
        and item.get("businessPackId") == business_pack_id
        and item.get("status") in {"production", "已发布"}
    ]
    return deepcopy(matches[0]) if len(matches) == 1 else None


def classifier_prompt_validation_error(record: dict[str, Any]) -> str | None:
    if str(record.get("promptKey") or "") != CLASSIFIER_PROMPT_KEY:
        return None
    variables = {str(value or "").strip() for value in record.get("variables") or [] if str(value or "").strip()}
    forbidden = sorted(variables & FORBIDDEN_CLASSIFIER_PROMPT_VARIABLES)
    if forbidden:
        return "文件资料分类 Prompt 不得使用文件名或路径变量：" + "、".join(forbidden)
    prompt_text = "\n".join(
        str(record.get(key) or "")
        for key in ("systemPrompt", "userPromptTemplate", "plannerPromptTemplate", "criticPromptTemplate")
    )
    forbidden_placeholders = sorted(
        variable
        for variable in FORBIDDEN_CLASSIFIER_PROMPT_VARIABLES
        if "{{" + variable + "}}" in prompt_text
    )
    if forbidden_placeholders:
        return "文件资料分类 Prompt 正文不得引用文件名或路径占位符：" + "、".join(forbidden_placeholders)
    missing = sorted(CLASSIFIER_PROMPT_VARIABLES - variables)
    if missing:
        return "文件资料分类 Prompt 缺少必需变量：" + "、".join(missing)
    return None


def _walk_material_items(value: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if value.get("materialCategory") and value.get("materialTypeCode"):
            items.append(value)
        for nested in value.values():
            items.extend(_walk_material_items(nested))
    elif isinstance(value, list):
        for nested in value:
            items.extend(_walk_material_items(nested))
    return items


def _sha256_json(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def stable_json_hash(value: Any) -> str:
    return _sha256_json(value)


def render_classifier_messages(
    prompt: dict[str, Any],
    *,
    category_definitions_json: str = "",
    material_type_definitions_json: str = "",
    ocr_markdown: str,
) -> list[dict[str, str]]:
    user_template = str(prompt.get("userPromptTemplate") or "")
    rendered_user = (
        user_template.replace("{{categoryDefinitionsJson}}", category_definitions_json)
        .replace("{{materialTypeDefinitionsJson}}", material_type_definitions_json)
        .replace("{{ocrMarkdown}}", ocr_markdown)
    )
    return [
        {"role": "system", "content": str(prompt.get("systemPrompt") or "")},
        {"role": "user", "content": rendered_user},
    ]


def apply_auto_gold_projection(repo: Any, gold: dict[str, Any]) -> dict[str, Any]:
    document = repo.find_one("documents", str(gold.get("documentId") or ""))
    if not document:
        return {"status": "missing_document"}
    labels = [item for item in gold.get("labels") or [] if isinstance(item, dict)]
    categories = [str(item.get("category") or "") for item in labels if item.get("category")]
    confidence = max((float(item.get("confidence") or 0) for item in labels), default=0.0)
    now = server_time()
    projection = {
        "materialCategoryLabels": categories,
        "materialCategory": gold.get("primaryCategory"),
        "activeGoldLabelId": gold.get("id"),
        "classificationSource": "qwen_auto_gold",
        "classificationConfidence": confidence,
        "classifiedAt": now,
        "updatedAt": now,
    }
    document.update(deepcopy(projection))
    knowledge_file = repo.knowledge_file_for_version(str(gold.get("documentVersionId") or ""))
    if knowledge_file is not None:
        knowledge_file.update(deepcopy(projection))
    return {
        "status": "projected",
        "document": document,
        "knowledgeFile": knowledge_file,
    }


def document_classification_detail_view(repo: Any, document_id: str) -> dict[str, Any]:
    runs = sorted(
        [
            repo.clone(item)
            for item in repo.state.get("document_classification_runs", [])
            if item.get("documentId") == document_id
        ],
        key=lambda item: str(item.get("createdAt") or ""),
        reverse=True,
    )
    history = sorted(
        [
            repo.clone(item)
            for item in repo.state.get("document_gold_labels", [])
            if item.get("documentId") == document_id
        ],
        key=lambda item: int(item.get("goldVersion") or 0),
        reverse=True,
    )
    return {
        "classificationRuns": runs,
        "activeGoldLabel": next(
            (item for item in history if item.get("status") == "active"),
            None,
        ),
        "goldLabelHistory": history,
    }


def category_definition_snapshot(path: Path = MATERIAL_REVIEW_POINTS) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    grouped: dict[str, dict[str, set[str]]] = {}
    for item in _walk_material_items(payload):
        if item.get("enabled") is False:
            continue
        category = str(item.get("materialCategory") or "").strip()
        code = str(item.get("materialTypeCode") or "").strip()
        if not category or not code:
            continue
        group = grouped.setdefault(
            category,
            {"materialTypeCodes": set(), "materialTypeNames": set(), "evidenceItems": set()},
        )
        group["materialTypeCodes"].add(code)
        name = str(item.get("materialTypeName") or "").strip()
        if name:
            group["materialTypeNames"].add(name)
        for evidence in item.get("evidenceItems") or []:
            text = str(evidence or "").strip()
            if text:
                group["evidenceItems"].add(text)
    categories = [
        {
            "category": category,
            "materialTypeCodes": sorted(values["materialTypeCodes"]),
            "materialTypeNames": sorted(values["materialTypeNames"]),
            "evidenceItems": sorted(values["evidenceItems"]),
        }
        for category, values in sorted(grouped.items())
    ]
    snapshot = {
        "schemaVersion": "document-material-categories@1",
        "sourceVersion": str(payload.get("version") or ""),
        "categories": categories,
    }
    return {**snapshot, "schemaHash": _sha256_json(snapshot)}


def material_type_definition_snapshot(path: Path = MATERIAL_REVIEW_POINTS) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    grouped: dict[str, dict[str, set[Any]]] = {}
    for item in _walk_material_items(payload):
        if item.get("enabled") is False:
            continue
        code = str(item.get("materialTypeCode") or "").strip()
        if not code:
            continue
        group = grouped.setdefault(
            code,
            {
                "materialTypeNames": set(),
                "materialCategories": set(),
                "evidenceItems": set(),
                "nodeIds": set(),
            },
        )
        for key, target in (
            ("materialTypeName", "materialTypeNames"),
            ("materialCategory", "materialCategories"),
        ):
            value = str(item.get(key) or "").strip()
            if value:
                group[target].add(value)
        for evidence in item.get("evidenceItems") or []:
            value = str(evidence or "").strip()
            if value:
                group["evidenceItems"].add(value)
        try:
            node_id = int(item.get("nodeId") or 0)
        except (TypeError, ValueError):
            node_id = 0
        if node_id > 0:
            group["nodeIds"].add(node_id)
    material_types = [
        {
            "materialTypeCode": code,
            "materialTypeNames": sorted(values["materialTypeNames"]),
            "materialCategories": sorted(values["materialCategories"]),
            "evidenceItems": sorted(values["evidenceItems"]),
            "nodeIds": sorted(values["nodeIds"]),
        }
        for code, values in sorted(grouped.items())
    ]
    snapshot = {
        "schemaVersion": "document-material-types@1",
        "sourceVersion": str(payload.get("version") or ""),
        "mappingItemCount": int(payload.get("itemCount") or len(_walk_material_items(payload))),
        "materialTypes": material_types,
    }
    return {**snapshot, "schemaHash": _sha256_json(snapshot)}


def classification_response_format(categories: list[str]) -> dict[str, Any]:
    evidence_schema = {
        "type": "object",
        "properties": {
            "quote": {"type": "string", "minLength": 1},
            "purpose": {"type": "string", "minLength": 1},
        },
        "required": ["quote", "purpose"],
        "additionalProperties": False,
    }
    label_schema = {
        "type": "object",
        "properties": {
            "category": {"type": "string", "enum": list(categories)},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "decisionSummary": {"type": "string", "minLength": 1},
            "contentEvidence": {
                "type": "array",
                "minItems": 1,
                "maxItems": MAX_EVIDENCE_PER_LABEL,
                "items": evidence_schema,
            },
        },
        "required": ["category", "confidence", "decisionSummary", "contentEvidence"],
        "additionalProperties": False,
    }
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "document_material_classification",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "labels": {
                        "type": "array",
                        "maxItems": min(MAX_LABELS, len(categories)),
                        "items": label_schema,
                    },
                    "documentSummary": {"type": "string"},
                    "classificationComplete": {"type": "boolean"},
                    "unclassifiedReason": {"type": ["string", "null"]},
                },
                "required": ["labels", "documentSummary", "classificationComplete", "unclassifiedReason"],
                "additionalProperties": False,
            },
        },
    }


def material_type_classification_response_format(
    material_type_codes: list[str],
    material_categories: list[str] | None = None,
) -> dict[str, Any]:
    response_format = classification_response_format(material_type_codes)
    schema = response_format["json_schema"]["schema"]
    properties = schema["properties"]["labels"]["items"]["properties"]
    properties["materialTypeCode"] = properties.pop("category")
    properties["contentEvidence"]["maxItems"] = 2
    properties["contentEvidence"]["items"]["properties"]["quote"]["maxLength"] = 80
    required = schema["properties"]["labels"]["items"]["required"]
    required[required.index("category")] = "materialTypeCode"
    if material_categories is not None:
        schema["properties"]["fallbackMaterialCategories"] = {
            "type": "array",
            "maxItems": min(MAX_LABELS, len(material_categories)),
            "items": {"type": "string", "enum": list(material_categories)},
        }
        schema["required"].append("fallbackMaterialCategories")
    response_format["json_schema"]["name"] = "document_material_type_classification"
    return response_format


def _required_text(value: Any, *, code: str, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise AutoGoldValidationError(code, f"{field} must not be empty")
    return text


def _whitespace_normalized(value: str) -> str:
    return re.sub(r"\s+", "", value)


def _quote_is_grounded(quote: str, markdown: str) -> bool:
    if quote in markdown or _whitespace_normalized(quote) in _whitespace_normalized(markdown):
        return True
    visible_markdown = re.sub(r"<[^>]+>", " ", html.unescape(markdown))
    visible_quote = re.sub(r"<[^>]+>", " ", html.unescape(quote))
    return _whitespace_normalized(visible_quote) in _whitespace_normalized(visible_markdown)


def _canonical_grounded_span(quote: str, markdown: str) -> str | None:
    if _quote_is_grounded(quote, markdown):
        return quote
    if "..." in quote or "…" in quote:
        return None
    match = SequenceMatcher(None, quote, markdown).find_longest_match()
    span = markdown[match.b : match.b + match.size].strip()
    normalized_span = _whitespace_normalized(span)
    normalized_quote = _whitespace_normalized(quote)
    if len(normalized_span) < 6 or len(normalized_span) / max(len(normalized_quote), 1) < 0.7:
        return None
    return span if span in markdown else None


def validate_classification_output(
    raw: dict[str, Any],
    markdown: str,
    categories: list[str],
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise AutoGoldValidationError("INVALID_OUTPUT", "classification output must be an object")
    raw_labels = raw.get("labels")
    if not isinstance(raw_labels, list):
        raise AutoGoldValidationError("INVALID_LABELS", "labels must be an array")
    if len(raw_labels) > min(MAX_LABELS, len(categories)):
        raise AutoGoldValidationError("TOO_MANY_LABELS", "labels exceed the configured category count")
    allowed = set(categories)
    seen: set[str] = set()
    labels: list[dict[str, Any]] = []
    for raw_label in raw_labels:
        if not isinstance(raw_label, dict):
            raise AutoGoldValidationError("INVALID_LABEL", "label must be an object")
        category = _required_text(raw_label.get("category"), code="CATEGORY_REQUIRED", field="category")
        if category not in allowed:
            raise AutoGoldValidationError("UNKNOWN_CATEGORY", category)
        if category in seen:
            raise AutoGoldValidationError("DUPLICATE_CATEGORY", category)
        seen.add(category)
        try:
            confidence = float(raw_label.get("confidence"))
        except (TypeError, ValueError) as exc:
            raise AutoGoldValidationError("INVALID_CONFIDENCE", category) from exc
        if confidence < 0 or confidence > 1:
            raise AutoGoldValidationError("INVALID_CONFIDENCE", category)
        decision_summary = _required_text(
            raw_label.get("decisionSummary"),
            code="DECISION_SUMMARY_REQUIRED",
            field="decisionSummary",
        )
        raw_evidence = raw_label.get("contentEvidence")
        if not isinstance(raw_evidence, list) or not raw_evidence:
            raise AutoGoldValidationError("EVIDENCE_REQUIRED", category)
        if len(raw_evidence) > MAX_EVIDENCE_PER_LABEL:
            raise AutoGoldValidationError("TOO_MUCH_EVIDENCE", category)
        evidence: list[dict[str, str]] = []
        for raw_item in raw_evidence:
            if not isinstance(raw_item, dict):
                raise AutoGoldValidationError("INVALID_EVIDENCE", category)
            quote = _required_text(raw_item.get("quote"), code="EVIDENCE_QUOTE_REQUIRED", field="quote")
            purpose = _required_text(raw_item.get("purpose"), code="EVIDENCE_PURPOSE_REQUIRED", field="purpose")
            if not _quote_is_grounded(quote, markdown):
                raise AutoGoldValidationError("UNGROUNDED_EVIDENCE", quote)
            evidence.append({"quote": quote, "purpose": purpose})
        labels.append(
            {
                "category": category,
                "confidence": confidence,
                "decisionSummary": decision_summary,
                "contentEvidence": evidence,
            }
        )
    classification_complete = raw.get("classificationComplete")
    if not isinstance(classification_complete, bool):
        raise AutoGoldValidationError("INVALID_COMPLETION_STATUS", "classificationComplete must be boolean")
    unclassified_reason = raw.get("unclassifiedReason")
    if not labels and classification_complete and not str(unclassified_reason or "").strip():
        raise AutoGoldValidationError("UNCLASSIFIED_REASON_REQUIRED", "zero-label result requires a reason")
    return {
        "labels": labels,
        "documentSummary": str(raw.get("documentSummary") or "").strip(),
        "classificationComplete": classification_complete,
        "unclassifiedReason": str(unclassified_reason).strip() if unclassified_reason is not None else None,
    }


def validate_material_type_classification_output(
    raw: dict[str, Any],
    markdown: str,
    material_type_snapshot: dict[str, Any],
) -> dict[str, Any]:
    definitions = {
        str(item.get("materialTypeCode") or ""): item
        for item in material_type_snapshot.get("materialTypes") or []
        if item.get("materialTypeCode")
    }
    allowed_categories = {
        str(category)
        for definition in definitions.values()
        for category in definition.get("materialCategories") or []
        if str(category).strip()
    }
    raw_fallback_categories = raw.get("fallbackMaterialCategories") if isinstance(raw, dict) else []
    if raw_fallback_categories is None:
        raw_fallback_categories = []
    if not isinstance(raw_fallback_categories, list):
        raise AutoGoldValidationError("INVALID_FALLBACK_CATEGORIES", "fallbackMaterialCategories must be an array")
    fallback_categories: list[str] = []
    for value in raw_fallback_categories:
        category = str(value or "").strip()
        if category not in allowed_categories:
            raise AutoGoldValidationError("UNKNOWN_FALLBACK_CATEGORY", category)
        if category not in fallback_categories:
            fallback_categories.append(category)
    raw_labels = raw.get("labels") if isinstance(raw, dict) else None
    if not isinstance(raw_labels, list):
        raise AutoGoldValidationError("INVALID_LABELS", "labels must be an array")
    translated = deepcopy(raw)
    merged_labels: dict[str, dict[str, Any]] = {}
    for raw_label in raw_labels:
        if not isinstance(raw_label, dict):
            raise AutoGoldValidationError("INVALID_LABEL", "label must be an object")
        code = str(raw_label.get("materialTypeCode") or "").strip()
        candidate = {**raw_label, "category": code}
        existing = merged_labels.get(code)
        if existing is None:
            merged_labels[code] = candidate
            continue
        try:
            candidate_confidence = float(candidate.get("confidence"))
            existing_confidence = float(existing.get("confidence"))
        except (TypeError, ValueError):
            candidate_confidence = existing_confidence = 0.0
        if candidate_confidence > existing_confidence:
            existing["confidence"] = candidate.get("confidence")
            existing["decisionSummary"] = candidate.get("decisionSummary")
        evidence = list(existing.get("contentEvidence") or [])
        evidence_keys = {
            (str(item.get("quote") or ""), str(item.get("purpose") or ""))
            for item in evidence
            if isinstance(item, dict)
        }
        for item in candidate.get("contentEvidence") or []:
            key = (
                str(item.get("quote") or ""),
                str(item.get("purpose") or ""),
            ) if isinstance(item, dict) else None
            if key not in evidence_keys:
                evidence.append(item)
                evidence_keys.add(key)
        existing["contentEvidence"] = evidence
    for label in merged_labels.values():
        canonical_evidence: list[Any] = []
        invalid_evidence: list[Any] = []
        for item in label.get("contentEvidence") or []:
            if not isinstance(item, dict):
                invalid_evidence.append(item)
                continue
            quote = str(item.get("quote") or "").strip()
            canonical = _canonical_grounded_span(quote, markdown)
            if canonical:
                canonical_evidence.append({**item, "quote": canonical})
            else:
                invalid_evidence.append(item)
        label["contentEvidence"] = canonical_evidence or invalid_evidence
    translated["labels"] = list(merged_labels.values())
    validated = validate_classification_output(translated, markdown, sorted(definitions))
    labels: list[dict[str, Any]] = []
    categories: set[str] = set()
    for item in validated["labels"]:
        code = str(item.pop("category"))
        definition = definitions[code]
        material_categories = sorted(str(value) for value in definition.get("materialCategories") or [] if value)
        categories.update(material_categories)
        labels.append(
            {
                "materialTypeCode": code,
                "materialCategories": material_categories,
                "targetingMode": str(definition.get("targetingMode") or "exact"),
                **item,
            }
        )
    categories.update(fallback_categories)
    return {
        **validated,
        "labels": labels,
        "fallbackMaterialCategories": sorted(fallback_categories),
        "materialCategoryLabels": sorted(categories),
    }


def build_gold_label_record(
    *,
    document_id: str,
    document_version_id: str,
    ocr_parse_result_id: str,
    classification_run_id: str,
    labels: list[dict[str, Any]],
    model: str,
    prompt_hash: str,
    markdown_sha256: str,
    category_schema_hash: str,
    gold_version: int,
) -> dict[str, Any]:
    now = server_time()
    primary = max(labels, key=lambda item: float(item.get("confidence") or 0))["category"] if labels else None
    return {
        "id": f"DGL-{uuid4().hex[:12].upper()}",
        "documentId": document_id,
        "documentVersionId": document_version_id,
        "ocrParseResultId": ocr_parse_result_id,
        "classificationRunId": classification_run_id,
        "labels": deepcopy(labels),
        "primaryCategory": primary,
        "source": "qwen_auto_gold",
        "model": model,
        "promptHash": prompt_hash,
        "markdownSha256": markdown_sha256,
        "categorySchemaHash": category_schema_hash,
        "goldVersion": max(1, int(gold_version)),
        "status": "active",
        "createdAt": now,
        "updatedAt": now,
    }


def build_material_type_gold_label_record(
    *,
    document_id: str,
    document_version_id: str,
    ocr_parse_result_id: str,
    classification_run_id: str,
    validated: dict[str, Any],
    model: str,
    prompt_hash: str,
    markdown_sha256: str,
    material_type_schema_hash: str,
    gold_version: int,
) -> dict[str, Any]:
    labels = deepcopy(validated.get("labels") or [])
    primary = max(labels, key=lambda item: float(item.get("confidence") or 0))["materialTypeCode"] if labels else None
    now = server_time()
    return {
        "id": f"DGL-{uuid4().hex[:12].upper()}",
        "documentId": document_id,
        "documentVersionId": document_version_id,
        "ocrParseResultId": ocr_parse_result_id,
        "classificationRunId": classification_run_id,
        "labels": labels,
        "primaryMaterialTypeCode": primary,
        "materialCategoryLabels": deepcopy(validated.get("materialCategoryLabels") or []),
        "fallbackMaterialCategories": deepcopy(validated.get("fallbackMaterialCategories") or []),
        "classificationTargetingMode": (
            "category_advisory"
            if validated.get("fallbackMaterialCategories")
            or any(item.get("targetingMode") == "category_advisory" for item in labels)
            else "exact"
        ),
        "source": "qwen_auto_gold",
        "model": model,
        "promptHash": prompt_hash,
        "markdownSha256": markdown_sha256,
        "materialTypeSchemaHash": material_type_schema_hash,
        "goldVersion": max(1, int(gold_version)),
        "status": "active",
        "createdAt": now,
        "updatedAt": now,
    }


def apply_material_type_gold_projection(repo: Any, gold: dict[str, Any]) -> dict[str, Any]:
    document = repo.find_one("documents", str(gold.get("documentId") or ""))
    if not document:
        return {"status": "missing_document"}
    labels = [item for item in gold.get("labels") or [] if isinstance(item, dict)]
    type_codes = [str(item.get("materialTypeCode") or "") for item in labels if item.get("materialTypeCode")]
    confidence = max((float(item.get("confidence") or 0) for item in labels), default=0.0)
    now = server_time()
    projection = {
        "materialTypeLabels": type_codes,
        "materialTypeCode": gold.get("primaryMaterialTypeCode") or "unclassified_material",
        "materialCategoryLabels": deepcopy(gold.get("materialCategoryLabels") or []),
        "materialCategory": (gold.get("materialCategoryLabels") or [None])[0],
        "activeGoldLabelId": gold.get("id"),
        "classificationSource": "qwen_auto_gold",
        "classificationConfidence": confidence,
        "classificationTargetingMode": str(gold.get("classificationTargetingMode") or "exact"),
        "classifiedAt": now,
        "updatedAt": now,
    }
    document.update(deepcopy(projection))
    knowledge_file = repo.knowledge_file_for_version(str(gold.get("documentVersionId") or ""))
    if knowledge_file is not None:
        knowledge_file.update(deepcopy(projection))
    return {"status": "projected", "document": document, "knowledgeFile": knowledge_file}


def supersede_gold_label_records(
    existing_records: list[dict[str, Any]],
    new_record: dict[str, Any],
) -> list[dict[str, Any]]:
    now = server_time()
    records = [deepcopy(new_record)]
    for source in existing_records:
        record = deepcopy(source)
        if (
            record.get("documentId") == new_record.get("documentId")
            and record.get("status") == "active"
            and record.get("id") != new_record.get("id")
        ):
            record["status"] = "superseded"
            record["supersededAt"] = now
            record["supersededByGoldLabelId"] = new_record.get("id")
            record["updatedAt"] = now
        records.append(record)
    return records
