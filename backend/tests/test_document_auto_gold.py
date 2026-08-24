from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from libs.db.repository import InMemoryRepository
from libs.document_auto_gold import (
    AutoGoldValidationError,
    build_gold_label_record,
    category_definition_snapshot,
    classification_response_format,
    supersede_gold_label_records,
    validate_classification_output,
    apply_material_type_gold_projection,
    build_material_type_gold_label_record,
    material_type_classification_response_format,
    material_type_definition_snapshot,
    validate_material_type_classification_output,
)


CONFIG = Path(__file__).resolve().parents[1] / "config" / "material_review_points.json"


def categories() -> list[str]:
    return [item["category"] for item in category_definition_snapshot(CONFIG)["categories"]]


def valid_output() -> dict:
    return {
        "labels": [
            {
                "category": "资质证照",
                "confidence": 0.96,
                "decisionSummary": "正文是特种设备生产许可证。",
                "contentEvidence": [
                    {
                        "quote": "中华人民共和国特种设备生产许可证",
                        "purpose": "证明文件属于资质证照",
                    }
                ],
            },
            {
                "category": "设计基础资料",
                "confidence": 0.78,
                "decisionSummary": "正文包含压力管道设计表格。",
                "contentEvidence": [
                    {
                        "quote": "压力管道设计 | 公用管道（GB1、GB2）",
                        "purpose": "证明文件包含设计范围",
                    }
                ],
            },
        ],
        "documentSummary": "压力管道设计许可证",
        "classificationComplete": True,
        "unclassifiedReason": None,
    }


MARKDOWN = """# 中华人民共和国特种设备生产许可证

| 许可项目 | 许可子项目 |
| --- | --- |
| 压力管道设计 | 公用管道（GB1、GB2） |
"""


def test_category_snapshot_contains_exact_16_backend_categories():
    snapshot = category_definition_snapshot(CONFIG)

    assert len(snapshot["categories"]) == 16
    assert snapshot["schemaHash"].startswith("sha256:")
    assert "资质证照" in [item["category"] for item in snapshot["categories"]]
    assert all(item["materialTypeCodes"] for item in snapshot["categories"])


def test_category_snapshot_is_stable_for_same_source():
    assert category_definition_snapshot(CONFIG)["schemaHash"] == category_definition_snapshot(CONFIG)["schemaHash"]


def test_response_format_is_strict_json_schema_and_has_no_filename_fields():
    response_format = classification_response_format(categories())
    serialized = str(response_format)

    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["strict"] is True
    assert "fileName" not in serialized
    assert "relativeDirectory" not in serialized
    assert "filePath" not in serialized
    enum = response_format["json_schema"]["schema"]["properties"]["labels"]["items"]["properties"]["category"]["enum"]
    assert enum == categories()


def test_validate_accepts_multiple_grounded_labels():
    validated = validate_classification_output(valid_output(), MARKDOWN, categories())

    assert [item["category"] for item in validated["labels"]] == ["资质证照", "设计基础资料"]
    assert validated["labels"][0]["confidence"] == 0.96
    assert validated["classificationComplete"] is True


def test_validate_rejects_unknown_category():
    output = valid_output()
    output["labels"][0]["category"] = "不存在的大类"

    with pytest.raises(AutoGoldValidationError, match="UNKNOWN_CATEGORY"):
        validate_classification_output(output, MARKDOWN, categories())


def test_validate_rejects_duplicate_category():
    output = valid_output()
    output["labels"].append(deepcopy(output["labels"][0]))

    with pytest.raises(AutoGoldValidationError, match="DUPLICATE_CATEGORY"):
        validate_classification_output(output, MARKDOWN, categories())


def test_validate_rejects_quote_missing_from_markdown():
    output = valid_output()
    output["labels"][0]["contentEvidence"][0]["quote"] = "文件中不存在的原文"

    with pytest.raises(AutoGoldValidationError, match="UNGROUNDED_EVIDENCE"):
        validate_classification_output(output, MARKDOWN, categories())


