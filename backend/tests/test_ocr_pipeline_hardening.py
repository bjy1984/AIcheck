from __future__ import annotations

import inspect
import json
import threading
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from libs.capacity_guard import GIB, cpu_heavy_dispatch_status, disk_capacity_status, swap_capacity
from libs.db.repository import InMemoryRepository
from libs.pipeline_lock import (
    PipelineLockUnavailable,
    advisory_lock_id,
    pipeline_lock,
    pipeline_task_lock,
)
from scripts.ocr_accuracy_pipeline_batch import (
    register_state_record,
    safe_campaign,
    select_cases,
    stage_engine_gate,
)


def test_regression_case_selection_starts_with_cold_probes() -> None:
    cases = [
        {"caseId": "NORMAL-1"},
        {"caseId": "COLD-1", "coldProbe": True},
        {"caseId": "NORMAL-2"},
        {"caseId": "COLD-2", "coldProbe": True},
        {"caseId": "COLD-3", "coldProbe": True},
    ]

    assert [item["caseId"] for item in select_cases(cases, 2)] == ["COLD-1", "COLD-2"]
    assert [item["caseId"] for item in select_cases(cases, 4)] == [
        "COLD-1",
        "COLD-2",
        "COLD-3",
        "NORMAL-1",
    ]


def test_campaign_is_safe_for_object_names() -> None:
    assert safe_campaign(" scan regression/2026 ") == "scan-regression-2026"


def test_state_registration_is_an_upsert(monkeypatch) -> None:
    from scripts import ocr_accuracy_pipeline_batch as batch

    monkeypatch.setattr(batch.repo, "state", {"documents": []})
    register_state_record("documents", {"id": "DOC-1", "value": 1})
    register_state_record("documents", {"id": "DOC-1", "value": 2})

    assert batch.repo.state["documents"] == [{"id": "DOC-1", "value": 2}]


def test_cold_probe_requires_real_positive_duration() -> None:
    cached_stage = {
        "status": "success",
        "engineStatus": {
            "engineExecuted": ["pp_structure_v3"],
            "engineSucceeded": ["pp_structure_v3"],
            "runs": [{"engine": "pp_structure_v3", "status": "success", "durationMs": 5, "engineCacheHit": True}],
        },
    }
    warm_gate = stage_engine_gate(
        cached_stage,
        expected=True,
        expected_engine="pp_structure_v3",
        cold_probe=False,
    )
    cold_gate = stage_engine_gate(
        cached_stage,
        expected=True,
        expected_engine="pp_structure_v3",
        cold_probe=True,
    )

    assert warm_gate["passed"] is True
    assert cold_gate["passed"] is False


def test_stage_engine_gate_rejects_executed_engine_that_failed() -> None:
    failed_stage = {
        "status": "success",
        "engineStatus": {
            "engineExecuted": ["pp_structure_v3"],
            "engineSucceeded": ["opencv_table_grid_subprocess"],
            "runs": [
                {"engine": "pp_structure_v3", "status": "failed", "durationMs": 1200},
                {"engine": "opencv_table_grid_subprocess", "status": "success", "durationMs": 20},
            ],
        },
    }

    gate = stage_engine_gate(
        failed_stage, expected=True, expected_engine="pp_structure_v3", cold_probe=True
    )

    assert gate["engineExecuted"] is True
    assert gate["engineSucceeded"] is False
    assert gate["passed"] is False


def test_disk_capacity_thresholds_gate_dispatch(monkeypatch) -> None:
    monkeypatch.setattr(
        "libs.capacity_guard.shutil.disk_usage",
        lambda _path: SimpleNamespace(total=100 * GIB, used=89 * GIB, free=11 * GIB),
    )
    monkeypatch.setenv("AICHECK_CPU_HEAVY_DISK_GATE", "true")

    status = disk_capacity_status("/")
    dispatch = cpu_heavy_dispatch_status()

    assert status["status"] == "paused"
    assert status["readinessReady"] is True
    assert dispatch["allowed"] is False
    assert dispatch["statusReason"] == "disk_capacity_paused"


