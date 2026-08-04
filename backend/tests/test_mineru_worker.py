from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from apps.worker import tasks
from libs.db.repository import InMemoryRepository
from libs.integrations import task_dispatcher
from libs.integrations.mineru_client import MinerUProtocolError
from libs.mineru_ocr import MinerUArtifact
from libs.security.tenant import (
    current_tenant_id,
    reset_request_tenant_id,
    set_request_tenant_id,
)


def _result(storage_key: str) -> dict[str, object]:
    return {
        "parseResultId": "PARSE-MINERU-1",
        "status": "success",
        "outcomeStatus": "completed",
        "storageKey": storage_key,
        "fileName": "doc.pdf",
        "pages": [
            {
                "pageNo": 1,
                "width": 1000,
                "height": 1000,
                "coordinateSystem": "rendered_pixels",
            }
        ],
        "fragments": [
            {
                "candidateId": "MINERU-CAND-1",
                "sourceCandidateIds": ["MINERU-CAND-1"],
                "pageNo": 1,
                "text": "合格",
                "bbox": [0, 0, 100, 20],
                "coordinateSystem": "rendered_pixels",
                "sourceEngine": "mineru_vlm",
            }
        ],
        "layoutBlocks": [],
        "tables": [],
        "seals": [],
        "signatures": [],
        "fields": [],
        "quality": {
            "status": "usable",
            "reasons": ["provider_confidence_unavailable"],
            "blockingReasons": [],
        },
        "diagnostics": [],
        "engineRuns": [{"engine": "mineru_vlm", "status": "success"}],
        "metadata": {"provider": "mineru", "model": "vlm"},
        "groundingValidation": {},
    }


def _bundle(storage_key: str) -> SimpleNamespace:
    data = b"artifact"
    return SimpleNamespace(
        result=_result(storage_key),
        artifacts={
            "original_zip": MinerUArtifact(
                name="mineru-result.zip",
                data=data,
                content_type="application/zip",
                sha256="c7c5c1d70c5dec44a2d110c4029d24d7b377885dd19ea2212f9994c151f46c7d",
            ),
            "normalized_json": MinerUArtifact(
                name="normalized-result.json",
                data=b"{}",
                content_type="application/json",
                sha256="44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a",
            ),
        },
    )


def test_repository_tracks_safe_mineru_job_metadata() -> None:
    repository = InMemoryRepository()

    job = repository.create_ocr_job_record(
        document_id="",
        version_id="",
        storage_key="https://files.example/doc.pdf?token=must-not-persist",
        file_name="doc.pdf",
        provider="mineru",
        source_url="https://files.example/doc.pdf?token=must-not-persist",
        options={
            "language": "ch",
            "pageRanges": "1-3",
            "unexpected": "must-not-persist",
            "apiKey": "must-not-persist",
        },
    )

    assert job["provider"] == "mineru"
    assert job["sourceType"] == "url"
    assert job["sourceUrl"] == "https://files.example/doc.pdf"
    assert job["options"] == {"language": "ch", "pageRanges": "1-3"}
    assert "must-not-persist" not in str(job)
    assert job["stage"] == "queued"
    assert job["progress"] == 0

    repository.update_ocr_job_record(
        job,
        status="running",
        stage="poll",
        progress=150,
        provider_task_id="TASK-1",
        provider_task_type="task",
    )
    assert job["progress"] == 99
    assert job["providerTaskId"] == "TASK-1"
    repository.update_ocr_job_record(
        job,
        status="success",
        stage="completed",
        progress=150,
    )
    assert job["progress"] == 100


def test_fragment_fallback_fields_keep_mineru_provenance() -> None:
    repository = InMemoryRepository()
    repository.state["documents"].append({"id": "DOC-PROVENANCE"})
    repository.state["versions"].append(
        {
            "id": "VER-PROVENANCE",
            "documentId": "DOC-PROVENANCE",
        }
    )

    repository.apply_ocr_result(
        "DOC-PROVENANCE",
        "VER-PROVENANCE",
        _result("minio://documents/doc.pdf"),
    )

    field = next(
        item
        for item in repository.state["extracted_fields"]
        if item["documentVersionId"] == "VER-PROVENANCE"
    )
    assert field["extractionMethod"] == "mineru_vlm"