def test_validate_matches_quote_after_whitespace_normalization_only():
    output = valid_output()
    output["labels"][0]["contentEvidence"][0]["quote"] = "中华人民共和国  特种设备\n生产许可证"

    validated = validate_classification_output(output, MARKDOWN, categories())

    assert validated["labels"][0]["contentEvidence"][0]["quote"].startswith("中华人民共和国")


def test_validate_does_not_accept_punctuation_rewrite_as_quote():
    output = valid_output()
    output["labels"][1]["contentEvidence"][0]["quote"] = "压力管道设计，公用管道（GB1、GB2）"

    with pytest.raises(AutoGoldValidationError, match="UNGROUNDED_EVIDENCE"):
        validate_classification_output(output, MARKDOWN, categories())


def test_validate_requires_evidence_for_every_label():
    output = valid_output()
    output["labels"][0]["contentEvidence"] = []

    with pytest.raises(AutoGoldValidationError, match="EVIDENCE_REQUIRED"):
        validate_classification_output(output, MARKDOWN, categories())


def test_gold_record_keeps_all_lineage_hashes_and_multi_labels():
    labels = validate_classification_output(valid_output(), MARKDOWN, categories())["labels"]

    gold = build_gold_label_record(
        document_id="DOC-1",
        document_version_id="DV-1-V1",
        ocr_parse_result_id="PARSE-1",
        classification_run_id="DCR-1",
        labels=labels,
        model="qwen3.8-max",
        prompt_hash="sha256:prompt",
        markdown_sha256="sha256:markdown",
        category_schema_hash="sha256:categories",
        gold_version=2,
    )

    assert gold["source"] == "qwen_auto_gold"
    assert gold["primaryCategory"] == "资质证照"
    assert len(gold["labels"]) == 2
    assert gold["model"] == "qwen3.8-max"
    assert gold["promptHash"] == "sha256:prompt"
    assert gold["markdownSha256"] == "sha256:markdown"
    assert gold["categorySchemaHash"] == "sha256:categories"
    assert gold["goldVersion"] == 2
    assert gold["status"] == "active"


def test_next_gold_version_supersedes_previous_without_mutating_it():
    old = {
        "id": "DGL-OLD",
        "documentId": "DOC-1",
        "documentVersionId": "DV-1-V1",
        "status": "active",
        "goldVersion": 1,
    }
    old_before = deepcopy(old)
    new = {
        "id": "DGL-NEW",
        "documentId": "DOC-1",
        "documentVersionId": "DV-1-V1",
        "status": "active",
        "goldVersion": 2,
    }

    records = supersede_gold_label_records([old], new)

    assert old == old_before
    assert records[0]["id"] == "DGL-NEW"
    assert records[0]["status"] == "active"
    assert records[1]["id"] == "DGL-OLD"
    assert records[1]["status"] == "superseded"
    assert records[1]["supersededByGoldLabelId"] == "DGL-NEW"


def test_material_type_snapshot_contains_exactly_60_types_and_derived_categories():
    snapshot = material_type_definition_snapshot(CONFIG)

    assert len(snapshot["materialTypes"]) == 60
    assert snapshot["mappingItemCount"] == 164
    assert sum(len(item["nodeIds"]) for item in snapshot["materialTypes"]) == 163
    by_code = {item["materialTypeCode"]: item for item in snapshot["materialTypes"]}
    assert by_code["design_license"]["materialCategories"] == ["资质证照"]
    assert by_code["pipeline_summary"]["materialCategories"] == ["设计与施工组织", "设计基础资料"]
    assert snapshot["schemaHash"].startswith("sha256:")


def test_material_type_response_schema_uses_only_60_code_enum():
    snapshot = material_type_definition_snapshot(CONFIG)
    codes = [item["materialTypeCode"] for item in snapshot["materialTypes"]]
    response_format = material_type_classification_response_format(codes)
    label_properties = response_format["json_schema"]["schema"]["properties"]["labels"]["items"]["properties"]

    assert label_properties["materialTypeCode"]["enum"] == codes
    assert "category" not in label_properties


