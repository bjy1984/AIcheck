from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from apps.worker import tasks
from libs.db.repository import InMemoryRepository
from libs.integrations import task_dispatcher
from libs.integrations.mineru_client import MinerUProtocolError
from libs.mineru_ocr import MinerUArtifact


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
        "quality": {"status": "usable", "reasons": []},
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
    progress_snapshots: list[tuple[str, int]] = []
    stored_names: list[str] = []

    class FakeClient:
        def submit_file(self, path, *, data_id, options):
            assert Path(path).read_bytes() == b"%PDF-test"
            assert data_id == job["id"]
            return {"kind": "batch", "providerTaskId": "BATCH-1"}

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
    assert stored_names == [
        f"pipelines/mineru/{job['id']}/mineru-result.zip",
        f"pipelines/mineru/{job['id']}/normalized-result.json",
    ]
    assert job["artifactReferences"]["original_zip"]["sha256"].startswith(
        "c7c5"
    )


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
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        repository,
        "apply_ocr_result",
        lambda *_args: pytest.fail("unbound Job must not apply business OCR"),
    )

    output = tasks.mineru_ocr_extract.run(job["id"])

    assert output["status"] == "success"
    assert submitted == ["https://files.example/doc.pdf"]


def test_nonretryable_mineru_failure_is_persisted_without_secret(
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
            raise MinerUProtocolError(
                "A0202",
                "MinerU rejected the request.",
                retryable=False,
            )

    monkeypatch.setattr(tasks, "repo", repository)
    monkeypatch.setattr(tasks, "MinerUClient", FakeClient)
    monkeypatch.setattr(tasks, "flush_state_records", lambda _records: None)

    output = tasks.mineru_ocr_extract.run(job["id"])

    assert output == {
        "jobId": job["id"],
        "status": "failed",
        "diagnostics": [
            {
                "code": "A0202",
                "level": "error",
                "retryable": False,
            }
        ],
    }
    assert job["status"] == "failed"
    assert "sk-" not in str(job)


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

    output = task_dispatcher.dispatch_mineru_ocr("OCRJOB-1")

    assert output == {
        "mode": "celery",
        "taskId": "CELERY-1",
        "queue": "ocr.remote",
        "priority": 9,
        "statusReason": "mineru_ocr_queued",
    }
    assert calls[0]["args"] == ["OCRJOB-1"]
    assert calls[0]["queue"] == "ocr.remote"