def test_mineru_worker_persists_artifacts_and_applies_bound_result(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repository = InMemoryRepository()
    repository.state["documents"].append({"id": "DOC-MINERU-1"})
    repository.state["versions"].append(
        {"id": "VER-MINERU-1", "documentId": "DOC-MINERU-1"}
    )
    source = tmp_path / "doc.pdf"
    source.write_bytes(b"%PDF-test")
    job = repository.create_ocr_job_record(
        document_id="DOC-MINERU-1",
        version_id="VER-MINERU-1",
        storage_key="minio://documents/doc.pdf",
        file_name="doc.pdf",
        profile_id="generic_document_v1",
        document_type="generic_document",
        provider="mineru",
        options={"provider": "mineru"},
    )
    pipeline_run = repository.create_or_resume_ocr_pipeline_run(
        run_key="DOC-MINERU-1:VER-MINERU-1",
        document_id="DOC-MINERU-1",
        version_id="VER-MINERU-1",
        storage_key="minio://documents/doc.pdf",
        storage_bucket="documents",
        file_name="doc.pdf",
        profile_id="generic_document_v1",
        document_type="generic_document",
        mode="active",
        pipeline_version="test",
    )
    pipeline_run["ocrJobRecordId"] = job["id"]
    job["pipelineRunId"] = pipeline_run["id"]
    progress_snapshots: list[tuple[str, int]] = []
    stored_names: list[str] = []

    class FakeClient:
        def submit_file(
            self,
            path,
            *,
            data_id,
            options,
            submission_callback,
        ):
            assert Path(path).read_bytes() == b"%PDF-test"
            assert data_id == job["id"]
            submission = {
                "kind": "batch",
                "providerTaskId": "BATCH-1",
            }
            submission_callback(submission)
            return submission

        def wait_for_result(self, submission, *, progress_callback):
            progress_callback(
                {
                    "state": "running",
                    "extract_progress": {
                        "extracted_pages": 1,
                        "total_pages": 2,
                    },
                    "full_zip_url": None,
                }
            )
            progress_snapshots.append((job["stage"], job["progress"]))
            return {
                "state": "done",
                "extract_progress": {
                    "extracted_pages": 2,
                    "total_pages": 2,
                },
                "full_zip_url": "https://cdn.example/result.zip",
            }

        def download_result(self, _url):
            return b"zip"

    monkeypatch.setattr(tasks, "repo", repository)
    monkeypatch.setattr(tasks, "MinerUClient", FakeClient)
    monkeypatch.setattr(
        tasks,
        "mineru_source_path",
        lambda _job: (source, None),
    )
    monkeypatch.setattr(
        tasks,
        "normalize_mineru_zip",
        lambda *_args, **_kwargs: _bundle(job["storageKey"]),
    )
    monkeypatch.setattr(tasks, "flush_state_records", lambda _records: None)

    def put_bytes(bucket, object_name, data, *, content_type):
        assert bucket == "ocr-artifacts"
        assert data
        assert content_type in {"application/zip", "application/json"}
        stored_names.append(object_name)
        return f"minio://ocr-artifacts/{object_name}"

    monkeypatch.setattr(tasks.object_storage, "put_bytes", put_bytes)

    output = tasks.mineru_ocr_extract.run(job["id"])

    assert output["status"] == "success"
    assert output["parseResultId"] == "PARSE-MINERU-1"
    assert repository.find_one("ocr_jobs", job["id"])["status"] == "success"
    assert repository.find_one(
        "ocr_parse_results",
        "PARSE-MINERU-1",
        id_field="parseResultId",
    )
    assert repository.find_one("documents", "DOC-MINERU-1")[
        "currentOcrStatus"
    ] == "已识别"
    assert progress_snapshots == [("poll", 42)]
    assert job["providerProgress"] == {
        "extractedPages": 1,
        "totalPages": 2,
    }
    assert stored_names == [
        f"pipelines/mineru/{job['id']}/mineru-result.zip",
        f"pipelines/mineru/{job['id']}/normalized-result.json",
    ]
    assert job["artifactReferences"]["original_zip"]["sha256"].startswith(
        "c7c5"
    )
    assert pipeline_run["status"] == "completed"
    assert pipeline_run["parseResultId"] == "PARSE-MINERU-1"
    assert pipeline_run["provider"] == "mineru"
    assert pipeline_run["blockingReasons"] == []
    assert pipeline_run["formalEvidenceReady"] is True
    stage_status = {
        stage["stage"]: stage["status"]
        for stage in repository.ocr_pipeline_stages(pipeline_run["id"])
    }
    assert stage_status["text_scan"] == "success"
    assert stage_status["evidence_fusion"] == "success"


def test_unbound_url_job_never_mutates_business_documents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = InMemoryRepository()
    job = repository.create_ocr_job_record(
        document_id="",
        version_id="",
        storage_key="https://files.example/doc.pdf",
        file_name="doc.pdf",
        provider="mineru",
        source_url="https://files.example/doc.pdf",
        options={},
    )
    submitted: list[str] = []

    class FakeClient:
        def submit_url(self, url, *, data_id, options):
            submitted.append(url)
            return {"kind": "task", "providerTaskId": "TASK-1"}

        def wait_for_result(self, _submission, *, progress_callback):
            return {
                "state": "done",
                "extract_progress": None,
                "full_zip_url": "https://cdn.example/result.zip",
            }

        def download_result(self, _url):
            return b"zip"

    monkeypatch.setattr(tasks, "repo", repository)
    monkeypatch.setattr(tasks, "MinerUClient", FakeClient)
    monkeypatch.setattr(
        tasks,
        "normalize_mineru_zip",
        lambda *_args, **_kwargs: _bundle(job["storageKey"]),
    )
    monkeypatch.setattr(tasks, "flush_state_records", lambda _records: None)
    monkeypatch.setattr(
        tasks.object_storage,
        "put_bytes",
        lambda _bucket, object_name, *_args, **_kwargs: (
            f"minio://ocr-artifacts/{object_name}"
        ),
    )
    monkeypatch.setattr(
        repository,
        "apply_ocr_result",
        lambda *_args: pytest.fail("unbound Job must not apply business OCR"),
    )

    output = tasks.mineru_ocr_extract.run(job["id"])

    assert output["status"] == "success"
    assert submitted == ["https://files.example/doc.pdf"]


def test_artifact_storage_unavailable_fails_job_instead_of_losing_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = InMemoryRepository()
    job = repository.create_ocr_job_record(
        document_id="",
        version_id="",
        storage_key="https://files.example/doc.pdf",
        file_name="doc.pdf",
        provider="mineru",
        source_url="https://files.example/doc.pdf",
        options={},
    )

    class FakeClient:
        def submit_url(self, *_args, **_kwargs):
            return {"kind": "task", "providerTaskId": "TASK-1"}

        def wait_for_result(self, _submission, *, progress_callback):
            return {
                "state": "done",
                "extract_progress": None,
                "full_zip_url": "https://cdn.example/result.zip",
            }

        def download_result(self, _url):
            return b"zip"

    monkeypatch.setattr(tasks, "repo", repository)
    monkeypatch.setattr(tasks, "MinerUClient", FakeClient)
    monkeypatch.setattr(
        tasks,
        "normalize_mineru_zip",
        lambda *_args, **_kwargs: _bundle(job["storageKey"]),
    )
    monkeypatch.setattr(tasks, "flush_state_records", lambda _records: None)
    monkeypatch.setattr(tasks.object_storage, "endpoint", "127.0.0.1:9000")
    monkeypatch.setattr(
        tasks.object_storage,
        "put_bytes",
        lambda *_args, **_kwargs: None,
    )

    output = tasks.mineru_ocr_extract.run(job["id"])

    assert output["status"] == "failed"
    assert output["diagnostics"][0]["code"] == "MINERU_PERSIST_FAILED"
    assert job["status"] == "failed"


def test_nonretryable_mineru_failure_is_persisted_without_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = InMemoryRepository()
    repository.state["documents"].append({"id": "DOC-FAIL"})
    repository.state["versions"].append(
        {"id": "VER-FAIL", "documentId": "DOC-FAIL"}
    )
    job = repository.create_ocr_job_record(
        document_id="DOC-FAIL",
        version_id="VER-FAIL",
        storage_key="https://files.example/doc.pdf",
        file_name="doc.pdf",
        provider="mineru",
        source_url="https://files.example/doc.pdf",
        options={},
    )
    pipeline_run = repository.create_or_resume_ocr_pipeline_run(
        run_key="DOC-FAIL:VER-FAIL",
        document_id="DOC-FAIL",
        version_id="VER-FAIL",
        storage_key="https://files.example/doc.pdf",
        storage_bucket=None,
        file_name="doc.pdf",
        profile_id="generic_document_v1",
        document_type="generic_document",
        mode="active",
        pipeline_version="test",
    )
    pipeline_run["ocrJobRecordId"] = job["id"]
    job["pipelineRunId"] = pipeline_run["id"]
    persisted: list[dict[str, list[dict[str, object]]]] = []

    class FakeClient:
        def submit_url(self, *_args, **_kwargs):
            raise MinerUProtocolError(
                "A0202",
                "MinerU rejected the request.",
                retryable=False,
            )

    monkeypatch.setattr(tasks, "repo", repository)
    monkeypatch.setattr(tasks, "MinerUClient", FakeClient)
    monkeypatch.setattr(
        tasks,
        "flush_state_records",
        lambda records: persisted.append(records),
    )

    output = tasks.mineru_ocr_extract.run(job["id"])

    assert output == {
        "jobId": job["id"],
        "status": "failed",
        "diagnostics": [
            {
                "code": "A0202",
                "level": "error",
                "retryable": False,
                "stage": "submit",
            }
        ],
    }
    assert job["status"] == "failed"
    assert "sk-" not in str(job)
    assert job["diagnostics"][0]["stage"] == "submit"
    assert pipeline_run["status"] == "failed"
    assert "ocr_pipeline_runs" in persisted[-1]
    assert "ocr_stage_runs" in persisted[-1]


def test_dispatch_mineru_ocr_targets_remote_queue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []
    monkeypatch.setenv("AICHECK_TASK_DISPATCH", "celery")
    monkeypatch.setattr(
        tasks.mineru_ocr_extract,
        "apply_async",
        lambda **kwargs: calls.append(kwargs) or SimpleNamespace(id="CELERY-1"),
    )

    tenant_token = set_request_tenant_id("TENANT-MINERU")
    try:
        output = task_dispatcher.dispatch_mineru_ocr("OCRJOB-1")
    finally:
        reset_request_tenant_id(tenant_token)

    assert output == {
        "mode": "celery",
        "taskId": "CELERY-1",
        "queue": "ocr.remote",
        "priority": 9,
        "statusReason": "mineru_ocr_queued",
    }
    assert calls[0]["args"] == ["OCRJOB-1", "TENANT-MINERU"]
    assert calls[0]["queue"] == "ocr.remote"


def test_mineru_worker_resumes_existing_provider_task_without_resubmit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = {
        "id": "OCRJOB-RESUME-1",
        "sourceType": "url",
        "sourceUrl": "https://files.example/doc.pdf",
        "storageKey": "https://files.example/doc.pdf",
        "fileName": "doc.pdf",
        "providerTaskId": "TASK-EXISTING",
        "providerTaskType": "task",
        "options": {},
    }
    waited: list[dict[str, str]] = []

    class FakeClient:
        def submit_url(self, *_args, **_kwargs):
            raise AssertionError("existing provider task must not be resubmitted")

        def wait_for_result(self, submission, *, progress_callback):
            waited.append(submission)
            return {
                "state": "done",
                "full_zip_url": "https://cdn.example/result.zip",
            }

        def download_result(self, _url):
            return b"zip"

    monkeypatch.setattr(tasks, "MinerUClient", FakeClient)
    monkeypatch.setattr(tasks, "_persist_mineru_job", lambda _job: None)
    monkeypatch.setattr(
        tasks,
        "normalize_mineru_zip",
        lambda *_args, **_kwargs: _bundle(job["storageKey"]),
    )
    monkeypatch.setattr(
        tasks,
        "_store_mineru_artifacts",
        lambda *_args, **_kwargs: {},
    )

    result = tasks.run_mineru_job(job)

    assert result["status"] == "success"
    assert waited == [
        {
            "kind": "task",
            "providerTaskId": "TASK-EXISTING",
        }
    ]


def test_mineru_worker_reissues_batch_when_checkpoint_is_waiting_for_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "doc.pdf"
    source.write_bytes(b"%PDF-test")
    job = {
        "id": "OCRJOB-REISSUE-1",
        "sourceType": "storage",
        "storageKey": "minio://documents/doc.pdf",
        "fileName": "doc.pdf",
        "providerTaskId": "BATCH-STALE",
        "providerTaskType": "batch",
        "providerUploadState": "allocated",
        "options": {},
    }
    submitted: list[str] = []
    waited: list[dict[str, str]] = []

    class FakeClient:
        def submission_state(self, submission):
            assert submission["providerTaskId"] == "BATCH-STALE"
            return "waiting-file"

        def submit_file(
            self,
            path,
            *,
            data_id,
            options,
            submission_callback,
        ):
            submitted.append(str(path))
            submission = {
                "kind": "batch",
                "providerTaskId": "BATCH-REISSUED",
            }
            submission_callback(
                {**submission, "uploadState": "allocated"}
            )
            submission_callback(
                {**submission, "uploadState": "uploaded"}
            )
            return submission

        def wait_for_result(self, submission, *, progress_callback):
            waited.append(submission)
            return {
                "state": "done",
                "full_zip_url": "https://cdn.example/result.zip",
            }

        def download_result(self, _url):
            return b"zip"

    monkeypatch.setattr(tasks, "MinerUClient", FakeClient)
    monkeypatch.setattr(
        tasks,
        "mineru_source_path",
        lambda _job: (source, None),
    )
    monkeypatch.setattr(tasks, "_persist_mineru_job", lambda _job: None)
    monkeypatch.setattr(
        tasks,
        "normalize_mineru_zip",
        lambda *_args, **_kwargs: _bundle(job["storageKey"]),
    )
    monkeypatch.setattr(
        tasks,
        "_store_mineru_artifacts",
        lambda *_args, **_kwargs: {},
    )

    result = tasks.run_mineru_job(job)

    assert result["status"] == "success"
    assert submitted == [str(source)]
    assert job["providerTaskId"] == "BATCH-REISSUED"
    assert job["providerUploadState"] == "uploaded"
    assert waited == [
        {
            "kind": "batch",
            "providerTaskId": "BATCH-REISSUED",
        }
    ]


def test_failed_pipeline_uses_only_explicit_blocking_reasons(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = InMemoryRepository()
    job = repository.create_ocr_job_record(
        document_id="",
        version_id="",
        storage_key="https://files.example/doc.pdf",
        file_name="doc.pdf",
        provider="mineru",
        source_url="https://files.example/doc.pdf",
        options={},
    )
    pipeline_run = repository.create_or_resume_ocr_pipeline_run(
        run_key="MINERU-EXPLICIT-BLOCKERS",
        document_id="",
        version_id="",
        storage_key="https://files.example/doc.pdf",
        storage_bucket=None,
        file_name="doc.pdf",
        profile_id="generic_document_v1",
        document_type="generic_document",
        mode="active",
        pipeline_version="test",
    )
    job["pipelineRunId"] = pipeline_run["id"]
    monkeypatch.setattr(tasks, "repo", repository)

    tasks._finalize_mineru_pipeline(
        job,
        {
            "status": "failed",
            "outcomeStatus": "failed",
            "quality": {
                "reasons": [
                    {
                        "code": "MINERU_DIAGNOSTIC_ONLY",
                        "level": "warning",
                    }
                ]
            },
        },
        None,
    )

    assert pipeline_run["blockingReasons"] == []


def test_terminal_mineru_job_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = InMemoryRepository()
    job = repository.create_ocr_job_record(
        document_id="",
        version_id="",
        storage_key="https://files.example/doc.pdf",
        file_name="doc.pdf",
        provider="mineru",
        source_url="https://files.example/doc.pdf",
        options={},
    )
    job.update(
        {
            "status": "success",
            "stage": "completed",
            "progress": 100,
            "parseResultId": "PARSE-EXISTING",
        }
    )
    monkeypatch.setattr(tasks, "repo", repository)
    monkeypatch.setattr(tasks, "refresh_worker_state", lambda *_args: None)
    monkeypatch.setattr(
        tasks,
        "run_mineru_job",
        lambda _job: pytest.fail("terminal job must not execute again"),
    )

    output = tasks.mineru_ocr_extract.run(job["id"])

    assert output == {
        "jobId": job["id"],
        "status": "success",
        "parseResultId": "PARSE-EXISTING",
        "alreadyCompleted": True,
    }


def test_mineru_worker_uses_dispatched_tenant_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = InMemoryRepository()
    tenant_token = set_request_tenant_id("TENANT-REMOTE")
    try:
        job = repository.create_ocr_job_record(
            document_id="",
            version_id="",
            storage_key="https://files.example/doc.pdf",
            file_name="doc.pdf",
            provider="mineru",
            source_url="https://files.example/doc.pdf",
            options={},
        )
    finally:
        reset_request_tenant_id(tenant_token)
    observed: list[str] = []
    original_tenant = current_tenant_id()

    def fail_in_tenant(_job):
        observed.append(current_tenant_id())
        raise MinerUProtocolError(
            "A0202",
            "Rejected.",
            retryable=False,
        )

    monkeypatch.setattr(tasks, "repo", repository)
    monkeypatch.setattr(tasks, "refresh_worker_state", lambda *_args: None)
    monkeypatch.setattr(tasks, "run_mineru_job", fail_in_tenant)
    monkeypatch.setattr(tasks, "flush_state_records", lambda _records: None)

    tasks.mineru_ocr_extract.run(job["id"], "TENANT-REMOTE")

    assert observed == ["TENANT-REMOTE"]
    assert current_tenant_id() == original_tenant


@pytest.mark.parametrize(
    ("ocr_options", "configured_default", "expected_provider"),
    [
        ({"provider": "mineru"}, "local", "mineru"),
        ({"provider": "local"}, "mineru", "local"),
        ({}, None, "mineru"),
        ({}, "   ", "mineru"),
        ({}, "local", "local"),
        ({}, "unsupported", "unsupported"),
    ],
)
def test_document_ocr_resolves_explicit_or_configured_provider(
    ocr_options: dict[str, str],
    configured_default: str | None,
    expected_provider: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if configured_default is None:
        monkeypatch.delenv(
            "AICHECK_OCR_DEFAULT_PROVIDER",
            raising=False,
        )
    else:
        monkeypatch.setenv(
            "AICHECK_OCR_DEFAULT_PROVIDER",
            configured_default,
        )
    repository = InMemoryRepository()
    repository.state["documents"] = [
        {
            "id": "DOC-PROVIDER-1",
            "fileName": "doc.pdf",
            "ocrProfileId": "generic_document_v1",
        }
    ]
    repository.state["versions"] = [
        {
            "id": "VER-PROVIDER-1",
            "documentId": "DOC-PROVIDER-1",
            "storageKey": "minio://documents/doc.pdf",
            "ocrOptions": ocr_options,
        }
    ]
    remote_jobs: list[str] = []
    local_calls: list[str] = []
    lifecycle_events: list[str] = []
    monkeypatch.setattr(tasks, "repo", repository)
    monkeypatch.setattr(tasks, "refresh_ocr_worker_state", lambda *_args: None)
    monkeypatch.setattr(tasks, "pipeline_enabled", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        tasks,
        "persist_ocr_pipeline_progress",
        lambda *_args, **_kwargs: lifecycle_events.append("persist"),
    )
    monkeypatch.setattr(
        tasks,
        "flush_state_records",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        tasks.task_dispatcher,
        "dispatch_mineru_ocr",
        lambda job_id: lifecycle_events.append("dispatch")
        or remote_jobs.append(job_id)
        or {
            "mode": "celery",
            "taskId": "CELERY-MINERU-1",
            "queue": "ocr.remote",
        },
    )

    def local_result(storage_key, **_kwargs):
        local_calls.append(storage_key)
        return _result(storage_key)

    monkeypatch.setattr(tasks, "parse_with_ocr_service", local_result)

    output = tasks.parse_document.run(
        "DOC-PROVIDER-1",
        "VER-PROVIDER-1",
        "minio://documents/doc.pdf",
        "doc.pdf",
    )

    if expected_provider == "unsupported":
        assert output["status"] == "failed"
        assert output["diagnostics"] == [
            {
                "code": "OCR_PROVIDER_UNSUPPORTED",
                "level": "error",
            }
        ]
        assert remote_jobs == []
        assert local_calls == []
    elif expected_provider == "mineru":
        assert output["status"] == "queued"
        assert output["provider"] == "mineru"
        assert len(remote_jobs) == 1
        assert local_calls == []
        job = repository.find_one("ocr_jobs", output["ocrJobRecordId"])
        assert job["provider"] == "mineru"
        assert job["options"]["provider"] == "mineru"
        assert job["pipelineRunId"] == output["pipelineRunId"]
        assert lifecycle_events[:2] == ["persist", "dispatch"]
    else:
        assert output["status"] == "success"
        assert remote_jobs == []
        assert local_calls == ["minio://documents/doc.pdf"]
