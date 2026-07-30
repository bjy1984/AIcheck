from __future__ import annotations

import base64
import json
import socket

import pytest
from fastapi.testclient import TestClient

from apps.api import mineru_ocr_routes
from apps.api.main import app
from libs.db.repository import InMemoryRepository


client = TestClient(app)


@pytest.fixture
def api_repository(monkeypatch: pytest.MonkeyPatch) -> InMemoryRepository:
    repository = InMemoryRepository()
    repository.state["ocr_jobs"] = []
    repository.state["ocr_parse_results"] = []
    monkeypatch.setattr(mineru_ocr_routes, "repo", repository)
    monkeypatch.setattr(
        mineru_ocr_routes,
        "flush_state_records",
        lambda _records: None,
    )
    monkeypatch.setattr(
        mineru_ocr_routes.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                ("8.8.8.8", 443),
            )
        ],
    )
    return repository


def test_create_url_mineru_task(
    monkeypatch: pytest.MonkeyPatch,
    api_repository: InMemoryRepository,
) -> None:
    monkeypatch.setattr(
        mineru_ocr_routes.task_dispatcher,
        "dispatch_mineru_ocr",
        lambda _job_id: {
            "mode": "celery",
            "taskId": "CELERY-1",
            "queue": "ocr.remote",
        },
    )

    response = client.post(
        "/internal/ocr/mineru/tasks",
        json={
            "url": "https://files.example/document.pdf",
            "fileName": "document.pdf",
            "profileId": "generic_document_v1",
            "language": "ch",
            "pageRanges": "1-3",
        },
    )

    assert response.status_code == 200
    assert response.json()["code"] == 0
    data = response.json()["data"]
    assert data["status"] == "queued"
    assert data["provider"] == "mineru"
    assert data["model"] == "vlm"
    assert data["pollUrl"].endswith(data["jobId"])
    stored = api_repository.find_one("ocr_jobs", data["jobId"])
    assert stored["options"] == {
        "language": "ch",
        "pageRanges": "1-3",
    }


@pytest.mark.parametrize(
    "payload",
    [
        {"fileName": "document.pdf"},
        {
            "url": "https://files.example/document.pdf",
            "storageKey": "minio://documents/document.pdf",
            "fileName": "document.pdf",
        },
        {
            "url": "https://files.example/document.exe",
            "fileName": "document.exe",
        },
        {
            "url": "https://files.example/document.pdf?token=secret",
            "fileName": "document.pdf",
        },
        {
            "url": "https://files.example/document.pdf",
            "fileName": "document.pdf",
            "pageRanges": "1-201",
        },
        {
            "url": "https://files.example/document.pdf",
            "fileName": "document.pdf",
            "model_version": "pipeline",
        },
    ],
)
def test_rejects_invalid_sources_and_options(
    payload: dict[str, object],
    api_repository: InMemoryRepository,
) -> None:
    response = client.post("/internal/ocr/mineru/tasks", json=payload)

    assert response.status_code == 200
    assert response.json()["code"] != 0
    assert api_repository.state["ocr_jobs"] == []


@pytest.mark.parametrize(
    "address",
    ["127.0.0.1", "10.0.0.1", "169.254.169.254", "2001:db8::1"],
)
def test_rejects_urls_resolving_to_non_public_addresses(
    address: str,
    monkeypatch: pytest.MonkeyPatch,
    api_repository: InMemoryRepository,
) -> None:
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    monkeypatch.setattr(
        mineru_ocr_routes.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (
                family,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                (address, 443),
            )
        ],
    )

    response = client.post(
        "/internal/ocr/mineru/tasks",
        json={
            "url": "https://files.example/document.pdf",
            "fileName": "document.pdf",
        },
    )

    assert response.json()["code"] != 0
    assert address not in str(response.json())


def test_dispatch_unavailable_marks_job_failed(
    monkeypatch: pytest.MonkeyPatch,
    api_repository: InMemoryRepository,
) -> None:
    monkeypatch.setattr(
        mineru_ocr_routes.task_dispatcher,
        "dispatch_mineru_ocr",
        lambda _job_id: {
            "mode": "disabled",
            "taskId": None,
            "statusReason": "mineru_ocr_requires_task_dispatch",
        },
    )

    response = client.post(
        "/internal/ocr/mineru/tasks",
        json={
            "storageKey": "minio://documents/document.pdf",
            "fileName": "document.pdf",
        },
    )

    assert response.json()["code"] == 0
    data = response.json()["data"]
    assert data["status"] == "failed"
    job = api_repository.find_one("ocr_jobs", data["jobId"])
    assert job["stage"] == "dispatch"
    assert job["diagnostics"][0]["code"] == "MINERU_DISPATCH_UNAVAILABLE"