def test_validate_material_types_accepts_multi_labels_and_derives_16_categories():
    snapshot = material_type_definition_snapshot(CONFIG)
    raw = {
        "labels": [
            {
                "materialTypeCode": "design_license",
                "confidence": 0.98,
                "decisionSummary": "正文是压力管道设计许可证。",
                "contentEvidence": [{"quote": "特种设备生产许可证", "purpose": "许可证标题"}],
            },
            {
                "materialTypeCode": "design_document",
                "confidence": 0.76,
                "decisionSummary": "正文包含压力管道设计内容。",
                "contentEvidence": [{"quote": "压力管道设计", "purpose": "设计内容"}],
            },
        ],
        "documentSummary": "压力管道设计资料",
        "classificationComplete": True,
        "unclassifiedReason": None,
    }

    validated = validate_material_type_classification_output(raw, MARKDOWN, snapshot)

    assert [item["materialTypeCode"] for item in validated["labels"]] == ["design_license", "design_document"]
    assert validated["labels"][0]["materialCategories"] == ["资质证照"]
    assert validated["materialCategoryLabels"] == ["设计基础资料", "资质证照"]


def test_validate_material_types_merges_duplicate_type_evidence_from_model():
    snapshot = material_type_definition_snapshot(CONFIG)
    raw = {
        "labels": [
            {
                "materialTypeCode": "design_license",
                "confidence": 0.91,
                "decisionSummary": "标题表明这是许可证。",
                "contentEvidence": [{"quote": "特种设备生产许可证", "purpose": "许可证标题"}],
            },
            {
                "materialTypeCode": "design_license",
                "confidence": 0.98,
                "decisionSummary": "许可项目表明这是设计许可证。",
                "contentEvidence": [{"quote": "压力管道设计", "purpose": "许可项目"}],
            },
        ],
        "documentSummary": "压力管道设计许可证",
        "classificationComplete": True,
        "unclassifiedReason": None,
    }

    validated = validate_material_type_classification_output(raw, MARKDOWN, snapshot)

    assert len(validated["labels"]) == 1
    assert validated["labels"][0]["materialTypeCode"] == "design_license"
    assert validated["labels"][0]["confidence"] == 0.98
    assert validated["labels"][0]["decisionSummary"] == "许可项目表明这是设计许可证。"
    assert [item["quote"] for item in validated["labels"][0]["contentEvidence"]] == [
        "特种设备生产许可证",
        "压力管道设计",
    ]


def test_material_type_gold_projects_multi_types_and_primary_type_without_guessing():
    repository = InMemoryRepository()
    document, version = repository.create_document("P-2026-HDCP-001", "任意文件.bin", "application/octet-stream")
    snapshot = material_type_definition_snapshot(CONFIG)
    validated = validate_material_type_classification_output(
        {
            "labels": [
                {
                    "materialTypeCode": "design_license",
                    "confidence": 0.98,
                    "decisionSummary": "许可证。",
                    "contentEvidence": [{"quote": "特种设备生产许可证", "purpose": "标题"}],
                },
                {
                    "materialTypeCode": "design_document",
                    "confidence": 0.76,
                    "decisionSummary": "设计内容。",
                    "contentEvidence": [{"quote": "压力管道设计", "purpose": "正文"}],
                },
            ],
            "documentSummary": "设计资料",
            "classificationComplete": True,
            "unclassifiedReason": None,
        },
        MARKDOWN,
        snapshot,
    )
    gold = build_material_type_gold_label_record(
        document_id=document["id"],
        document_version_id=version["id"],
        ocr_parse_result_id="PARSE-1",
        classification_run_id="DCR-1",
        validated=validated,
        model="qwen3.8-max",
        prompt_hash="sha256:prompt",
        markdown_sha256="sha256:markdown",
        material_type_schema_hash=snapshot["schemaHash"],
        gold_version=1,
    )

    projection = apply_material_type_gold_projection(repository, gold)

    assert gold["primaryMaterialTypeCode"] == "design_license"
    assert document["materialTypeLabels"] == ["design_license", "design_document"]
    assert document["materialTypeCode"] == "design_license"
    assert document["materialCategoryLabels"] == ["设计基础资料", "资质证照"]
    assert projection["status"] == "projected"
