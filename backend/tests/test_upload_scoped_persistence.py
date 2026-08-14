from __future__ import annotations

from apps.api.routes import (
    create_ndt_atomic_drafts_for_completed_session,
    upload_session_state_records,
)
from libs.db.repository import repo
from libs.db.seed import PROJECT_ID


def setup_function() -> None:
    repo.reset()
    repo.postgres_enabled = False
    repo.sync_postgres = None
    repo.postgres_dsn = None
    repo.sqlite_enabled = False
    repo.sqlite_path = None


def test_upload_session_scoped_records_exclude_unrelated_and_vector_state() -> None:
    existing_document_ids = {str(item.get("id")) for item in repo.state["documents"]}
    session_id, _ = repo.create_upload_session(
        PROJECT_ID,
        [{"fileName": "新增施工资料.pdf", "fileType": "application/pdf"}],
    )

    records = upload_session_state_records(session_id)

    session = records["upload_sessions"][0]
    document_id = str(session["files"][0]["documentId"])
    version_id = str(session["files"][0]["documentVersionId"])
    assert document_id not in existing_document_ids
    assert {str(item["id"]) for item in records["documents"]} == {document_id}
    assert {str(item["id"]) for item in records["versions"]} == {version_id}
    assert len(records["knowledge_files"]) == 1
    assert len(records["knowledge_tasks"]) == 1
    assert "knowledge_vectors" not in records
    assert "knowledge_chunks" not in records


def test_unknown_upload_session_has_no_scoped_records() -> None:
    assert upload_session_state_records("UPS-NOT-FOUND") == {}


def test_ndt_upload_session_scoped_records_include_created_bindings() -> None:
    session_id, _ = repo.create_upload_session(
        PROJECT_ID,
        [
            {
                "fileName": "质量保证手册.pdf",
                "fileType": "application/pdf",
                "materialCategory": "无损检测资料",
                "materialTypeCode": "ndt_quality_assurance_manual",
                "materialTypeName": "无损检测单位质量保证手册",
                "nodeIds": [35],
            }
        ],
    )
    files = repo.complete_upload_session(session_id)
    created = create_ndt_atomic_drafts_for_completed_session(PROJECT_ID, files)

    records = upload_session_state_records(session_id)

    assert len(created) == 1
    assert {item["id"] for item in records["bindings"]} == set(created[0]["bindingIds"])
    assert {item["documentId"] for item in records["bindings"]} == {created[0]["documentId"]}
