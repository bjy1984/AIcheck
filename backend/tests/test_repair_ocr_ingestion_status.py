from __future__ import annotations

from copy import deepcopy

import pytest

from libs.db.repository import InMemoryRepository
from scripts import repair_ocr_ingestion_status as repair_module
from scripts.repair_ocr_ingestion_status import apply_repairs, build_repairs


def incomplete_repository(
    *,
    fragments: list[dict] | None = None,
    tables: list[dict] | None = None,
) -> tuple[InMemoryRepository, dict, dict]:
    repository = InMemoryRepository()
    document, version = repository.create_document(
        "PRJ-001",
        "材料代用单.docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    document["currentOcrStatus"] = "抽取不完整"
    version["ocrStatus"] = "抽取不完整"
    version["sliceStatus"] = "未切片"
    version["vectorStatus"] = "未向量化"
    knowledge_file = repository.knowledge_file_for_version(version["id"])
    assert knowledge_file is not None
    knowledge_file["ocrStatus"] = "抽取不完整"
    knowledge_file["sliceStatus"] = "未切片"
    knowledge_file["vectorStatus"] = "未向量化"
    repository.state["ocr_parse_results"].append(
        {
            "id": "PARSE-REPAIR-1",
            "parseResultId": "PARSE-REPAIR-1",
            "documentId": document["id"],
            "documentVersionId": version["id"],
            "status": "success",
            "outcomeStatus": "partial",
            "fragments": fragments or [],
            "tables": tables or [],
            "fields": [],
            "seals": [],
            "quality": {
                "status": "needs_human_review",
                "reasons": ["REQUIRED_FIELD_MISSING", "SEAL_NOT_FOUND"],
            },
            "finishedAt": "2026-08-06 00:40:29",
        }
    )
    return repository, document, version


def test_dry_run_finds_usable_incomplete_without_mutating() -> None:
    repository, document, version = incomplete_repository(
        fragments=[{"text": "材料代用单"}]
    )
    before = deepcopy(repository.state)

    repairs = build_repairs(repository)

    assert repairs == [
        {
            "documentId": document["id"],
            "documentVersionId": version["id"],
            "fileName": document["fileName"],
            "ingestionStatus": "usable",
            "before": "抽取不完整",
            "after": "已识别",
        }
    ]
    assert repository.state == before


def test_apply_promotes_usable_result_and_is_idempotent() -> None:
    repository, document, version = incomplete_repository(
        fragments=[{"text": "材料代用单"}]
    )

    first = apply_repairs(repository, build_repairs(repository))
    second = apply_repairs(repository, build_repairs(repository))

    assert first == {"promotedCount": 1, "failedCount": 0, "taskCount": 2}
    assert second == {"promotedCount": 0, "failedCount": 0, "taskCount": 0}
    assert document["currentOcrStatus"] == "已识别"
    assert version["ocrStatus"] == "已识别"
    assert version["sliceStatus"] == "待切片"
    assert version["vectorStatus"] == "待向量化"
    knowledge_file = repository.knowledge_file_for_version(version["id"])
    assert knowledge_file is not None
    assert knowledge_file["ocrStatus"] == "已识别"
    task_types = {
        item.get("taskType")
        for item in repository.state["knowledge_tasks"]
        if item.get("documentVersionId") == version["id"]
    }
    assert task_types >= {"slice", "vector"}


def test_apply_marks_empty_result_failed_without_downstream_tasks() -> None:
    repository, document, version = incomplete_repository(
        fragments=[{"text": "  "}],
        tables=[{"rows": []}],
    )

    summary = apply_repairs(repository, build_repairs(repository))

    assert summary == {"promotedCount": 0, "failedCount": 1, "taskCount": 0}
    assert document["currentOcrStatus"] == "识别失败"
    assert version["ocrStatus"] == "识别失败"
    assert version["sliceStatus"] == "未切片"
    assert version["vectorStatus"] == "未向量化"
    assert not [
        item
        for item in repository.state["knowledge_tasks"]
        if item.get("documentVersionId") == version["id"]
        and item.get("taskType") in {"slice", "vector"}
    ]


def test_apply_preserves_completed_downstream_stages() -> None:
    repository, document, version = incomplete_repository(
        tables=[{"rows": [["材料", "规格"], ["20#", "DN50"]]}]
    )
    version["sliceStatus"] = "已切片"
    version["vectorStatus"] = "已向量化"
    knowledge_file = repository.knowledge_file_for_version(version["id"])
    assert knowledge_file is not None
    knowledge_file["sliceStatus"] = "已切片"
    knowledge_file["vectorStatus"] = "已向量化"

    summary = apply_repairs(repository, build_repairs(repository))

    assert summary["promotedCount"] == 1
    assert version["sliceStatus"] == "已切片"
    assert version["vectorStatus"] == "已向量化"
    assert knowledge_file["sliceStatus"] == "已切片"
    assert knowledge_file["vectorStatus"] == "已向量化"


def test_persist_repairs_upserts_only_changed_state_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, document, version = incomplete_repository(
        fragments=[{"text": "材料代用单"}]
    )
    persisted: list[dict[str, list[dict]]] = []
    monkeypatch.setattr(
        repair_module,
        "flush_state_records",
        lambda records: persisted.append(records),
    )

    summary = repair_module.persist_repairs(repository, build_repairs(repository))

    assert summary == {"promotedCount": 1, "failedCount": 0, "taskCount": 2}
    assert len(persisted) == 1
    assert set(persisted[0]) == {
        "documents",
        "versions",
        "knowledge_files",
        "knowledge_tasks",
    }
    assert persisted[0]["documents"] == [document]
    assert persisted[0]["versions"] == [version]
