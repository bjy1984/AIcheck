from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest

import apps.api.routes as routes_module
from apps.api.routes import (
    create_ndt_atomic_drafts_for_completed_session,
    ndt_atomic_draft_consistency_error,
    upload_session_state_records,
)
from libs.db.repository import InMemoryRepository, repo
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


def test_upload_routes_resolve_the_live_composition_repository() -> None:
    replacement = InMemoryRepository(seed=False)
    replacement.state["upload_sessions"] = [
        {"id": "UPS-LIVE-COMPOSITION", "files": []}
    ]
    original = routes_module.repo
    routes_module.repo = replacement
    try:
        records = routes_module.upload_session_state_records("UPS-LIVE-COMPOSITION")
    finally:
        routes_module.repo = original

    assert records["upload_sessions"][0]["id"] == "UPS-LIVE-COMPOSITION"


def test_upload_dispatch_resolves_the_live_composition_dispatcher() -> None:
    calls: list[tuple[str, str]] = []
    replacement = SimpleNamespace(
        dispatch_parse_document=lambda document_id, version_id, *_args: (
            calls.append((document_id, version_id))
            or {"mode": "disabled", "queue": "live-composition"}
        )
    )
    original = routes_module.task_dispatcher
    routes_module.task_dispatcher = replacement
    try:
        outcomes = routes_module.dispatch_completed_upload_files(
            [
                {
                    "documentId": "DOC-LIVE-DISPATCH",
                    "documentVersionId": "DV-LIVE-DISPATCH",
                    "storageKey": "local://live-dispatch.pdf",
                    "fileName": "live-dispatch.pdf",
                }
            ]
        )
    finally:
        routes_module.task_dispatcher = original

    assert calls == [("DOC-LIVE-DISPATCH", "DV-LIVE-DISPATCH")]
    assert outcomes[0]["queue"] == "live-composition"


def test_completion_without_a_stored_body_hash_is_atomic() -> None:
    session_id, _ = repo.create_upload_session(
        PROJECT_ID,
        [{"fileName": "缺少本体哈希.pdf", "fileType": "application/pdf"}],
    )
    session = repo.find_one("upload_sessions", session_id)
    assert session is not None

    with pytest.raises(ValueError, match="UPLOAD_SESSION_BODY_HASH_MISSING"):
        repo.complete_upload_session(session_id)

    assert session["status"] == "待上传"
    assert "completedAt" not in session


def test_sequential_file_updates_keep_the_whole_upload_aggregate_merge_safe() -> None:
    session_id, _ = repo.create_upload_session(
        PROJECT_ID,
        [
            {
                "fileName": f"批量文件-{index}.pdf",
                "fileType": "application/pdf",
                "materialCategory": "无损检测资料",
                "materialTypeCode": "ndt_person_certificate",
                "materialTypeName": "无损检测人员资格证",
                "nodeIds": [38],
            }
            for index in range(1, 9)
        ],
    )
    session = repo.find_one("upload_sessions", session_id)
    assert session is not None

    expected_hashes: dict[str, str] = {}
    for index, file_entry in enumerate(session["files"], start=1):
        body = f"repository-put-{index}".encode()
        version_id = str(file_entry["documentVersionId"])
        content_hash = f"sha256-{hashlib.sha256(body).hexdigest()}"
        expected_hashes[version_id] = content_hash
        repo.update_upload_session_file(
            session_id,
            version_id,
            storage_bucket="local",
            storage_key=f"local://repository/{version_id}",
            file_size=len(body),
            content_type="application/pdf",
            content_hash=content_hash,
        )

    records = upload_session_state_records(session_id)
    assert len(records["upload_sessions"][0]["files"]) == 8
    assert {item["id"]: item["hash"] for item in records["versions"]} == expected_hashes
    assert all(item["fileStatus"] == "已上传" for item in records["documents"])
    assert all(item["status"] == "已上传" for item in records["upload_sessions"][0]["files"])

    completed_files = repo.complete_upload_session(session_id)
    assert len(completed_files) == 8
    assert repo.find_one("upload_sessions", session_id)["status"] == "已完成"


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
    version_id = repo.find_one("upload_sessions", session_id)["files"][0]["documentVersionId"]
    repo.update_upload_session_file(
        session_id,
        version_id,
        storage_bucket="local",
        storage_key=f"local://repository/{version_id}",
        file_size=32,
        content_type="application/pdf",
        content_hash="sha256-test-upload-scoped-persistence",
    )
    files = repo.complete_upload_session(session_id)
    created, error = create_ndt_atomic_drafts_for_completed_session(PROJECT_ID, files)

    records = upload_session_state_records(session_id)

    assert error is None
    assert len(created) == 1
    assert {item["id"] for item in records["bindings"]} == set(created[0]["bindingIds"])
    assert {item["documentId"] for item in records["bindings"]} == {created[0]["documentId"]}


def test_atomic_draft_consistency_rejects_binding_ids_missing_at_commit_boundary() -> None:
    session_id, _ = repo.create_upload_session(
        PROJECT_ID,
        [
            {
                "fileName": "并发丢失挂载.pdf",
                "fileType": "application/pdf",
                "materialCategory": "无损检测资料",
                "materialTypeCode": "ndt_plan",
                "materialTypeName": "无损检测方案",
                "nodeIds": [36, 38],
            }
        ],
    )
    session = repo.find_one("upload_sessions", session_id)
    assert session is not None
    version_id = str(session["files"][0]["documentVersionId"])
    repo.update_upload_session_file(
        session_id,
        version_id,
        storage_bucket="local",
        storage_key=f"local://repository/{version_id}",
        file_size=32,
        content_type="application/pdf",
        content_hash="sha256-binding-commit-boundary",
    )
    files = repo.upload_session_files(session_id)
    created, draft_error = create_ndt_atomic_drafts_for_completed_session(PROJECT_ID, files)
    assert draft_error is None
    lost_binding_id = str(created[0]["bindingIds"][0])
    lost_node_id = int(
        repo.find_one("bindings", lost_binding_id)["nodeId"]
    )
    repo.state["bindings"] = [
        item for item in repo.state["bindings"] if item.get("id") != lost_binding_id
    ]

    error = ndt_atomic_draft_consistency_error(files, created, None)

    assert error is not None
    assert error["invalidAtomicBindings"] == [
        {
            "documentId": created[0]["documentId"],
            "missingBindingIds": [lost_binding_id],
            "unexpectedBindingIds": [],
            "missingNodeIds": [lost_node_id],
            "unexpectedNodeIds": [],
        }
    ]
