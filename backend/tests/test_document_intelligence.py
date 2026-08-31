from __future__ import annotations

from libs.db.repository import InMemoryRepository
from libs.db.seed import PROJECT_ID


def _apply_ocr(
    repository: InMemoryRepository,
    *,
    document: dict,
    version: dict,
    text: str,
    document_type: str = "",
    profile_id: str = "",
) -> None:
    result = {
        "status": "success",
        "fileName": document["fileName"],
        "documentType": document_type,
        "profileId": profile_id,
        "fragments": [
            {
                "pageNo": 1,
                "text": text,
                "bbox": [10.0, 10.0, 560.0, 180.0],
                "confidence": 0.96,
            }
        ],
        "fields": [],
        "tables": [],
        "seals": [],
    }
    job = repository.create_ocr_job_record(
        document_id=document["id"],
        version_id=version["id"],
        storage_key=version["storageKey"],
        file_name=document["fileName"],
        document_type=document_type or None,
        profile_id=profile_id or None,
    )
    repository.finish_ocr_job_record(job, result)
    applied = repository.apply_ocr_result(document["id"], version["id"], result)
    assert applied["status"] == "success"


def test_post_ocr_classification_updates_document_and_knowledge_file() -> None:
    from libs.document_intelligence import process_document_classification_and_targeting

    repository = InMemoryRepository()
    document, version = repository.create_document(
        PROJECT_ID,
        "设计单位许可证.pdf",
        "application/pdf",
    )
    _apply_ocr(
        repository,
        document=document,
        version=version,
        document_type="design_license",
        profile_id="design_license_v1",
        text="设计许可证机构名称 华东设计院 许可范围 压力管道设计",
    )

    result = process_document_classification_and_targeting(
        repository,
        PROJECT_ID,
        document["id"],
        version["id"],
        triggered_by="test",
    )

    knowledge_file = repository.knowledge_file_for_version(version["id"])
    assert result["classification"]["materialTypeCode"] == "design_license"
    assert document["materialTypeCode"] == "design_license"
    assert document["classificationStatus"] == "classified"
    assert knowledge_file is not None
    assert knowledge_file["materialTypeCode"] == "design_license"
    assert knowledge_file["classificationStatus"] == "classified"


def test_llm_classification_override_skips_rule_classifier_and_targets_once(monkeypatch) -> None:
    from libs import document_intelligence

    repository = InMemoryRepository()
    document, version = repository.create_document(
        PROJECT_ID,
        "扫描件001.pdf",
        "application/pdf",
    )
    _apply_ocr(
        repository,
        document=document,
        version=version,
        text="特种设备设计许可证 许可项目 压力管道设计",
    )

    def unexpected_rule_classifier(**_kwargs):
        raise AssertionError("LLM 分类成功后不应再次执行规则分类")

    targeting_calls: list[dict] = []

    def record_targeting(*_args, **kwargs):
        targeting_calls.append(kwargs)
        return {
            "id": "MTR-LLM-1",
            "status": "completed",
            "createdLinks": [],
            "createdLinkCount": 0,
            "createdBindingCount": 0,
        }

    monkeypatch.setattr(document_intelligence, "classify_material", unexpected_rule_classifier)
    monkeypatch.setattr(document_intelligence, "run_material_targeting", record_targeting)
    llm_classification = {
        "materialCategory": "资质证照",
        "materialTypeCode": "design_license",
        "materialTypeName": "设计单位许可证",
        "classificationStatus": "classified",
        "classificationConfidence": 0.97,
        "classificationSource": "llm_classifier",
        "classificationReasons": ["OCR 原文包含设计许可项目"],
        "classifierVersion": "llm-material-classifier-v1",
    }

    result = document_intelligence.process_document_classification_and_targeting(
        repository,
        PROJECT_ID,
        document["id"],
        version["id"],
        triggered_by="llm_classifier",
        classification_override=llm_classification,
    )

    knowledge_file = repository.knowledge_file_for_version(version["id"])
    assert result["classification"] == llm_classification
    assert document["materialTypeCode"] == "design_license"
    assert document["classificationSource"] == "llm_classifier"
    assert knowledge_file is not None
    assert knowledge_file["materialTypeCode"] == "design_license"
    assert len(targeting_calls) == 1


def test_classification_text_excludes_ocr_metadata_and_identifiers() -> None:
    from libs.document_intelligence import classification_text

    text = classification_text(
        {
            "fragments": [
                {
                    "candidateId": "MINERU-CAND-SECRET",
                    "sourceCandidateIds": ["MINERU-CAND-SECRET"],
                    "pageNo": 1,
                    "confidence": 0.96,
                    "sourceEngine": "mineru_vlm",
                    "sourceMethod": "pymupdf_text_layer_block",
                    "ocrEngine": "pymupdf_text_layer",
                    "candidateType": "text_line",
                    "status": "success",
                    "coordinateSystem": "rendered_pixels",
                    "text": "特种设备设计许可证",
                }
            ],
            "fields": [],
            "tables": [
                {
                    "rows": [
                        {
                            "text": "表格中的许可范围",
                            "status": "success",
                            "sourceMethod": "pymupdf_text_layer_block",
                            "ocrEngine": "pymupdf",
                        }
                    ]
                }
            ],
            "seals": [],
        }
    )

    assert text == "特种设备设计许可证 表格中的许可范围"


