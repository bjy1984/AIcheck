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