def test_swap_capacity_parses_linux_proc_format(tmp_path: Path) -> None:
    swaps = tmp_path / "swaps"
    swaps.write_text(
        "Filename Type Size Used Priority\n/data/aicheck.swap file 8388608 0 -2\n",
        encoding="utf-8",
    )

    result = swap_capacity(swaps)

    assert result["totalBytes"] == 8 * GIB
    assert result["devices"][0]["name"] == "/data/aicheck.swap"


def test_pipeline_lock_is_non_blocking_and_process_local_without_postgres(monkeypatch) -> None:
    monkeypatch.delenv("AICHECK_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("AICHECK_STRICT_PRODUCTION", "false")
    entered = threading.Event()
    release = threading.Event()
    results: list[bool] = []

    def hold_lock() -> None:
        with pipeline_lock("RUN-1") as acquired:
            results.append(acquired)
            entered.set()
            release.wait(timeout=2)

    thread = threading.Thread(target=hold_lock)
    thread.start()
    entered.wait(timeout=2)
    with pipeline_lock("RUN-1") as acquired:
        results.append(acquired)
    release.set()
    thread.join(timeout=2)

    assert results == [True, False]
    assert advisory_lock_id("RUN-1") == advisory_lock_id("RUN-1")


def test_pipeline_task_lock_retries_when_postgres_lock_is_temporarily_unavailable(monkeypatch) -> None:
    from libs import pipeline_lock as lock_module

    @contextmanager
    def unavailable(_key: str):
        raise PipelineLockUnavailable("postgres unavailable")
        yield False

    class RetryScheduled(Exception):
        pass

    class FakeTask:
        request = SimpleNamespace(retries=0)
        max_retries = 3

        def retry(self, *, exc, countdown):
            assert isinstance(exc, PipelineLockUnavailable)
            assert countdown == 10
            return RetryScheduled()

    monkeypatch.setattr(lock_module, "pipeline_lock", unavailable)

    @pipeline_task_lock("test", lambda _task, value: value)
    def guarded(_task, _value):
        return {"status": "unexpected"}

    with pytest.raises(RetryScheduled):
        guarded(FakeTask(), "RUN-1")


def test_stage_ocr_job_and_parse_result_are_idempotent() -> None:
    repository = InMemoryRepository()
    job = repository.create_ocr_job_record(
        document_id="DOC-1",
        version_id="VER-1",
        storage_key="minio://documents/source.pdf",
        record_id="OCRJOB-STAGE-1",
    )
    same_job = repository.create_ocr_job_record(
        document_id="DOC-1",
        version_id="VER-1",
        storage_key="minio://documents/source.pdf",
        record_id="OCRJOB-STAGE-1",
    )
    repository.finish_ocr_job_record(job, {"parseResultId": "PARSE-STAGE-1", "status": "success"})
    repository.finish_ocr_job_record(job, {"parseResultId": "PARSE-STAGE-1", "status": "success"})

    assert same_job is job
    assert len([item for item in repository.state["ocr_jobs"] if item["id"] == "OCRJOB-STAGE-1"]) == 1
    assert len([item for item in repository.state["ocr_parse_results"] if item["id"] == "PARSE-STAGE-1"]) == 1


def test_terminal_pipeline_stage_records_elapsed_seconds(monkeypatch) -> None:
    repository = InMemoryRepository()
    run = repository.create_or_resume_ocr_pipeline_run(
        run_key="RUN-KEY",
        document_id="DOC-1",
        version_id="VER-1",
        storage_key="minio://documents/source.pdf",
        storage_bucket="documents",
        file_name="source.pdf",
        profile_id="ndt_rt_report_v1",
        document_type="ndt_report",
        mode="shadow",
        pipeline_version="test@1",
    )
    stage = repository.ocr_pipeline_stages(run["id"])[0]
    stage["startedAt"] = "2026-07-11 10:00:00"
    monkeypatch.setattr("libs.db.repository.server_time", lambda: "2026-07-11 10:00:12")

    repository.mark_ocr_pipeline_stage(run, "prepare", "success")

    assert stage["elapsedSeconds"] == 12


def test_validation_worker_uploads_isolated_minio_object_to_ocr_service(monkeypatch, tmp_path: Path) -> None:
    from apps.worker import tasks

    downloaded = tmp_path / "download" / "source.pdf"
    downloaded.parent.mkdir()
    downloaded.write_bytes(b"%PDF-test")
    captured: dict = {}

    class FakeClient:
        enabled = True

        def parse_upload_sync(self, path, payload):
            captured["path"] = str(path)
            captured["payload"] = payload
            return {"status": "success", "fragments": [{"text": "ok"}]}

    monkeypatch.setenv("AICHECK_OCR_UPLOAD_OBJECTS", "true")
    monkeypatch.setattr(tasks, "worker_ocr_http_enabled", lambda: True)
    monkeypatch.setattr(tasks, "OcrClient", FakeClient)
    monkeypatch.setattr(tasks.object_storage, "download_to_temp", lambda *_args, **_kwargs: downloaded)

    result = tasks.parse_with_ocr_service(
        "minio://aicheck-ocr-validation-documents/campaign/report.pdf",
        file_name="report.pdf",
        document_id="DOC-1",
        version_id="VER-1",
        profile_id="ndt_rt_report_v1",
    )

    assert result["status"] == "success"
    assert captured["payload"]["profileId"] == "ndt_rt_report_v1"
    assert not downloaded.parent.exists()


def test_fault_proxy_injects_only_configured_request_count(monkeypatch) -> None:
    from scripts import ocr_fault_proxy

    monkeypatch.setenv("AICHECK_FAULT_PROXY_TOKEN", "test-token")
    monkeypatch.setenv("AICHECK_FAULT_PROXY_UPSTREAM", "http://127.0.0.1:9")
    ocr_fault_proxy._fault.update({"mode": "pass", "statusCode": 503, "delaySeconds": 0, "remaining": 0})
    client = TestClient(ocr_fault_proxy.app)

    configured = client.post(
        "/__fault__/configure",
        headers={"Authorization": "Bearer test-token"},
        json={"mode": "status", "statusCode": 429, "remaining": 1},
    )
    first = client.get("/v1/probe")
    second = client.get("/v1/probe")

    assert configured.status_code == 200
    assert first.status_code == 429
    assert second.status_code != 429


def test_release_manifest_can_require_bundle_and_immutable_images(monkeypatch, tmp_path: Path) -> None:
    from scripts import ocr_pipeline_release_manifest as release_manifest

    monkeypatch.setattr(release_manifest, "git_revision", lambda _reference: "a" * 40)
    monkeypatch.setattr(release_manifest, "git_worktree_status", lambda: [])
    args = SimpleNamespace(
        origin_commit="a" * 40,
        bundle=None,
        compose=[],
        image_manifest=None,
        require_origin=True,
        require_bundle=True,
        require_images=True,
        output=None,
    )

    blocked = release_manifest.build_manifest(args)

    assert {item["code"] for item in blocked["blockingReasons"]} == {
        "GIT_BUNDLE_REQUIRED",
        "IMMUTABLE_IMAGE_DIGESTS_REQUIRED",
    }

    bundle = tmp_path / "release.bundle"
    bundle.write_bytes(b"bundle")
    images = tmp_path / "images.json"
    images.write_text(json.dumps({"api": "registry/aicheck-api@sha256:" + "b" * 64}), encoding="utf-8")
    args.bundle = str(bundle)
    args.image_manifest = str(images)

    passed = release_manifest.build_manifest(args)

    assert passed["passed"] is True
    assert passed["imageDigestsComplete"] is True


def test_accuracy_pipeline_workers_never_full_flush_partial_state() -> None:
    from apps.worker import tasks

    partial_state_workers = [
        tasks.parse_document.run,
        tasks.ocr_pipeline_official_extract.run,
        tasks.ocr_pipeline_evidence_fusion.run,
        tasks.ocr_pipeline_qwen_extract.run,
        tasks._ocr_pipeline_finalize_impl,
    ]

    for worker in partial_state_workers:
        source = inspect.getsource(worker)
        assert "flush_state()" not in source, (
            f"{worker.__name__} must use record-level persistence after a scoped state load"
        )
