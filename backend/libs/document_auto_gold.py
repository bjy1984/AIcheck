from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any
from uuid import uuid4

from libs.contracts.responses import server_time


MATERIAL_REVIEW_POINTS = Path(__file__).resolve().parents[1] / "config" / "material_review_points.json"
MAX_LABELS = 16
MAX_EVIDENCE_PER_LABEL = 12
CLASSIFIER_PROMPT_KEY = "document-material-classifier"
CLASSIFIER_PROMPT_VARIABLES = {"categoryDefinitionsJson", "ocrMarkdown"}
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
    category_definitions_json: str,
    ocr_markdown: str,
) -> list[dict[str, str]]:
    user_template = str(prompt.get("userPromptTemplate") or "")
    rendered_user = user_template.replace("{{categoryDefinitionsJson}}", category_definitions_json).replace(
        "{{ocrMarkdown}}", ocr_markdown
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


def _required_text(value: Any, *, code: str, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise AutoGoldValidationError(code, f"{field} must not be empty")
    return text


def _whitespace_normalized(value: str) -> str:
    return re.sub(r"\s+", "", value)


def _quote_is_grounded(quote: str, markdown: str) -> bool:
    return quote in markdown or _whitespace_normalized(quote) in _whitespace_normalized(markdown)


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
