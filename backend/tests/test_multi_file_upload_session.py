from __future__ import annotations

import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import apps.api.routes as routes_module
from apps.api.main import app
from apps.api.routes import document_body_uploaded
from libs.db.repository import flush_mutation_records, repo
from libs.db.seed import PROJECT_ID

client = TestClient(app)
NDT_HEADERS = {"X-Role": "ndt", "X-User-Id": "USER-NDT-001"}
CONTRACTOR_HEADERS = {"X-Role": "contractor", "X-User-Id": "USER-CONTRACTOR-001"}
NDT_ORG_ID = "ORG-NDT-EIGHT-FILE"


def setup_function() -> None:
    repo.reset()
    repo.postgres_enabled = False
    repo.sync_postgres = None
    repo.postgres_dsn = None
    repo.sqlite_enabled = False
    repo.sqlite_path = None
    member = next(
        item
        for item in repo.state["project_members"]
        if item.get("projectId") == PROJECT_ID
        and item.get("userId") == "USER-NDT-001"
        and item.get("role") == "ndt"
    )
    member["orgId"] = NDT_ORG_ID


def _assert_ok(response, step: str) -> dict:
    assert response.status_code == 200, f"[{step}] HTTP {response.status_code}: {response.text}"
    payload = response.json()
    assert payload.get("code") == 0, f"[{step}] {payload}"
    return payload.get("data") or {}


def _eight_atomic_files() -> list[dict[str, object]]:
    files: list[dict[str, object]] = [
        {
            "fileName": "无损检测机构核准证.pdf",
            "fileSize": 128,
            "fileType": "application/pdf",
            "materialCategory": "无损检测资料",
            "materialTypeCode": "ndt_org_certificate",
            "materialTypeName": "无损检测机构核准证",
            "nodeIds": [35],
        }
    ]
    files.extend(
        {
            "fileName": f"无损检测人员资格证-{index}.pdf",
            "fileSize": 128 + index,
            "fileType": "application/pdf",
            "materialCategory": "无损检测资料",
            "materialTypeCode": "ndt_person_certificate",
            "materialTypeName": "无损检测人员资格证",
            "nodeIds": [38],
        }
        for index in range(1, 7)
    )
    files.append(
        {
            "fileName": "无损检测方案.pdf",
            "fileSize": 256,
            "fileType": "application/pdf",
            "materialCategory": "无损检测资料",
            "materialTypeCode": "ndt_plan",
            "materialTypeName": "无损检测方案",
            "nodeIds": [36, 38],
        }
    )
    return files


def _create_and_put_eight_files() -> tuple[dict, list[dict[str, object]]]:
    upload = _assert_ok(
        client.post(
            f"/api/projects/{PROJECT_ID}/documents/upload-session",
            headers=NDT_HEADERS,
            json={"files": _eight_atomic_files()},
        ),
        "create",
    )
    completed_files: list[dict[str, object]] = []
    for index, target in enumerate(upload["uploadUrls"], start=1):
        body = f"%PDF-eight-file-{index}".encode().ljust(128 + index, b"0")
        stored = _assert_ok(
            client.put(target["url"], headers={**NDT_HEADERS, **target["headers"]}, content=body),
            f"put-{index}",
        )
        assert stored["documentVersionId"] == target["documentVersionId"]
        completed_files.append(
            {
                "documentVersionId": target["documentVersionId"],
                "fileSize": len(body),
                "contentHash": hashlib.sha256(body).hexdigest(),
            }
        )
    return upload, completed_files


def _complete_eight_file_session(
    upload: dict,
    completed_files: list[dict[str, object]],
    headers: dict[str, str] | None = None,
) -> dict:
    return _assert_ok(
        client.post(
            f"/api/projects/{PROJECT_ID}/documents/upload-session/{upload['uploadSessionId']}/complete",
            headers=headers or NDT_HEADERS,
            json={"completedFiles": completed_files},
        ),
        "complete",
    )


def _assert_eight_file_result(upload: dict, completed_files: list[dict[str, object]], completed: dict) -> None:
    assert completed["nextStatus"] == "已完成"
    assert completed["fileCount"] == len(completed_files) == 8
    assert len(completed["documents"]) == 8
    assert [item["documentId"] for item in completed["documents"]] == [
        item["documentId"] for item in upload["uploadUrls"]
    ]

    persisted_session = repo.find_one("upload_sessions", upload["uploadSessionId"])
    assert persisted_session is not None
    assert persisted_session["status"] == "已完成"

    expected_nodes_by_document = {
        str(target["documentId"]): set(target["nodeIds"])
        for target in upload["uploadUrls"]
    }
    for target in upload["uploadUrls"]:
        document = repo.find_one("documents", str(target["documentId"]))
        version = repo.find_one("versions", str(target["documentVersionId"]))
        assert document is not None
        assert version is not None
        assert document["currentVersionId"] == version["id"]
        assert document["sourceOrgId"] == NDT_ORG_ID
        assert version["hash"]
        assert document_body_uploaded(document, version) is True
        bound_nodes = {
            int(item["nodeId"])
            for item in repo.state["bindings"]
            if item.get("projectId") == PROJECT_ID
            and item.get("documentId") == document["id"]
        }
        assert bound_nodes == expected_nodes_by_document[document["id"]]

    binding_counts = [len(item["bindingIds"]) for item in completed["documents"]]
    assert binding_counts == [1, 1, 1, 1, 1, 1, 1, 2]