def test_zero_signal_persists_uniform_unclassified_result() -> None:
    from libs.document_intelligence import process_document_classification_and_targeting

    repository = InMemoryRepository()
    document, version = repository.create_document(
        PROJECT_ID,
        "扫描件001.pdf",
        "application/pdf",
    )
    _apply_ocr(
        repository,
        document=document,
        version=version,
        text="第1页 001 002 003",
    )

    result = process_document_classification_and_targeting(
        repository,
        PROJECT_ID,
        document["id"],
        version["id"],
        triggered_by="test",
    )

    knowledge_file = repository.knowledge_file_for_version(version["id"])
    assert result["classification"]["materialTypeCode"] == "unclassified_material"
    assert result["targeting"]["status"] == "skipped_unclassified"
    assert document["materialCategory"] == "未分类资料"
    assert knowledge_file is not None
    assert knowledge_file["materialTypeCode"] == "unclassified_material"


def test_classifier_exception_falls_back_without_blocking_postprocessing(monkeypatch) -> None:
    import libs.document_intelligence as intelligence

    repository = InMemoryRepository()
    document, version = repository.create_document(
        PROJECT_ID,
        "异常分类样本.pdf",
        "application/pdf",
    )
    _apply_ocr(
        repository,
        document=document,
        version=version,
        text="可正常切片的工程资料正文",
    )

    def broken_classifier(**_kwargs):
        raise RuntimeError("classifier unavailable")

    monkeypatch.setattr(intelligence, "classify_material", broken_classifier)

    result = intelligence.process_document_classification_and_targeting(
        repository,
        PROJECT_ID,
        document["id"],
        version["id"],
        triggered_by="test",
    )

    assert result["status"] == "completed"
    assert result["classification"]["materialTypeCode"] == "unclassified_material"
    assert result["classification"]["classificationError"] == "RuntimeError"
    assert document["classificationStatus"] == "unclassified"

    monkeypatch.setattr(
        intelligence,
        "classify_material",
        lambda **_kwargs: {
            "materialCategory": "资质证照",
            "materialTypeCode": "design_license",
            "materialTypeName": "设计单位许可证",
            "matchedBy": "documentType",
            "reason": "OCR文档类型精确匹配",
            "classificationStatus": "classified",
            "classificationConfidence": 1.0,
            "classificationSource": "ocr_classifier",
            "classificationReasons": ["OCR文档类型精确匹配"],
            "classifierVersion": "material-classifier-v2",
        },
    )
    recovered = intelligence.process_document_classification_and_targeting(
        repository,
        PROJECT_ID,
        document["id"],
        version["id"],
        triggered_by="test-retry",
    )
    knowledge_file = repository.knowledge_file_for_version(version["id"])
    assert recovered["classification"]["materialTypeCode"] == "design_license"
    assert "classificationError" not in document
    assert knowledge_file is not None
    assert "classificationError" not in knowledge_file


def test_document_intelligence_rejects_version_from_another_document() -> None:
    from libs.document_intelligence import process_document_classification_and_targeting

    repository = InMemoryRepository()
    document, _version = repository.create_document(
        PROJECT_ID,
        "目标文档.pdf",
        "application/pdf",
    )
    other_document, other_version = repository.create_document(
        PROJECT_ID,
        "其他文档.pdf",
        "application/pdf",
    )
    _apply_ocr(
        repository,
        document=other_document,
        version=other_version,
        document_type="design_license",
        text="设计单位许可证",
    )
    before = repository.clone(document)

    result = process_document_classification_and_targeting(
        repository,
        PROJECT_ID,
        document["id"],
        other_version["id"],
        triggered_by="test",
    )

    assert result["status"] == "version_mismatch"
    assert document == before


def test_late_old_version_ocr_does_not_overwrite_current_document_classification() -> None:
    from libs.document_intelligence import process_document_classification_and_targeting

    repository = InMemoryRepository()
    document, old_version = repository.create_document(
        PROJECT_ID,
        "历史版本.pdf",
        "application/pdf",
    )
    _apply_ocr(
        repository,
        document=document,
        version=old_version,
        document_type="design_license",
        text="设计单位许可证",
    )
    current_version = repository.next_document_version(document, file_name="当前版本.pdf")
    document.update(
        {
            "materialTypeCode": "quality_certificate",
            "materialTypeName": "产品质量证明书",
            "classificationStatus": "classified",
        }
    )

    result = process_document_classification_and_targeting(
        repository,
        PROJECT_ID,
        document["id"],
        old_version["id"],
        triggered_by="late-ocr",
    )

    assert result["status"] == "stale_version"
    assert document["currentVersionId"] == current_version["id"]
    assert document["materialTypeCode"] == "quality_certificate"