def test_status_read_exposes_safe_summary_only(
    monkeypatch: pytest.MonkeyPatch,
    api_repository: InMemoryRepository,
) -> None:
    job = api_repository.create_ocr_job_record(
        document_id="",
        version_id="",
        storage_key="https://files.example/document.pdf",
        file_name="document.pdf",
        provider="mineru",
        source_url="https://files.example/document.pdf",
        options={"language": "ch"},
    )
    job["artifactReferences"] = {
        "normalized_json": {
            "storageUrl": "minio://ocr-artifacts/result.json",
            "sha256": "abc",
        }
    }
    job["internalSecret"] = "sk-must-not-leak"

    response = client.get(f"/internal/ocr/mineru/tasks/{job['id']}")

    assert response.json()["code"] == 0
    data = response.json()["data"]
    assert data["jobId"] == job["id"]
    assert data["artifactReferences"] == job["artifactReferences"]
    assert "internalSecret" not in data
    assert "sk-must-not-leak" not in str(response.json())


def _metadata_header(metadata: dict[str, object]) -> str:
    return base64.b64encode(
        json.dumps(metadata, ensure_ascii=False).encode("utf-8")
    ).decode("ascii")


def test_raw_upload_stores_bytes_and_creates_storage_job(
    monkeypatch: pytest.MonkeyPatch,
    api_repository: InMemoryRepository,
) -> None:
    stored: list[tuple[str, str, bytes, str]] = []

    def put_bytes(bucket, object_name, data, *, content_type):
        stored.append((bucket, object_name, data, content_type))
        return f"minio://{bucket}/{object_name}"

    monkeypatch.setattr(
        mineru_ocr_routes.object_storage,
        "put_bytes",
        put_bytes,
    )
    monkeypatch.setattr(
        mineru_ocr_routes.task_dispatcher,
        "dispatch_mineru_ocr",
        lambda _job_id: {
            "mode": "celery",
            "taskId": "CELERY-1",
            "queue": "ocr.remote",
        },
    )

    response = client.post(
        "/internal/ocr/mineru/tasks/upload",
        content=b"%PDF-upload",
        headers={
            "Content-Type": "application/pdf",
            "X-AICheck-Ocr-Metadata-B64": _metadata_header(
                {
                    "fileName": "uploaded.pdf",
                    "profileId": "generic_document_v1",
                }
            ),
        },
    )

    assert response.json()["code"] == 0
    data = response.json()["data"]
    job = api_repository.find_one("ocr_jobs", data["jobId"])
    assert job["sourceType"] == "storage"
    assert job["storageKey"].startswith("minio://ocr-artifacts/")
    assert stored[0][0] == "ocr-artifacts"
    assert stored[0][2] == b"%PDF-upload"


@pytest.mark.parametrize(
    ("header", "body"),
    [
        ("not-base64", b"%PDF"),
        (_metadata_header({"fileName": "uploaded.pdf"}), b""),
    ],
)
def test_raw_upload_rejects_bad_metadata_and_empty_body(
    header: str,
    body: bytes,
    api_repository: InMemoryRepository,
) -> None:
    response = client.post(
        "/internal/ocr/mineru/tasks/upload",
        content=body,
        headers={"X-AICheck-Ocr-Metadata-B64": header},
    )

    assert response.json()["code"] != 0
    assert api_repository.state["ocr_jobs"] == []


def test_raw_upload_enforces_size_and_storage_availability(
    monkeypatch: pytest.MonkeyPatch,
    api_repository: InMemoryRepository,
) -> None:
    monkeypatch.setattr(mineru_ocr_routes, "MAX_UPLOAD_BYTES", 4)
    header = _metadata_header({"fileName": "uploaded.pdf"})

    too_large = client.post(
        "/internal/ocr/mineru/tasks/upload",
        content=b"12345",
        headers={"X-AICheck-Ocr-Metadata-B64": header},
    )
    assert too_large.json()["code"] != 0

    monkeypatch.setattr(mineru_ocr_routes, "MAX_UPLOAD_BYTES", 200 * 1024 * 1024)
    monkeypatch.setattr(
        mineru_ocr_routes.object_storage,
        "put_bytes",
        lambda *_args, **_kwargs: None,
    )
    unavailable = client.post(
        "/internal/ocr/mineru/tasks/upload",
        content=b"%PDF",
        headers={"X-AICheck-Ocr-Metadata-B64": header},
    )
    assert unavailable.json()["code"] != 0
    assert api_repository.state["ocr_jobs"] == []

