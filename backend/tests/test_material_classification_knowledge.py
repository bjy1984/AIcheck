from __future__ import annotations

from pathlib import Path

from libs.document_auto_gold import material_type_definition_snapshot
from libs.material_classification_knowledge import (
    classification_type_definition_snapshot,
    classification_knowledge_snapshot,
    qwen_classification_knowledge_snapshot,
    validate_material_classification_knowledge,
)


BACKEND_ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_PATH = BACKEND_ROOT / "config" / "material_classification_knowledge.json"
MAPPING_PATH = BACKEND_ROOT / "config" / "material_review_points.json"


def test_knowledge_cards_cover_60_mapped_types_plus_one_category_advisory_type():
    snapshot = classification_knowledge_snapshot(KNOWLEDGE_PATH)
    expected_codes = {
        item["materialTypeCode"]
        for item in material_type_definition_snapshot(MAPPING_PATH)["materialTypes"]
    }

    card_codes = {item["materialTypeCode"] for item in snapshot["cards"]}
    assert len(snapshot["cards"]) == 61
    assert expected_codes < card_codes
    assert card_codes - expected_codes == {"component_compliance_checklist"}
    component = next(item for item in snapshot["cards"] if item["materialTypeCode"] == "component_compliance_checklist")
    assert component["materialCategories"] == ["材料验收与复验"]
    assert component["targetingMode"] == "category_advisory"
    assert snapshot["schemaHash"].startswith("sha256:")


def test_every_card_has_auditable_classification_signals_and_sources():
    snapshot = classification_knowledge_snapshot(KNOWLEDGE_PATH)

    for card in snapshot["cards"]:
        assert card["classificationDefinition"].strip()
        assert card["documentPurpose"].strip()
        assert card["titlePatterns"]
        assert card["requiredSignals"]
        assert card["supportingSignals"]
        assert isinstance(card["negativeSignals"], list)
        assert isinstance(card["confusableWith"], list)
        assert card["basisLevel"] in {"standard_supported", "business_defined"}
        assert card["sourceRefs"]
        assert all(ref.get("document") and ref.get("locator") for ref in card["sourceRefs"])


def test_cards_explain_high_risk_confusion_boundaries():
    cards = {
        item["materialTypeCode"]: item
        for item in classification_knowledge_snapshot(KNOWLEDGE_PATH)["cards"]
    }

    assert any(item["materialTypeCode"] == "construction_license" for item in cards["design_license"]["confusableWith"])
    assert "设计" in "".join(cards["design_license"]["requiredSignals"])
    assert any(item["materialTypeCode"] == "material_ndt_report" for item in cards["ndt_report"]["confusableWith"])
    assert "材料本体" in "".join(
        item["distinction"]
        for item in cards["ndt_report"]["confusableWith"]
        if item["materialTypeCode"] == "material_ndt_report"
    )
    assert any(item["materialTypeCode"] == "factory_inspection_report" for item in cards["quality_certificate"]["confusableWith"])


def test_validator_rejects_unknown_confusable_type():
    payload = classification_knowledge_snapshot(KNOWLEDGE_PATH)
    payload.pop("schemaHash")
    payload["cards"][0]["confusableWith"].append(
        {"materialTypeCode": "not_a_real_type", "distinction": "不存在的分类"}
    )

    errors = validate_material_classification_knowledge(
        payload,
        expected_type_codes={item["materialTypeCode"] for item in payload["cards"]},
    )

    assert "UNKNOWN_CONFUSABLE_TYPE" in {item["code"] for item in errors}


def test_validator_rejects_name_or_category_drift_from_runtime_mapping():
    payload = classification_knowledge_snapshot(KNOWLEDGE_PATH)
    payload.pop("schemaHash")
    design_license = next(item for item in payload["cards"] if item["materialTypeCode"] == "design_license")
    design_license["materialCategories"] = ["无损检测资料"]

    errors = validate_material_classification_knowledge(
        payload,
        expected_type_codes={item["materialTypeCode"] for item in payload["cards"]},
        expected_definitions={
            "design_license": {
                "materialTypeNames": ["设计单位许可证"],
                "materialCategories": ["资质证照"],
            }
        },
    )

    assert "MATERIAL_CATEGORY_MISMATCH" in {item["code"] for item in errors}


def test_validator_requires_a_standard_reference_for_standard_supported_cards():
    payload = classification_knowledge_snapshot(KNOWLEDGE_PATH)
    payload.pop("schemaHash")
    design_license = next(item for item in payload["cards"] if item["materialTypeCode"] == "design_license")
    design_license["sourceRefs"] = [
        {"document": "docs/工程监检资料映射表.md", "locator": "materialTypeCode=design_license"}
    ]

    errors = validate_material_classification_knowledge(
        payload,
        expected_type_codes={item["materialTypeCode"] for item in payload["cards"]},
    )

    assert "STANDARD_SOURCE_REQUIRED" in {item["code"] for item in errors}


def test_qwen_projection_keeps_classification_rules_but_excludes_audit_only_fields():
    projection = qwen_classification_knowledge_snapshot(KNOWLEDGE_PATH)
    serialized = str(projection)

    assert len(projection["materialTypes"]) == 61
    assert all(item.get("materialTypeCode") for item in projection["materialTypes"])
    assert all(item.get("classificationDefinition") for item in projection["materialTypes"])
    assert all(item.get("materialCategories") for item in projection["materialTypes"])
    assert "sourceRefs" not in serialized
    assert "negativeSignals" not in serialized
    assert "basisLevel" not in serialized
    assert "documentPurpose" not in serialized


def test_classification_type_snapshot_includes_advisory_type_without_adding_a_formal_mapping():
    snapshot = classification_type_definition_snapshot(KNOWLEDGE_PATH, mapping_path=MAPPING_PATH)
    by_code = {item["materialTypeCode"]: item for item in snapshot["materialTypes"]}

    assert len(by_code) == 61
    assert by_code["component_compliance_checklist"]["targetingMode"] == "category_advisory"
    assert by_code["component_compliance_checklist"]["nodeIds"] == []
    assert snapshot["mappingItemCount"] == 164
