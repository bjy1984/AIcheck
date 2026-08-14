from __future__ import annotations

import argparse
import json
from typing import Any

from libs.contracts.responses import server_time
from libs.db.repository import (
    InMemoryRepository,
    flush_state_records,
    load_state,
    repo,
)
from libs.ocr_readiness import parse_result_ingestion_status

REPAIR_COLLECTIONS = {
    "documents",
    "versions",
    "knowledge_files",
    "knowledge_sources",
    "knowledge_tasks",
    "ocr_parse_results",
}


def _latest_parse_result(
    repository: InMemoryRepository,
    version_id: str,
) -> dict[str, Any] | None:
    matches = [
        item
        for item in repository.state.get("ocr_parse_results", [])
        if str(item.get("documentVersionId") or "") == version_id
    ]
    if not matches:
        return None
    return max(
        matches,
        key=lambda item: str(item.get("finishedAt") or item.get("createdAt") or ""),
    )


def build_repairs(repository: InMemoryRepository) -> list[dict[str, Any]]:
    repairs: list[dict[str, Any]] = []
    for document in repository.state.get("documents", []):
        if str(document.get("currentOcrStatus") or "") != "抽取不完整":
            continue
        version_id = str(document.get("currentVersionId") or "")
        parse_result = _latest_parse_result(repository, version_id)
        ingestion_status = parse_result_ingestion_status(parse_result)
        repairs.append(
            {
                "documentId": document.get("id"),
                "documentVersionId": version_id,
                "fileName": document.get("fileName"),
                "ingestionStatus": ingestion_status,
                "before": "抽取不完整",
                "after": "已识别" if ingestion_status == "usable" else "识别失败",
            }
        )
    return repairs


def _set_pending_if_unprocessed(record: dict[str, Any], key: str, pending: str) -> None:
    current = str(record.get(key) or "")
    unprocessed = {
        "sliceStatus": {"", "未切片", "等待OCR"},
        "vectorStatus": {"", "未向量化", "等待OCR"},
    }
    if current in unprocessed[key]:
        record[key] = pending


def _find_task(
    repository: InMemoryRepository,
    *,
    task_type: str,
    target_id: str,
) -> dict[str, Any] | None:
    return next(
        (
            item
            for item in repository.state.get("knowledge_tasks", [])
            if item.get("taskType") == task_type and item.get("targetId") == target_id
        ),
        None,
    )


def _finish_ocr_task(
    repository: InMemoryRepository,
    *,
    document_id: str,
    version_id: str,
    success: bool,
) -> None:
    document = repository.find_one("documents", document_id)
    task = repository.ocr_task_for(
        document_id,
        version_id,
        str((document or {}).get("fileName") or "") or None,
    )
    if not task:
        return
    now = server_time()
    task.update(
        {
            "status": "成功" if success else "失败",
            "progress": 100 if success else task.get("progress", 0),
            "updatedAt": now,
            "finishedAt": now,
        }
    )
    if success:
        task.pop("errorMessage", None)
    else:
        task["errorMessage"] = "OCR result did not contain usable text or table content."
    repository._bump_revision(task)


def apply_repairs(
    repository: InMemoryRepository,
    repairs: list[dict[str, Any]],
) -> dict[str, int]:
    promoted_count = 0
    failed_count = 0
    task_count = 0
    for repair in repairs:
        document_id = str(repair.get("documentId") or "")
        version_id = str(repair.get("documentVersionId") or "")
        document = repository.find_one("documents", document_id)
        version = repository.find_one("versions", version_id)
        if not document or not version or document.get("currentOcrStatus") != "抽取不完整":
            continue
        knowledge_file = repository.knowledge_file_for_version(version_id)
        usable = repair.get("ingestionStatus") == "usable"
        ocr_status = "已识别" if usable else "识别失败"
        document["currentOcrStatus"] = ocr_status
        document["updatedAt"] = server_time()
        version["ocrStatus"] = ocr_status
        if knowledge_file:
            knowledge_file["ocrStatus"] = ocr_status
            knowledge_file["updatedAt"] = server_time()
        _finish_ocr_task(
            repository,
            document_id=document_id,
            version_id=version_id,
            success=usable,
        )
        if not usable:
            failed_count += 1
            continue

        promoted_count += 1
        _set_pending_if_unprocessed(version, "sliceStatus", "待切片")
        _set_pending_if_unprocessed(version, "vectorStatus", "待向量化")
        if not knowledge_file:
            continue
        _set_pending_if_unprocessed(knowledge_file, "sliceStatus", "待切片")
        _set_pending_if_unprocessed(knowledge_file, "vectorStatus", "待向量化")
        source = repository.find_one("knowledge_sources", knowledge_file.get("sourceId"))
        if (source or {}).get("sourceType") == "rule":
            continue
        for task_type, completed_status in (
            ("slice", "已切片"),
            ("vector", "已向量化"),
        ):
            status_key = "sliceStatus" if task_type == "slice" else "vectorStatus"
            if knowledge_file.get(status_key) == completed_status:
                continue
            if _find_task(repository, task_type=task_type, target_id=knowledge_file["id"]):
                continue
            repository.upsert_knowledge_task(
                task_type=task_type,
                target_id=knowledge_file["id"],
                target_name=knowledge_file["fileName"],
                document_id=document_id,
                version_id=version_id,
            )
            task_count += 1
    return {
        "promotedCount": promoted_count,
        "failedCount": failed_count,
        "taskCount": task_count,
    }


def persist_repairs(
    repository: InMemoryRepository,
    repairs: list[dict[str, Any]],
) -> dict[str, int]:
    summary = apply_repairs(repository, repairs)
    document_ids = {str(item.get("documentId") or "") for item in repairs}
    version_ids = {str(item.get("documentVersionId") or "") for item in repairs}
    if document_ids or version_ids:
        flush_state_records(
            {
                "documents": [
                    item
                    for item in repository.state.get("documents", [])
                    if str(item.get("id") or "") in document_ids
                ],
                "versions": [
                    item
                    for item in repository.state.get("versions", [])
                    if str(item.get("id") or "") in version_ids
                ],
                "knowledge_files": [
                    item
                    for item in repository.state.get("knowledge_files", [])
                    if str(item.get("documentVersionId") or "") in version_ids
                ],
                "knowledge_tasks": [
                    item
                    for item in repository.state.get("knowledge_tasks", [])
                    if str(item.get("documentVersionId") or "") in version_ids
                ],
            }
        )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Repair legacy review-incomplete OCR labels using ingestion content usability."
    )
    parser.add_argument("--apply", action="store_true", help="Apply repairs. Default is dry-run.")
    parser.add_argument("--json", action="store_true", help="Print the full JSON report.")
    args = parser.parse_args()
    load_state(REPAIR_COLLECTIONS)
    repairs = build_repairs(repo)
    summary = {"promotedCount": 0, "failedCount": 0, "taskCount": 0}
    if args.apply:
        summary = persist_repairs(repo, repairs)
    report = {
        "schemaVersion": "aicheck-ocr-ingestion-repair@1",
        "mode": "apply" if args.apply else "dry-run",
        "repairCount": len(repairs),
        **summary,
        "repairs": repairs,
    }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(
            f"{report['mode']}: {report['repairCount']} repair candidates; "
            f"{report['promotedCount']} promoted, {report['failedCount']} failed"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
