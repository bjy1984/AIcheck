from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

import httpx

from apps.ocr_service.jobs import DocumentParseJobStore
from libs.integrations.ocr_client import OcrClient, ocr_job_request_key


def test_job_store_reuses_queued_running_and_success_jobs(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("AICHECK_OCR_JOB_STORE_PATH", str(tmp_path / "jobs.json"))
    store = DocumentParseJobStore()
    payload = {
        "requestKey": "ocrjob:stable",
        "storageKey": "minio://documents/source.pdf",
        "documentVersionId": "DV-1",
    }

    created = store.create(payload)
    queued_reuse = store.create(payload)
    store.mark_running(created["jobId"])
    running_reuse = store.create(payload)
    store.mark_finished(created["jobId"], {"status": "success", "fragments": [{"text": "ok"}]})
    success_reuse = store.create(payload)

    assert queued_reuse["jobId"] == created["jobId"]
    assert running_reuse["jobId"] == created["jobId"]
    assert success_reuse["jobId"] == created["jobId"]
    assert queued_reuse["reused"] is True
    assert running_reuse["reused"] is True
    assert success_reuse["reused"] is True


def test_job_store_concurrent_create_is_atomic(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("AICHECK_OCR_JOB_STORE_PATH", str(tmp_path / "jobs.json"))
    store = DocumentParseJobStore()
    payload = {"requestKey": "ocrjob:concurrent", "storageKey": "minio://documents/source.pdf"}

    with ThreadPoolExecutor(max_workers=8) as executor:
        jobs = list(executor.map(lambda _index: store.create(payload), range(32)))

    assert len({job["jobId"] for job in jobs}) == 1
    assert len(store._jobs) == 1


def test_job_store_allows_new_job_after_actual_failure(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("AICHECK_OCR_JOB_STORE_PATH", str(tmp_path / "jobs.json"))
    store = DocumentParseJobStore()
    payload = {"requestKey": "ocrjob:failed", "storageKey": "minio://documents/source.pdf"}

    failed = store.create(payload)
    store.mark_finished(failed["jobId"], {"status": "failed", "diagnostics": ["failed"]})
    replacement = store.create(payload)

    assert replacement["jobId"] != failed["jobId"]
    assert replacement.get("reused") is not True


def test_job_store_marks_non_terminal_jobs_failed_after_service_restart(monkeypatch, tmp_path) -> None:
    path = tmp_path / "jobs.json"
    monkeypatch.setenv("AICHECK_OCR_JOB_STORE_PATH", str(path))
    store = DocumentParseJobStore()
    payload = {"requestKey": "ocrjob:restart", "storageKey": "minio://documents/source.pdf"}
    queued = store.create(payload)
    store.mark_running(queued["jobId"])

    restarted = DocumentParseJobStore()
    interrupted = restarted.get_job(queued["jobId"])
    replacement = restarted.create(payload)

    assert interrupted is not None
    assert interrupted["status"] == "failed"
    assert interrupted["finishedAt"]
    assert any(
        item.get("code") == "OCR_SERVICE_RESTARTED"
        for item in interrupted.get("diagnostics") or []
    )
    assert replacement["jobId"] != queued["jobId"]
    assert replacement.get("reused") is not True


def test_ocr_client_adds_stable_request_key() -> None:
    captured = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(200, json={"code": 0, "data": {"jobId": "OCRJOB-1", "status": "queued"}})

    payload = {
        "storageKey": "minio://documents/source.pdf",
        "documentVersionId": "DV-1",
        "profileId": "quality_certificate_v1",
        "options": {"maxPages": 7, "deepScanPdf": True},
    }
    client = OcrClient(base_url="http://ocr", transport=httpx.MockTransport(handler))

    client.create_parse_job(payload)
    client.create_parse_job(payload)

    expected = ocr_job_request_key(payload)
    assert captured[0]["requestKey"] == expected
    assert captured[1]["requestKey"] == expected
    assert expected.startswith("ocrjob:")
