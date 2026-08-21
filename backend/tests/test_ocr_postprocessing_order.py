from __future__ import annotations

from apps.worker import tasks
from libs.db.repository import InMemoryRepository
from libs.db.seed import PROJECT_ID


def test_shared_ocr_apply_classifies_before_downstream_processing(monkeypatch) -> None:
    repository = InMemoryRepository()
    document, version = repository.create_document(
        PROJECT_ID,
        "扫描件-shared-pipeline.pdf",
        "application/pdf",
    )
    result = {
        "parseResultId": "PARSE-SHARED-CLASSIFY",
        "status": "success",
        "outcomeStatus": "completed",
        "fileName": document["fileName"],
        "documentType": "design_license",
        "profileId": "design_license_v1",
        "fragments": [
            {
                "pageNo": 1,
                "text": "设计许可证机构名称 华东设计院 许可范围 压力管道设计",
                "bbox": [10, 10, 500, 80],
                "confidence": 0.96,
            }
        ],
        "fields": [],
        "tables": [],
        "seals": [],
        "quality": {"status": "usable", "blockingReasons": []},
    }
    job = repository.create_ocr_job_record(
        document_id=document["id"],
        version_id=version["id"],
        storage_key=version["storageKey"],
        file_name=document["fileName"],
        document_type="design_license",
        profile_id="design_license_v1",
    )
    repository.finish_ocr_job_record(job, result)
    monkeypatch.setattr(tasks, "repo", repository)
    monkeypatch.setattr(tasks, "sync_state_records", lambda *_args, **_kwargs: None)
    previous_ids = tasks.state_record_ids(
        tasks.ocr_result_state_records(document["id"], version["id"])
    )

    applied, intelligence = tasks.pipeline_apply_result(
        document["id"],
        version["id"],
        result,
        previous_ids,
    )

    knowledge_file = repository.knowledge_file_for_version(version["id"])
    assert applied["status"] == "success"
    assert intelligence["classification"]["materialTypeCode"] == "design_license"
    assert document["materialTypeCode"] == "design_license"
    assert knowledge_file is not None
    assert knowledge_file["materialTypeCode"] == "design_license"