def test_eight_file_multi_request_session_retains_bodies_results_and_bindings(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("AICHECK_TASK_DISPATCH", "disabled")
    repo.configure_sqlite(tmp_path / "eight-file-upload.sqlite3")
    upload, completed_files = _create_and_put_eight_files()
    completed = _complete_eight_file_session(upload, completed_files)

    repo.load_from_sqlite({"upload_sessions", "documents", "versions", "bindings"})
    _assert_eight_file_result(upload, completed_files, completed)


def test_postgres_eight_file_session_persists_every_hash_and_binding(
    monkeypatch,
    isolated_postgres_url,
) -> None:
    monkeypatch.setenv("AICHECK_TASK_DISPATCH", "disabled")
    repo.configure_sync_postgres(isolated_postgres_url)
    repo.ensure_postgres_schema()
    try:
        upload, completed_files = _create_and_put_eight_files()
        completed = _complete_eight_file_session(upload, completed_files)

        repo.load_from_sync_postgres(
            {"upload_sessions", "documents", "versions", "bindings"}
        )
        _assert_eight_file_result(upload, completed_files, completed)
    finally:
        repo.close_sync_postgres()


def test_overlapping_postgres_puts_cannot_lose_the_first_hash(
    monkeypatch,
    isolated_postgres_url,
) -> None:
    import apps.api.main as api_main

    monkeypatch.setenv("AICHECK_TASK_DISPATCH", "disabled")
    repo.configure_sync_postgres(isolated_postgres_url)
    repo.ensure_postgres_schema()
    upload = _assert_ok(
        client.post(
            f"/api/projects/{PROJECT_ID}/documents/upload-session",
            headers=NDT_HEADERS,
            json={"files": _eight_atomic_files()[:2]},
        ),
        "create-overlap",
    )
    first_target, second_target = upload["uploadUrls"]
    first_body = b"%PDF-overlap-first"
    second_body = b"%PDF-overlap-second"
    first_flush_entered = threading.Event()
    release_first_flush = threading.Event()
    flush_lock = threading.Lock()
    flush_count = 0
    original_flush = api_main.flush_mutation_records

    def delayed_first_flush(records, scopes):
        nonlocal flush_count
        with flush_lock:
            flush_count += 1
            current = flush_count
        if current == 1:
            first_flush_entered.set()
            assert release_first_flush.wait(timeout=10), "second PUT did not reach persistence"
        return original_flush(records, scopes)

    monkeypatch.setattr(api_main, "flush_mutation_records", delayed_first_flush)

    def put(target: dict, body: bytes):
        return client.put(
            target["url"],
            headers={**NDT_HEADERS, **target["headers"]},
            content=body,
        )

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first_future = pool.submit(put, first_target, first_body)
            assert first_flush_entered.wait(timeout=10), "first PUT did not reach persistence"
            second_future = pool.submit(put, second_target, second_body)
            second_response = second_future.result(timeout=10)
            release_first_flush.set()
            first_response = first_future.result(timeout=10)
        _assert_ok(first_response, "overlap-first")
        _assert_ok(second_response, "overlap-second")

        repo.load_from_sync_postgres({"upload_sessions", "documents", "versions"})
        first_version = repo.find_one("versions", first_target["documentVersionId"])
        second_version = repo.find_one("versions", second_target["documentVersionId"])
        assert first_version is not None
        assert second_version is not None
        assert first_version["hash"] == f"sha256-{hashlib.sha256(first_body).hexdigest()}"
        assert second_version["hash"] == f"sha256-{hashlib.sha256(second_body).hexdigest()}"
    finally:
        release_first_flush.set()
        repo.close_sync_postgres()


def test_rejected_put_does_not_overwrite_completed_local_body() -> None:
    upload = _assert_ok(
        client.post(
            f"/api/projects/{PROJECT_ID}/documents/upload-session",
            headers=NDT_HEADERS,
            json={"files": [_eight_atomic_files()[0]]},
        ),
        "create-rejected-put",
    )
    target = upload["uploadUrls"][0]
    original_body = b"%PDF-original-committed-body"
    replacement_body = b"%PDF-rejected-replacement"
    _assert_ok(
        client.put(
            target["url"],
            headers={**NDT_HEADERS, **target["headers"]},
            content=original_body,
        ),
        "initial-put",
    )
    _complete_eight_file_session(
        {**upload, "uploadUrls": upload["uploadUrls"]},
        [
            {
                "documentVersionId": target["documentVersionId"],
                "fileSize": len(original_body),
                "contentHash": hashlib.sha256(original_body).hexdigest(),
            }
        ],
    )
    version = repo.find_one("versions", target["documentVersionId"])
    assert version is not None
    original_path = Path(__file__).resolve().parents[2] / str(version["storageKey"]).removeprefix("local://")
    assert original_path.read_bytes() == original_body

    rejected = client.put(
        target["url"],
        headers={**NDT_HEADERS, **target["headers"]},
        content=replacement_body,
    )

    assert rejected.json()["code"] != 0
    assert original_path.read_bytes() == original_body


def test_dispatch_failure_returns_success_and_persists_retryable_state(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("AICHECK_TASK_DISPATCH", "celery")
    repo.configure_sqlite(tmp_path / "dispatch-failure.sqlite3")
    upload = _assert_ok(
        client.post(
            f"/api/projects/{PROJECT_ID}/documents/upload-session",
            headers=NDT_HEADERS,
            json={"files": [_eight_atomic_files()[-1]]},
        ),
        "create-dispatch-failure",
    )
    target = upload["uploadUrls"][0]
    body = b"%PDF-dispatch-failure"
    _assert_ok(
        client.put(
            target["url"],
            headers={**NDT_HEADERS, **target["headers"]},
            content=body,
        ),
        "put-dispatch-failure",
    )
    monkeypatch.setattr(
        "apps.api.routes.task_dispatcher.dispatch_parse_document",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("broker down")),
    )

    completed = _complete_eight_file_session(
        upload,
        [
            {
                "documentVersionId": target["documentVersionId"],
                "fileSize": len(body),
                "contentHash": hashlib.sha256(body).hexdigest(),
            }
        ],
    )

    assert completed["nextStatus"] == "已完成"
    assert completed["processingStatus"] == "需重试"
    assert completed["queuedTasks"] == [
        {
            "documentId": target["documentId"],
            "documentVersionId": target["documentVersionId"],
            "status": "dispatch_failed",
            "retryable": True,
            "errorCode": "RUNTIMEERROR",
        }
    ]
    repo.load_from_sqlite(
        {"upload_sessions", "documents", "versions", "bindings", "knowledge_tasks"}
    )
    session = repo.find_one("upload_sessions", upload["uploadSessionId"])
    task = repo.ocr_task_for(target["documentId"], target["documentVersionId"])
    assert session is not None and session["status"] == "已完成"
    assert task is not None
    assert task["status"] == "失败"
    assert task["dispatchStatus"] == "retry_pending"
    assert task["retryable"] is True
    assert task["lastDispatch"]["status"] == "dispatch_failed"


def test_duplicate_projection_failure_after_commit_returns_truthful_success(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("AICHECK_TASK_DISPATCH", "disabled")
    repo.configure_sqlite(tmp_path / "duplicate-projection-failure.sqlite3")
    upload = _assert_ok(
        client.post(
            f"/api/projects/{PROJECT_ID}/documents/upload-session",
            headers=NDT_HEADERS,
            json={"files": [_eight_atomic_files()[-1]]},
        ),
        "create-duplicate-projection-failure",
    )
    target = upload["uploadUrls"][0]
    body = b"%PDF-duplicate-projection-failure"
    _assert_ok(
        client.put(
            target["url"],
            headers={**NDT_HEADERS, **target["headers"]},
            content=body,
        ),
        "put-duplicate-projection-failure",
    )
    monkeypatch.setattr(
        routes_module,
        "duplicate_documents_in_project",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("projection failed")),
    )

    response = client.post(
        f"/api/projects/{PROJECT_ID}/documents/upload-session/{upload['uploadSessionId']}/complete",
        headers=NDT_HEADERS,
        json={
            "completedFiles": [
                {
                    "documentVersionId": target["documentVersionId"],
                    "fileSize": len(body),
                    "contentHash": hashlib.sha256(body).hexdigest(),
                }
            ]
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] == 0, payload
    assert payload["data"]["nextStatus"] == "已完成"
    assert payload["data"]["duplicates"] == []
    assert payload["data"]["completionWarnings"] == [
        {
            "stage": "duplicate_projection",
            "status": "failed",
            "errorCode": "RUNTIMEERROR",
        }
    ]
    repo.load_from_sqlite({"upload_sessions"})
    session = repo.find_one("upload_sessions", upload["uploadSessionId"])
    assert session is not None and session["status"] == "已完成"


def test_dispatch_enrichment_failure_after_commit_is_structured(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("AICHECK_TASK_DISPATCH", "disabled")
    repo.configure_sqlite(tmp_path / "dispatch-enrichment-failure.sqlite3")
    upload = _assert_ok(
        client.post(
            f"/api/projects/{PROJECT_ID}/documents/upload-session",
            headers=NDT_HEADERS,
            json={"files": [_eight_atomic_files()[-1]]},
        ),
        "create-dispatch-enrichment-failure",
    )
    target = upload["uploadUrls"][0]
    body = b"%PDF-dispatch-enrichment-failure"
    _assert_ok(
        client.put(
            target["url"],
            headers={**NDT_HEADERS, **target["headers"]},
            content=body,
        ),
        "put-dispatch-enrichment-failure",
    )
    monkeypatch.setattr(
        routes_module,
        "dispatch_completed_upload_files",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("dispatch wrapper failed")),
    )

    completed = _complete_eight_file_session(
        upload,
        [
            {
                "documentVersionId": target["documentVersionId"],
                "fileSize": len(body),
                "contentHash": hashlib.sha256(body).hexdigest(),
            }
        ],
    )

    assert completed["nextStatus"] == "已完成"
    assert completed["processingStatus"] == "需重试"
    assert completed["queuedTasks"] == [
        {
            "documentId": target["documentId"],
            "documentVersionId": target["documentVersionId"],
            "status": "dispatch_failed",
            "retryable": True,
            "errorCode": "RUNTIMEERROR",
        }
    ]
    assert completed["completionWarnings"] == [
        {"stage": "dispatch", "status": "failed", "errorCode": "RUNTIMEERROR"}
    ]


def test_completed_session_replays_durable_result_without_redispatch(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("AICHECK_TASK_DISPATCH", "disabled")
    repo.configure_sqlite(tmp_path / "completion-replay.sqlite3")
    upload = _assert_ok(
        client.post(
            f"/api/projects/{PROJECT_ID}/documents/upload-session",
            headers=NDT_HEADERS,
            json={"files": [_eight_atomic_files()[-1]]},
        ),
        "create-completion-replay",
    )
    target = upload["uploadUrls"][0]
    body = b"%PDF-completion-replay"
    _assert_ok(
        client.put(
            target["url"],
            headers={**NDT_HEADERS, **target["headers"]},
            content=body,
        ),
        "put-completion-replay",
    )
    completion_body = {
        "completedFiles": [
            {
                "documentVersionId": target["documentVersionId"],
                "fileSize": len(body),
                "contentHash": hashlib.sha256(body).hexdigest(),
            }
        ]
    }
    first = client.post(
        f"/api/projects/{PROJECT_ID}/documents/upload-session/{upload['uploadSessionId']}/complete",
        headers=NDT_HEADERS,
        json=completion_body,
    )
    assert first.json()["code"] == 0, first.text
    repo.load_from_sqlite(
        {
            "upload_sessions",
            "documents",
            "versions",
            "bindings",
            "knowledge_tasks",
            "ndt_reports",
            "knowledge_files",
        }
    )
    monkeypatch.setattr(
        routes_module,
        "dispatch_completed_upload_files",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not redispatch")),
    )

    replay = client.post(
        f"/api/projects/{PROJECT_ID}/documents/upload-session/{upload['uploadSessionId']}/complete",
        headers=NDT_HEADERS,
        json=completion_body,
    )

    assert replay.json()["code"] == 0, replay.text
    assert replay.json()["data"]["nextStatus"] == "已完成"
    assert replay.json()["data"]["fileCount"] == 1


def test_database_failure_before_promotion_leaves_no_final_body(
    monkeypatch,
    tmp_path,
) -> None:
    repo.configure_sqlite(tmp_path / "stage-db-failure.sqlite3")
    upload = _assert_ok(
        client.post(
            f"/api/projects/{PROJECT_ID}/documents/upload-session",
            headers=NDT_HEADERS,
            json={"files": [_eight_atomic_files()[0]]},
        ),
        "create-stage-db-failure",
    )
    target = upload["uploadUrls"][0]
    version_root = (
        Path(__file__).resolve().parents[2]
        / "output"
        / "document_uploads"
        / PROJECT_ID
        / upload["uploadSessionId"]
        / target["documentVersionId"]
    )
    monkeypatch.setattr(
        repo,
        "_persist_upload_session_records_to_sqlite",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("db write failed")),
    )

    with pytest.raises(RuntimeError, match="db write failed"):
        client.put(
            target["url"],
            headers={**NDT_HEADERS, **target["headers"]},
            content=b"%PDF-never-promoted",
        )

    assert [path for path in version_root.rglob("*") if path.is_file()] == []


def test_promotion_failure_is_compensated_without_body_uploaded(
    monkeypatch,
    tmp_path,
) -> None:
    repo.configure_sqlite(tmp_path / "promotion-failure.sqlite3")
    upload = _assert_ok(
        client.post(
            f"/api/projects/{PROJECT_ID}/documents/upload-session",
            headers=NDT_HEADERS,
            json={"files": [_eight_atomic_files()[0]]},
        ),
        "create-promotion-failure",
    )
    target = upload["uploadUrls"][0]
    monkeypatch.setattr(
        "apps.api.routes.os.replace",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk unavailable")),
    )

    response = client.put(
        target["url"],
        headers={**NDT_HEADERS, **target["headers"]},
        content=b"%PDF-promotion-failure",
    )

    assert response.json()["code"] != 0
    repo.load_from_sqlite({"upload_sessions", "documents", "versions"})
    session = repo.find_one("upload_sessions", upload["uploadSessionId"])
    document = repo.find_one("documents", target["documentId"])
    version = repo.find_one("versions", target["documentVersionId"])
    assert session is not None
    file_entry = session["files"][0]
    assert file_entry["status"] == "待上传"
    assert file_entry["promotionStatus"] == "失败"
    assert file_entry["promotionRetryable"] is True
    assert version is not None and not version.get("hash")
    assert document_body_uploaded(document, version) is False


def test_finalize_database_failure_removes_promoted_body_and_records_recovery(
    monkeypatch,
    tmp_path,
) -> None:
    repo.configure_sqlite(tmp_path / "finalize-db-failure.sqlite3")
    upload = _assert_ok(
        client.post(
            f"/api/projects/{PROJECT_ID}/documents/upload-session",
            headers=NDT_HEADERS,
            json={"files": [_eight_atomic_files()[0]]},
        ),
        "create-finalize-db-failure",
    )
    target = upload["uploadUrls"][0]
    version_root = (
        Path(__file__).resolve().parents[2]
        / "output"
        / "document_uploads"
        / PROJECT_ID
        / upload["uploadSessionId"]
        / target["documentVersionId"]
    )
    original_persist = repo._persist_upload_session_records_to_sqlite
    persist_calls = 0

    def fail_finalize(connection, records, tenant_id):
        nonlocal persist_calls
        persist_calls += 1
        if persist_calls == 2:
            raise RuntimeError("finalize db failed")
        return original_persist(connection, records, tenant_id)

    monkeypatch.setattr(repo, "_persist_upload_session_records_to_sqlite", fail_finalize)

    response = client.put(
        target["url"],
        headers={**NDT_HEADERS, **target["headers"]},
        content=b"%PDF-finalize-db-failure",
    )

    assert response.json()["code"] != 0
    assert [path for path in version_root.rglob("*") if path.is_file()] == []
    repo.load_from_sqlite({"upload_sessions", "documents", "versions"})
    session = repo.find_one("upload_sessions", upload["uploadSessionId"])
    version = repo.find_one("versions", target["documentVersionId"])
    assert session is not None
    assert session["files"][0]["promotionStatus"] == "失败"
    assert version is not None and not version.get("hash")


def test_duplicate_filenames_persist_distinct_dispatch_failures(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("AICHECK_TASK_DISPATCH", "celery")
    repo.configure_sqlite(tmp_path / "duplicate-dispatch.sqlite3")
    duplicate = {
        **_eight_atomic_files()[1],
        "fileName": "同名资格证.pdf",
    }
    upload = _assert_ok(
        client.post(
            f"/api/projects/{PROJECT_ID}/documents/upload-session",
            headers=NDT_HEADERS,
            json={"files": [duplicate, dict(duplicate)]},
        ),
        "create-duplicate-dispatch",
    )
    completed_files: list[dict[str, object]] = []
    for index, target in enumerate(upload["uploadUrls"], start=1):
        body = f"%PDF-duplicate-{index}".encode()
        _assert_ok(
            client.put(
                target["url"],
                headers={**NDT_HEADERS, **target["headers"]},
                content=body,
            ),
            f"put-duplicate-{index}",
        )
        completed_files.append(
            {
                "documentVersionId": target["documentVersionId"],
                "fileSize": len(body),
                "contentHash": hashlib.sha256(body).hexdigest(),
            }
        )
    monkeypatch.setattr(
        "apps.api.routes.task_dispatcher.dispatch_parse_document",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("broker down")),
    )

    completed = _complete_eight_file_session(upload, completed_files)

    assert [item["documentVersionId"] for item in completed["queuedTasks"]] == [
        item["documentVersionId"] for item in upload["uploadUrls"]
    ]
    assert {item["status"] for item in completed["queuedTasks"]} == {"dispatch_failed"}
    repo.load_from_sqlite({"knowledge_tasks"})
    expected_version_ids = {
        str(item["documentVersionId"]) for item in upload["uploadUrls"]
    }
    exact_tasks = [
        item for item in repo.state["knowledge_tasks"]
        if str(item.get("documentVersionId") or "") in expected_version_ids
    ]
    assert len(exact_tasks) == 2
    assert {str(item["documentVersionId"]) for item in exact_tasks} == expected_version_ids
    assert all(item["status"] == "失败" for item in exact_tasks)
    assert all(item["dispatchStatus"] == "retry_pending" for item in exact_tasks)
    assert all(item["retryable"] is True for item in exact_tasks)
    assert all(
        item["lastDispatch"]["documentVersionId"] == item["documentVersionId"]
        for item in exact_tasks
    )


def _create_crashed_staging_state(
    tmp_path: Path,
    *,
    artifact: str,
) -> tuple[dict, dict, bytes, Path, Path]:
    repo.configure_sqlite(tmp_path / f"staging-recovery-{artifact}.sqlite3")
    upload = _assert_ok(
        client.post(
            f"/api/projects/{PROJECT_ID}/documents/upload-session",
            headers=NDT_HEADERS,
            json={"files": [_eight_atomic_files()[0]]},
        ),
        f"create-recovery-{artifact}",
    )
    target = upload["uploadUrls"][0]
    target_dir = (
        Path(__file__).resolve().parents[2]
        / "output"
        / "document_uploads"
        / PROJECT_ID
        / upload["uploadSessionId"]
        / target["documentVersionId"]
    )
    target_dir.mkdir(parents=True, exist_ok=True)
    final_path = target_dir / target["fileName"]
    temporary_path = target_dir / f".{target['fileName']}.crash.upload"
    staged_body = f"%PDF-staged-{artifact}".encode()
    if artifact == "temporary":
        temporary_path.write_bytes(staged_body)
    elif artifact == "promoted":
        final_path.write_bytes(staged_body)
    repo.stage_upload_session_file(
        upload["uploadSessionId"],
        target["documentVersionId"],
        storage_bucket="local",
        storage_key=f"local://{final_path.relative_to(Path(__file__).resolve().parents[2])}",
        file_size=len(staged_body),
        content_type="application/pdf",
        content_hash=f"sha256-{hashlib.sha256(staged_body).hexdigest()}",
        temporary_storage_key=(
            f"local://{temporary_path.relative_to(Path(__file__).resolve().parents[2])}"
        ),
        project_id=PROJECT_ID,
        upload_token=target["headers"]["X-Upload-Session-Token"],
    )
    return upload, target, staged_body, temporary_path, final_path


def test_later_put_recovers_staged_temporary_file(monkeypatch, tmp_path) -> None:
    upload, target, staged_body, temporary_path, _final_path = _create_crashed_staging_state(
        tmp_path,
        artifact="temporary",
    )

    recovered = _assert_ok(
        client.put(
            target["url"],
            headers={**NDT_HEADERS, **target["headers"]},
            content=b"%PDF-new-body-not-needed",
        ),
        "recover-temporary",
    )

    assert recovered["recovered"] is True
    assert recovered["recoverySource"] == "temporary"
    assert not temporary_path.exists()
    repo.load_from_sqlite({"upload_sessions", "documents", "versions"})
    version = repo.find_one("versions", target["documentVersionId"])
    assert version is not None
    assert version["hash"] == f"sha256-{hashlib.sha256(staged_body).hexdigest()}"
    published_path = Path(__file__).resolve().parents[2] / str(version["storageKey"]).removeprefix(
        "local://"
    )
    assert published_path.read_bytes() == staged_body


def test_later_put_finalizes_already_promoted_staged_file(monkeypatch, tmp_path) -> None:
    upload, target, staged_body, temporary_path, _final_path = _create_crashed_staging_state(
        tmp_path,
        artifact="promoted",
    )

    recovered = _assert_ok(
        client.put(
            target["url"],
            headers={**NDT_HEADERS, **target["headers"]},
            content=b"%PDF-new-body-not-needed",
        ),
        "recover-promoted",
    )

    assert recovered["recovered"] is True
    assert recovered["recoverySource"] == "promoted"
    assert not temporary_path.exists()
    repo.load_from_sqlite({"upload_sessions", "documents", "versions"})
    version = repo.find_one("versions", target["documentVersionId"])
    assert version is not None
    assert version["hash"] == f"sha256-{hashlib.sha256(staged_body).hexdigest()}"
    published_path = Path(__file__).resolve().parents[2] / str(version["storageKey"]).removeprefix(
        "local://"
    )
    assert published_path.read_bytes() == staged_body


def test_later_put_resets_missing_staged_artifacts_and_uploads_new_body(
    monkeypatch,
    tmp_path,
) -> None:
    upload, target, _staged_body, temporary_path, _final_path = _create_crashed_staging_state(
        tmp_path,
        artifact="missing",
    )
    replacement_body = b"%PDF-replacement-after-missing-stage"

    uploaded = _assert_ok(
        client.put(
            target["url"],
            headers={**NDT_HEADERS, **target["headers"]},
            content=replacement_body,
        ),
        "recover-missing",
    )

    assert uploaded.get("recovered") is not True
    assert not temporary_path.exists()
    repo.load_from_sqlite({"upload_sessions", "documents", "versions"})
    session = repo.find_one("upload_sessions", upload["uploadSessionId"])
    version = repo.find_one("versions", target["documentVersionId"])
    assert session is not None
    assert session["files"][0]["status"] == "已上传"
    assert version is not None
    assert version["hash"] == f"sha256-{hashlib.sha256(replacement_body).hexdigest()}"
    published_path = Path(__file__).resolve().parents[2] / str(version["storageKey"]).removeprefix(
        "local://"
    )
    assert published_path.read_bytes() == replacement_body


def test_stale_recovery_cannot_delete_concurrently_finalized_body(
    monkeypatch,
    tmp_path,
) -> None:
    import apps.api.routes as routes_module

    upload, target, staged_body, _temporary_path, _final_path = _create_crashed_staging_state(
        tmp_path,
        artifact="promoted",
    )
    stale_snapshot_ready = threading.Event()
    release_stale_recovery = threading.Event()
    original_matches = routes_module.staged_local_upload_matches
    match_lock = threading.Lock()
    stale_match_calls = 0

    def controlled_matches(path: Path | None, file_entry: dict) -> bool:
        nonlocal stale_match_calls
        with match_lock:
            stale_match_calls += 1
            current = stale_match_calls
        if current == 2:
            stale_snapshot_ready.set()
            assert release_stale_recovery.wait(timeout=10)
        if current <= 2:
            return False
        return original_matches(path, file_entry)

    monkeypatch.setattr(routes_module, "staged_local_upload_matches", controlled_matches)

    def recover(body: bytes):
        return client.put(
            target["url"],
            headers={**NDT_HEADERS, **target["headers"]},
            content=body,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        stale_future = pool.submit(recover, b"")
        assert stale_snapshot_ready.wait(timeout=10)
        winner_future = pool.submit(recover, b"unused")
        winner_response = winner_future.result(timeout=10)
        release_stale_recovery.set()
        stale_response = stale_future.result(timeout=10)

    assert winner_response.json()["code"] == 0
    if stale_response.json()["code"] != 0:
        assert stale_response.json()["data"]["reason"] in {
            "CONFLICT",
            "UPLOAD_STAGING_ALREADY_FINALIZED",
            "VALIDATION_ERROR",
        }
    repo.load_from_sqlite({"upload_sessions", "documents", "versions"})
    session = repo.find_one("upload_sessions", upload["uploadSessionId"])
    version = repo.find_one("versions", target["documentVersionId"])
    assert session is not None
    assert session["files"][0]["status"] == "已上传"
    assert version is not None
    assert version["hash"] == f"sha256-{hashlib.sha256(staged_body).hexdigest()}"
    published_path = Path(__file__).resolve().parents[2] / str(version["storageKey"]).removeprefix(
        "local://"
    )
    assert published_path.read_bytes() == staged_body


def test_cleanup_failure_state_survives_reload_and_later_retry(
    monkeypatch,
    tmp_path,
) -> None:
    upload, target, _staged_body, temporary_path, final_path = _create_crashed_staging_state(
        tmp_path,
        artifact="missing",
    )
    invalid_body = b"invalid-staged-artifact"
    final_path.write_bytes(invalid_body)
    original_unlink = Path.unlink

    def fail_staged_cleanup(path: Path, *args, **kwargs):
        if path == final_path:
            raise OSError("cleanup blocked")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_staged_cleanup)
    failed = client.put(
        target["url"],
        headers={**NDT_HEADERS, **target["headers"]},
        content=b"replacement-waits-for-cleanup",
    )

    assert failed.json()["data"]["reason"] == "UPLOAD_STAGING_CLEANUP_REQUIRED"
    repo.load_from_sqlite({"upload_sessions", "documents", "versions"})
    session = repo.find_one("upload_sessions", upload["uploadSessionId"])
    assert session is not None
    staged = session["files"][0]
    assert staged["status"] == "待落盘"
    assert staged["promotionStatus"] == "待清理"
    assert staged["promotionCleanupRequired"] is True
    assert staged["stagedStorageKey"]
    assert staged["stagedTemporaryStorageKey"]
    assert staged["stagedContentHash"]
    assert staged["stagedFileSize"]

    monkeypatch.setattr(Path, "unlink", original_unlink)
    replacement_body = b"%PDF-after-cleanup-retry"
    retried = _assert_ok(
        client.put(
            target["url"],
            headers={**NDT_HEADERS, **target["headers"]},
            content=replacement_body,
        ),
        "retry-after-cleanup",
    )

    assert retried.get("recovered") is not True
    assert not temporary_path.exists()
    repo.load_from_sqlite({"upload_sessions", "documents", "versions"})
    session = repo.find_one("upload_sessions", upload["uploadSessionId"])
    version = repo.find_one("versions", target["documentVersionId"])
    assert session is not None and session["files"][0]["status"] == "已上传"
    assert version is not None
    assert version["hash"] == f"sha256-{hashlib.sha256(replacement_body).hexdigest()}"
    published_path = Path(__file__).resolve().parents[2] / str(version["storageKey"]).removeprefix(
        "local://"
    )
    assert published_path.read_bytes() == replacement_body


def test_expired_recovery_claimant_cannot_delete_takeover_winner_body(
    monkeypatch,
    tmp_path,
) -> None:
    import apps.api.routes as routes_module

    upload, target, staged_body, _temporary_path, _initial_path = _create_crashed_staging_state(
        tmp_path,
        artifact="promoted",
    )
    old_claim_paused = threading.Event()
    release_old_claim = threading.Event()
    original_matches = routes_module.staged_local_upload_matches
    match_lock = threading.Lock()
    calls = 0

    def controlled_matches(path: Path | None, file_entry: dict) -> bool:
        nonlocal calls
        with match_lock:
            calls += 1
            current = calls
        if current == 4:
            old_claim_paused.set()
            assert release_old_claim.wait(timeout=10)
        if current in {3, 4}:
            return False
        return original_matches(path, file_entry)

    monkeypatch.setattr(routes_module, "staged_local_upload_matches", controlled_matches)

    def recover(body: bytes):
        return client.put(
            target["url"],
            headers={**NDT_HEADERS, **target["headers"]},
            content=body,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        expired_future = pool.submit(recover, b"")
        assert old_claim_paused.wait(timeout=10)
        session = repo.find_one("upload_sessions", upload["uploadSessionId"])
        assert session is not None
        session["files"][0]["recoveryLeaseAt"] = "2000-01-01 00:00:00"
        flush_mutation_records({"upload_sessions": [session]}, [])

        winner_future = pool.submit(recover, b"unused")
        winner_response = winner_future.result(timeout=10)
        release_old_claim.set()
        expired_response = expired_future.result(timeout=10)

    assert winner_response.json()["code"] == 0
    assert expired_response.json()["code"] != 0
    repo.load_from_sqlite({"upload_sessions", "documents", "versions"})
    session = repo.find_one("upload_sessions", upload["uploadSessionId"])
    version = repo.find_one("versions", target["documentVersionId"])
    assert session is not None and session["files"][0]["status"] == "已上传"
    assert version is not None
    assert version["hash"] == f"sha256-{hashlib.sha256(staged_body).hexdigest()}"
    winner_path = Path(__file__).resolve().parents[2] / str(version["storageKey"]).removeprefix(
        "local://"
    )
    assert winner_path.read_bytes() == staged_body


def test_recovery_replace_failure_preserves_temp_and_retry_metadata(
    monkeypatch,
    tmp_path,
) -> None:
    import apps.api.routes as routes_module

    upload, target, staged_body, temporary_path, _final_path = _create_crashed_staging_state(
        tmp_path,
        artifact="temporary",
    )
    original_replace = routes_module.os.replace
    monkeypatch.setattr(
        routes_module.os,
        "replace",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("promotion blocked")),
    )

    failed = client.put(
        target["url"],
        headers={**NDT_HEADERS, **target["headers"]},
        content=b"unused",
    )

    assert failed.json()["data"]["reason"] == "UPLOAD_STAGING_RECOVERY_FAILED"
    assert temporary_path.read_bytes() == staged_body
    repo.load_from_sqlite({"upload_sessions", "documents", "versions"})
    session = repo.find_one("upload_sessions", upload["uploadSessionId"])
    assert session is not None
    staged = session["files"][0]
    assert staged["status"] == "待落盘"
    assert staged["promotionStatus"] == "待清理"
    assert staged["promotionCleanupRequired"] is True
    assert staged["stagedTemporaryStorageKey"]
    assert staged["stagedContentHash"]

    monkeypatch.setattr(routes_module.os, "replace", original_replace)
    recovered = _assert_ok(
        client.put(
            target["url"],
            headers={**NDT_HEADERS, **target["headers"]},
            content=b"unused-again",
        ),
        "retry-recovery-replace",
    )
    assert recovered["recovered"] is True
    repo.load_from_sqlite({"versions"})
    version = repo.find_one("versions", target["documentVersionId"])
    assert version is not None
    assert version["hash"] == f"sha256-{hashlib.sha256(staged_body).hexdigest()}"


def test_direct_storage_hash_failure_rejects_client_hash_without_completing(
    monkeypatch,
) -> None:
    import apps.api.routes as routes_module

    file_size = 4096
    client_claimed_hash = "a" * 64
    upload = _assert_ok(
        client.post(
            f"/api/projects/{PROJECT_ID}/documents/upload-session",
            headers=NDT_HEADERS,
            json={"files": [_eight_atomic_files()[0]]},
        ),
        "create-direct-hash-failure",
    )
    target = upload["uploadUrls"][0]
    monkeypatch.setattr(
        routes_module.object_storage,
        "object_metadata",
        lambda _bucket, _key: {
            "size": file_size,
            "contentType": "application/pdf",
            "etag": "stored-etag",
        },
    )
    monkeypatch.setattr(
        routes_module.object_storage,
        "content_hash",
        lambda _bucket, _key: (_ for _ in ()).throw(RuntimeError("hash backend down")),
    )

    response = client.post(
        f"/api/projects/{PROJECT_ID}/documents/upload-session/{upload['uploadSessionId']}/complete",
        headers=NDT_HEADERS,
        json={
            "completedFiles": [
                {
                    "documentVersionId": target["documentVersionId"],
                    "fileSize": file_size,
                    "contentHash": client_claimed_hash,
                }
            ]
        },
    )

    payload = response.json()
    assert payload["code"] != 0
    assert payload["data"]["reason"] == "AUTHORITATIVE_CONTENT_HASH_UNAVAILABLE"
    assert payload["data"]["retryable"] is True
    session = repo.find_one("upload_sessions", upload["uploadSessionId"])
    document = repo.find_one("documents", target["documentId"])
    version = repo.find_one("versions", target["documentVersionId"])
    assert session is not None and session["status"] == "待上传"
    assert session["files"][0]["status"] == "待上传"
    assert version is not None and not version.get("hash")
    assert document_body_uploaded(document, version) is False


def test_create_session_client_hash_cannot_authorize_new_or_replacement_body(
    monkeypatch,
) -> None:
    monkeypatch.setenv("AICHECK_TASK_DISPATCH", "disabled")
    fake_hash = "f" * 64

    def assert_bind_and_submit_denied(document_id: str, key: str) -> None:
        document = repo.find_one("documents", document_id)
        version = repo.current_version(document_id)
        knowledge_file = repo.knowledge_file_for_version(str((version or {}).get("id") or ""))
        assert document is not None and version is not None and knowledge_file is not None
        document["currentOcrStatus"] = "已识别"
        version["ocrStatus"] = "已识别"
        version["sliceStatus"] = "已切片"
        version["vectorStatus"] = "已向量化"
        knowledge_file["ocrStatus"] = "已识别"
        knowledge_file["sliceStatus"] = "已切片"
        knowledge_file["vectorStatus"] = "已向量化"
        bound = client.post(
            f"/api/projects/{PROJECT_ID}/documents/bindings",
            headers={**CONTRACTOR_HEADERS, "Idempotency-Key": f"{key}-bind"},
            json={"bindings": [{"documentId": document_id, "nodeId": 24}]},
        )
        assert bound.json()["data"]["reason"] == "DOCUMENT_BODY_MISSING"
        submitted = client.post(
            f"/api/projects/{PROJECT_ID}/submissions",
            headers={**CONTRACTOR_HEADERS, "Idempotency-Key": f"{key}-submit"},
            json={"nodeIds": [24], "documentIds": [document_id], "batchName": key},
        )
        assert submitted.json()["data"]["reason"] == "DOCUMENT_BODY_MISSING"

    new_file = {
        "fileName": "伪造哈希空壳.pdf",
        "fileSize": 1024,
        "fileType": "application/pdf",
        "contentHash": fake_hash,
    }
    new_upload = _assert_ok(
        client.post(
            f"/api/projects/{PROJECT_ID}/documents/upload-session",
            headers=CONTRACTOR_HEADERS,
            json={"files": [new_file]},
        ),
        "create-client-hash-shell",
    )
    new_target = new_upload["uploadUrls"][0]
    new_document = repo.find_one("documents", new_target["documentId"])
    new_version = repo.find_one("versions", new_target["documentVersionId"])
    assert new_version is not None and not new_version.get("hash")
    assert document_body_uploaded(new_document, new_version) is False
    assert_bind_and_submit_denied(new_target["documentId"], "new-client-hash-shell")

    initial_upload = _assert_ok(
        client.post(
            f"/api/projects/{PROJECT_ID}/documents/upload-session",
            headers=CONTRACTOR_HEADERS,
            json={"files": [{"fileName": "替换基线.pdf", "fileSize": 1024, "fileType": "application/pdf"}]},
        ),
        "create-replacement-base",
    )
    initial_target = initial_upload["uploadUrls"][0]
    initial_body = b"%PDF-replacement-base"
    _assert_ok(
        client.put(
            initial_target["url"],
            headers={**CONTRACTOR_HEADERS, **initial_target["headers"]},
            content=initial_body,
        ),
        "put-replacement-base",
    )
    _complete_eight_file_session(
        initial_upload,
        [
            {
                "documentVersionId": initial_target["documentVersionId"],
                "fileSize": len(initial_body),
                "contentHash": hashlib.sha256(initial_body).hexdigest(),
            }
        ],
        headers=CONTRACTOR_HEADERS,
    )
    replacement_file = {
        "fileName": "替换但未上传.pdf",
        "fileSize": 1024,
        "fileType": "application/pdf",
        "replaceDocumentId": initial_target["documentId"],
        "contentHash": fake_hash,
    }
    replacement_upload = _assert_ok(
        client.post(
            f"/api/projects/{PROJECT_ID}/documents/upload-session",
            headers=CONTRACTOR_HEADERS,
            json={"files": [replacement_file]},
        ),
        "create-client-hash-replacement",
    )
    replacement_target = replacement_upload["uploadUrls"][0]
    replacement_document = repo.find_one("documents", replacement_target["documentId"])
    replacement_version = repo.find_one("versions", replacement_target["documentVersionId"])
    assert replacement_target["documentId"] == initial_target["documentId"]
    assert replacement_version is not None and not replacement_version.get("hash")
    assert document_body_uploaded(replacement_document, replacement_version) is False
    assert_bind_and_submit_denied(
        replacement_target["documentId"],
        "replacement-client-hash-shell",
    )


def test_invalid_atomic_item_fails_before_session_completion_or_partial_bindings(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_TASK_DISPATCH", "disabled")
    upload, completed_files = _create_and_put_eight_files()
    session = repo.find_one("upload_sessions", upload["uploadSessionId"])
    assert session is not None
    invalid_document_id = str(session["files"][3]["documentId"])
    repo.state["documents"] = [
        item for item in repo.state["documents"] if item.get("id") != invalid_document_id
    ]
    bindings_before = list(repo.state["bindings"])

    response = client.post(
        f"/api/projects/{PROJECT_ID}/documents/upload-session/{upload['uploadSessionId']}/complete",
        headers=NDT_HEADERS,
        json={"completedFiles": completed_files},
    )

    payload = response.json()
    assert payload["code"] != 0
    assert payload["data"]["reason"] == "VALIDATION_ERROR"
    assert payload["data"]["invalidAtomicItems"] == [
        {"documentId": invalid_document_id, "reason": "DOCUMENT_NOT_FOUND"}
    ]
    assert session["status"] == "待上传"
    assert "completedAt" not in session
    assert repo.state["bindings"] == bindings_before


def test_completion_rechecks_returned_bindings_inside_atomic_commit(monkeypatch) -> None:
    import apps.api.routes as routes_module

    monkeypatch.setenv("AICHECK_TASK_DISPATCH", "disabled")
    upload = _assert_ok(
        client.post(
            f"/api/projects/{PROJECT_ID}/documents/upload-session",
            headers=NDT_HEADERS,
            json={"files": [_eight_atomic_files()[-1]]},
        ),
        "create-binding-race",
    )
    target = upload["uploadUrls"][0]
    body = b"%PDF-binding-race"
    _assert_ok(
        client.put(
            target["url"],
            headers={**NDT_HEADERS, **target["headers"]},
            content=body,
        ),
        "put-binding-race",
    )
    original_create = routes_module.create_ndt_atomic_drafts_for_completed_session

    def create_then_drop_binding(project_id: str, files: list[dict]):
        documents, error = original_create(project_id, files)
        assert error is None
        lost_id = documents[0]["bindingIds"][0]
        repo.state["bindings"] = [
            item for item in repo.state["bindings"] if item.get("id") != lost_id
        ]
        return documents, None

    monkeypatch.setattr(
        routes_module,
        "create_ndt_atomic_drafts_for_completed_session",
        create_then_drop_binding,
    )
    response = client.post(
        f"/api/projects/{PROJECT_ID}/documents/upload-session/{upload['uploadSessionId']}/complete",
        headers=NDT_HEADERS,
        json={
            "completedFiles": [
                {
                    "documentVersionId": target["documentVersionId"],
                    "fileSize": len(body),
                    "contentHash": hashlib.sha256(body).hexdigest(),
                }
            ]
        },
    )

    payload = response.json()
    assert payload["code"] != 0
    assert payload["data"]["reason"] == "VALIDATION_ERROR"
    assert payload["data"]["invalidAtomicBindings"][0]["missingBindingIds"]
    session = repo.find_one("upload_sessions", upload["uploadSessionId"])
    assert session is not None
    assert session["status"] == "待上传"
    assert [
        item for item in repo.state["bindings"]
        if item.get("documentId") == target["documentId"]
    ] == []
