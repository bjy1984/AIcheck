from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any


BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_KNOWLEDGE_PATH = BACKEND_ROOT / "config" / "material_classification_knowledge.json"
DEFAULT_MAPPING_PATH = BACKEND_ROOT / "config" / "material_review_points.json"
REQUIRED_TEXT_FIELDS = ("classificationDefinition", "documentPurpose", "basisLevel")
REQUIRED_LIST_FIELDS = (
    "materialTypeNames",
    "materialCategories",
    "titlePatterns",
    "requiredSignals",
    "supportingSignals",
    "negativeSignals",
    "confusableWith",
    "sourceRefs",
)


def _hash_payload(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def material_type_definitions_from_mapping(path: Path = DEFAULT_MAPPING_PATH) -> dict[str, dict[str, list[str]]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    grouped: dict[str, dict[str, set[str]]] = {}
    for item in payload.get("items") or []:
        code = str(item.get("materialTypeCode") or "").strip()
        if not code or item.get("enabled") is False:
            continue
        current = grouped.setdefault(code, {"materialTypeNames": set(), "materialCategories": set()})
        name = str(item.get("materialTypeName") or "").strip()
        category = str(item.get("materialCategory") or "").strip()
        if name:
            current["materialTypeNames"].add(name)
        if category:
            current["materialCategories"].add(category)
    return {
        code: {
            "materialTypeNames": sorted(values["materialTypeNames"]),
            "materialCategories": sorted(values["materialCategories"]),
        }
        for code, values in sorted(grouped.items())
    }


def validate_material_classification_knowledge(
    payload: dict[str, Any],
    *,
    expected_type_codes: set[str] | None = None,
    expected_definitions: dict[str, dict[str, list[str]]] | None = None,
) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []

    def add(code: str, message: str) -> None:
        errors.append({"code": code, "message": message})

    if not isinstance(payload, dict):
        return [{"code": "INVALID_PAYLOAD", "message": "knowledge payload must be an object"}]
    if not str(payload.get("schemaVersion") or "").strip():
        add("SCHEMA_VERSION_REQUIRED", "schemaVersion is required")
    if not str(payload.get("version") or "").strip():
        add("VERSION_REQUIRED", "version is required")
    cards = payload.get("cards")
    if not isinstance(cards, list):
        return [*errors, {"code": "CARDS_REQUIRED", "message": "cards must be an array"}]
    seen: set[str] = set()
    card_codes: set[str] = set()
    for index, card in enumerate(cards):
        if not isinstance(card, dict):
            add("INVALID_CARD", f"cards[{index}] must be an object")
            continue
        code = str(card.get("materialTypeCode") or "").strip()
        if not code:
            add("MATERIAL_TYPE_CODE_REQUIRED", f"cards[{index}] has no materialTypeCode")
            continue
        if code in seen:
            add("DUPLICATE_MATERIAL_TYPE", code)
        seen.add(code)
        card_codes.add(code)
        for field in REQUIRED_TEXT_FIELDS:
            if not str(card.get(field) or "").strip():
                add("REQUIRED_TEXT_MISSING", f"{code}.{field}")
        if card.get("basisLevel") not in {"standard_supported", "business_defined"}:
            add("INVALID_BASIS_LEVEL", code)
        targeting_mode = str(card.get("targetingMode") or "exact")
        if targeting_mode not in {"exact", "category_advisory"}:
            add("INVALID_TARGETING_MODE", code)
        for field in REQUIRED_LIST_FIELDS:
            if not isinstance(card.get(field), list):
                add("REQUIRED_LIST_MISSING", f"{code}.{field}")
        for field in ("materialTypeNames", "materialCategories", "titlePatterns", "requiredSignals", "supportingSignals"):
            if isinstance(card.get(field), list) and not card[field]:
                add("REQUIRED_LIST_EMPTY", f"{code}.{field}")
        for ref in card.get("sourceRefs") or []:
            if not isinstance(ref, dict) or not str(ref.get("document") or "").strip() or not str(ref.get("locator") or "").strip():
                add("INVALID_SOURCE_REF", code)
        if card.get("basisLevel") == "standard_supported" and not any(
            isinstance(ref, dict)
            and str(ref.get("document") or "").strip()
            and str(ref.get("document") or "").strip() != "docs/工程监检资料映射表.md"
            for ref in card.get("sourceRefs") or []
        ):
            add("STANDARD_SOURCE_REQUIRED", code)
        expected = (expected_definitions or {}).get(code)
        if expected:
            if sorted(card.get("materialTypeNames") or []) != sorted(expected.get("materialTypeNames") or []):
                add("MATERIAL_TYPE_NAME_MISMATCH", code)
            if sorted(card.get("materialCategories") or []) != sorted(expected.get("materialCategories") or []):
                add("MATERIAL_CATEGORY_MISMATCH", code)
        for confused in card.get("confusableWith") or []:
            confused_code = str(confused.get("materialTypeCode") or "").strip() if isinstance(confused, dict) else ""
            if not confused_code or not str(confused.get("distinction") or "").strip():
                add("INVALID_CONFUSION_RULE", code)
            elif expected_type_codes is not None and confused_code not in expected_type_codes:
                add("UNKNOWN_CONFUSABLE_TYPE", f"{code}->{confused_code}")
    if expected_type_codes is not None:
        for code in sorted(expected_type_codes - card_codes):
            add("MISSING_MATERIAL_TYPE", code)
        cards_by_code = {
            str(item.get("materialTypeCode") or ""): item
            for item in cards
            if isinstance(item, dict)
        }
        for code in sorted(card_codes - expected_type_codes):
            if str((cards_by_code.get(code) or {}).get("targetingMode") or "") != "category_advisory":
                add("UNKNOWN_MATERIAL_TYPE", code)
    return errors


def classification_knowledge_snapshot(
    path: Path = DEFAULT_KNOWLEDGE_PATH,
    *,
    mapping_path: Path = DEFAULT_MAPPING_PATH,
) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    expected_definitions = material_type_definitions_from_mapping(mapping_path)
    errors = validate_material_classification_knowledge(
        payload,
        expected_type_codes=set(expected_definitions),
        expected_definitions=expected_definitions,
    )
    if errors:
        summary = "; ".join(f"{item['code']}: {item['message']}" for item in errors[:10])
        raise ValueError(f"invalid material classification knowledge: {summary}")
    snapshot = deepcopy(payload)
    snapshot["schemaHash"] = _hash_payload(payload)
    return snapshot


def qwen_classification_knowledge_snapshot(
    path: Path = DEFAULT_KNOWLEDGE_PATH,
    *,
    mapping_path: Path = DEFAULT_MAPPING_PATH,
) -> dict[str, Any]:
    knowledge = classification_knowledge_snapshot(path, mapping_path=mapping_path)
    cards: list[dict[str, Any]] = []
    for card in knowledge["cards"]:
        projected = {
            "materialTypeCode": card["materialTypeCode"],
            "name": card["materialTypeNames"][0],
            "classificationDefinition": card["classificationDefinition"],
            "titlePatterns": deepcopy(card["titlePatterns"]),
            "requiredSignals": deepcopy(card["requiredSignals"]),
            "supportingSignals": deepcopy(card["supportingSignals"]),
        }
        if card.get("confusableWith"):
            projected["confusableWith"] = deepcopy(card["confusableWith"])
        cards.append(projected)
    return {
        "schemaVersion": "qwen-material-classification@1",
        "sourceVersion": knowledge["version"],
        "knowledgeSchemaHash": knowledge["schemaHash"],
        "materialTypes": cards,
    }


def classification_type_definition_snapshot(
    path: Path = DEFAULT_KNOWLEDGE_PATH,
    *,
    mapping_path: Path = DEFAULT_MAPPING_PATH,
) -> dict[str, Any]:
    knowledge = classification_knowledge_snapshot(path, mapping_path=mapping_path)
    mapping_payload = json.loads(mapping_path.read_text(encoding="utf-8"))
    mapping_by_code: dict[str, dict[str, set[Any]]] = {}
    for item in mapping_payload.get("items") or []:
        code = str(item.get("materialTypeCode") or "").strip()
        if not code or item.get("enabled") is False:
            continue
        current = mapping_by_code.setdefault(code, {"nodeIds": set(), "evidenceItems": set()})
        try:
            node_id = int(item.get("nodeId") or 0)
        except (TypeError, ValueError):
            node_id = 0
        if node_id > 0:
            current["nodeIds"].add(node_id)
        for evidence in item.get("evidenceItems") or []:
            text = str(evidence or "").strip()
            if text:
                current["evidenceItems"].add(text)
    material_types = []
    for card in knowledge["cards"]:
        mapped = mapping_by_code.get(card["materialTypeCode"]) or {"nodeIds": set(), "evidenceItems": set()}
        material_types.append(
            {
                "materialTypeCode": card["materialTypeCode"],
                "materialTypeNames": deepcopy(card["materialTypeNames"]),
                "materialCategories": deepcopy(card["materialCategories"]),
                "evidenceItems": sorted(mapped["evidenceItems"]),
                "nodeIds": sorted(mapped["nodeIds"]),
                "targetingMode": str(card.get("targetingMode") or "exact"),
            }
        )
    snapshot = {
        "schemaVersion": "document-classification-types@2",
        "sourceVersion": knowledge["version"],
        "mappingItemCount": int(mapping_payload.get("itemCount") or len(mapping_payload.get("items") or [])),
        "materialTypes": material_types,
    }
    return {**snapshot, "schemaHash": _hash_payload(snapshot)}
