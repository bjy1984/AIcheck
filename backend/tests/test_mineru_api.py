from __future__ import annotations

import asyncio
import base64
import json
import socket

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

import apps.api.main as api_main
from apps.api import mineru_ocr_routes
from apps.api import routes as api_routes
from apps.api.main import app
from libs.db.repository import InMemoryRepository
from libs.security.actions import required_action_for_request

client = TestClient(app)


@pytest.fixture
def api_repository(monkeypatch: pytest.MonkeyPatch) -> InMemoryRepository:
    repository = InMemoryRepository()
    repository.state["ocr_jobs"] = []
    repository.state["ocr_parse_results"] = []
    monkeypatch.setattr(mineru_ocr_routes, "repo", repository)
    monkeypatch.setattr(api_routes, "repo", repository)
    monkeypatch.setattr(api_main, "flush_state", lambda: None)
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


def test_mineru_mutations_require_ai_recheck_permission() -> None:
    assert (
        required_action_for_request(
            "POST",
            "/internal/ocr/mineru/tasks",
        )
        == "ai:recheck"
    )
    assert (
        required_action_for_request(
            "POST",
            "/api/internal/ocr/mineru/tasks/upload",
        )
        == "ai:recheck"
    )


def test_binary_request_fingerprint_hashes_raw_bytes() -> None:
    def fingerprint(body: bytes) -> str:
        delivered = False

        async def receive():
            nonlocal delivered
            if delivered:
                return {
                    "type": "http.request",
                    "body": b"",
                    "more_body": False,
                }
            delivered = True
            return {
                "type": "http.request",
                "body": body,
                "more_body": False,
            }

        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/internal/ocr/mineru/tasks/upload",
                "query_string": b"",
                "headers": [
                    (b"content-type", b"application/octet-stream"),
                ],
            },
            receive,
        )
        return asyncio.run(api_main.request_fingerprint(request))

    assert fingerprint(b"\x80") != fingerprint(b"\x81")


def test_job_is_durable_before_remote_dispatch(
    monkeypatch: pytest.MonkeyPatch,
    api_repository: InMemoryRepository,
) -> None:
    events: list[str] = []

    def persist(records):
        assert records["ocr_jobs"][0]["status"] == "queued"
        events.append("persist")

    def dispatch(job_id):
        assert api_repository.find_one("ocr_jobs", job_id)
        events.append("dispatch")
        return {
            "mode": "celery",
            "taskId": "CELERY-1",
            "queue": "ocr.remote",
        }

    monkeypatch.setattr(mineru_ocr_routes, "flush_state_records", persist)
    monkeypatch.setattr(
        mineru_ocr_routes.task_dispatcher,
        "dispatch_mineru_ocr",
        dispatch,
    )

    response = client.post(
        "/internal/ocr/mineru/tasks",
        json={
            "url": "https://files.example/document.pdf",
            "fileName": "document.pdf",
        },
    )

    assert response.json()["code"] == 0
    assert events[:2] == ["persist", "dispatch"]


def test_idempotency_key_prevents_duplicate_job_and_dispatch(
    monkeypatch: pytest.MonkeyPatch,
    api_repository: InMemoryRepository,
) -> None:
    dispatched: list[str] = []
    monkeypatch.setattr(
        mineru_ocr_routes.task_dispatcher,
        "dispatch_mineru_ocr",
        lambda job_id: dispatched.append(job_id)
        or {
            "mode": "celery",
            "taskId": "CELERY-1",
            "queue": "ocr.remote",
        },
    )
    payload = {
        "url": "https://files.example/document.pdf",
        "fileName": "document.pdf",
    }
    headers = {"Idempotency-Key": "mineru-url-once"}

    first = client.post(
        "/internal/ocr/mineru/tasks",
        json=payload,
        headers=headers,
    )
    second = client.post(
        "/internal/ocr/mineru/tasks",
        json=payload,
        headers=headers,
    )

    assert first.json()["code"] == 0
    assert second.json()["data"]["jobId"] == first.json()["data"]["jobId"]
    assert dispatched == [first.json()["data"]["jobId"]]
    assert len(api_repository.state["ocr_jobs"]) == 1


def test_storage_source_must_match_bound_document_version(
    monkeypatch: pytest.MonkeyPatch,
    api_repository: InMemoryRepository,
) -> None:
    api_repository.state["documents"] = [{"id": "DOC-1"}]
    api_repository.state["versions"] = [
        {
            "id": "VER-1",
            "documentId": "DOC-1",
            "storageKey": "minio://documents/tenant/doc.pdf",
        }
    ]
    monkeypatch.setattr(
        mineru_ocr_routes.task_dispatcher,
        "dispatch_mineru_ocr",
        lambda _job_id: {
            "mode": "celery",
            "taskId": "CELERY-1",
            "queue": "ocr.remote",
        },
    )

    arbitrary = client.post(
        "/internal/ocr/mineru/tasks",
        json={
            "storageKey": "minio://documents/other.pdf",
            "fileName": "other.pdf",
        },
    )
    mismatched = client.post(
        "/internal/ocr/mineru/tasks",
        json={
            "storageKey": "minio://documents/other.pdf",
            "fileName": "other.pdf",
            "documentId": "DOC-1",
            "documentVersionId": "VER-1",
        },
    )
    local = client.post(
        "/internal/ocr/mineru/tasks",
        json={
            "storageKey": "local://doc.pdf",
            "fileName": "doc.pdf",
            "documentId": "DOC-1",
            "documentVersionId": "VER-1",
        },
    )
    accepted = client.post(
        "/internal/ocr/mineru/tasks",
        json={
            "storageKey": "minio://documents/tenant/doc.pdf",
            "fileName": "doc.pdf",
            "documentId": "DOC-1",
            "documentVersionId": "VER-1",
        },
    )

    assert arbitrary.json()["code"] != 0
    assert mismatched.json()["code"] != 0
    assert local.json()["code"] != 0
    assert accepted.json()["code"] == 0


def test_external_url_and_upload_cannot_overwrite_bound_document(
    monkeypatch: pytest.MonkeyPatch,
    api_repository: InMemoryRepository,
) -> None:
    api_repository.state["documents"] = [{"id": "DOC-1"}]
    api_repository.state["versions"] = [
        {
            "id": "VER-1",
            "documentId": "DOC-1",
            "storageKey": "minio://documents/tenant/doc.pdf",
        }
    ]
    stored: list[bytes] = []
    monkeypatch.setattr(
        mineru_ocr_routes.object_storage,
        "put_bytes",
        lambda _bucket, _name, data, **_kwargs: stored.append(data)
        or "minio://ocr-artifacts/upload.pdf",
    )

    url_response = client.post(
        "/internal/ocr/mineru/tasks",
        json={
            "url": "https://files.example/other.pdf",
            "fileName": "other.pdf",
            "documentId": "DOC-1",
            "documentVersionId": "VER-1",
        },
    )
    upload_response = client.post(
        "/internal/ocr/mineru/tasks/upload",
        content=b"%PDF-other",
        headers={
            "X-AICheck-Ocr-Metadata-B64": _metadata_header(
                {
                    "fileName": "other.pdf",
                    "documentId": "DOC-1",
                    "documentVersionId": "VER-1",
                }
            )
        },
    )

    assert url_response.json()["code"] != 0
    assert upload_response.json()["code"] != 0
    assert stored == []


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
            "url": "https://files.example/document.exe",
            "fileName": "document.pdf",
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
            "url": "https://files.example/document.pdf",
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
    job["providerProgress"] = {
        "extractedPages": 4,
        "totalPages": 10,
    }
    job["internalSecret"] = "sk-must-not-leak"

    response = client.get(f"/internal/ocr/mineru/tasks/{job['id']}")

    assert response.json()["code"] == 0
    data = response.json()["data"]
    assert data["jobId"] == job["id"]
    assert data["artifactReferences"] == job["artifactReferences"]
    assert data["providerProgress"] == {
        "extractedPages": 4,
        "totalPages": 10,
    }
    assert "internalSecret" not in data
    assert "sk-must-not-leak" not in str(response.json())


def test_unbound_job_status_is_limited_to_creator_or_admin(
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
    created = client.post(
        "/internal/ocr/mineru/tasks",
        json={
            "url": "https://files.example/private.pdf",
            "fileName": "private.pdf",
        },
        headers={"X-User-Id": "USER-ALICE"},
    ).json()["data"]

    denied = client.get(
        created["pollUrl"],
        headers={"X-User-Id": "USER-BOB"},
    )
    allowed = client.get(
        created["pollUrl"],
        headers={"X-User-Id": "USER-ALICE"},
    )

    assert denied.json()["code"] != 0
    assert allowed.json()["code"] == 0
    assert "requestedBy" not in allowed.json()["data"]


def test_status_read_refreshes_authoritative_persistence(
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
        options={},
    )

    def refresh(_selected_keys):
        job["status"] = "success"
        job["stage"] = "completed"
        job["progress"] = 100

    monkeypatch.setattr(
        mineru_ocr_routes,
        "load_state",
        refresh,
        raising=False,
    )

    response = client.get(f"/internal/ocr/mineru/tasks/{job['id']}")

    assert response.json()["data"]["status"] == "success"
    assert response.json()["data"]["progress"] == 100


def _metadata_header(metadata: dict[str, object]) -> str:
    return base64.urlsafe_b64encode(
        json.dumps(metadata, ensure_ascii=False).encode("utf-8")
    ).decode("ascii").rstrip("=")


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


@pytest.mark.parametrize("provider", ["local", "mineru"])
def test_unified_upload_session_persists_explicit_ocr_provider(
    provider: str,
    api_repository: InMemoryRepository,
) -> None:
    api_repository.state["projects"] = [
        {
            "id": "PROJECT-OCR-PROVIDER",
            "name": "OCR Provider Test",
            "status": "进行中",
        }
    ]
    response = client.post(
        "/projects/PROJECT-OCR-PROVIDER/documents/upload-session",
        json={
            "files": [
                {
                    "fileName": f"{provider}.pdf",
                    "fileSize": 1024,
                    "fileType": "application/pdf",
                    "ocrOptions": {"provider": provider},
                }
            ]
        },
    )

    assert response.json()["code"] == 0
    version_id = response.json()["data"]["uploadUrls"][0][
        "documentVersionId"
    ]
    version = api_repository.find_one("versions", version_id)
    assert version["ocrOptions"] == {"provider": provider}


def test_unified_upload_session_rejects_invalid_ocr_provider(
    api_repository: InMemoryRepository,
) -> None:
    api_repository.state["projects"] = [
        {
            "id": "PROJECT-OCR-PROVIDER",
            "name": "OCR Provider Test",
            "status": "进行中",
        }
    ]
    version_count = len(api_repository.state["versions"])

    response = client.post(
        "/projects/PROJECT-OCR-PROVIDER/documents/upload-session",
        json={
            "files": [
                {
                    "fileName": "invalid.pdf",
                    "fileSize": 1024,
                    "fileType": "application/pdf",
                    "ocrOptions": {"provider": "unsupported"},
                }
            ]
        },
    )

    assert response.json()["code"] != 0
    assert len(api_repository.state["versions"]) == version_count


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


def test_raw_upload_validates_metadata_before_storing_bytes(
    monkeypatch: pytest.MonkeyPatch,
    api_repository: InMemoryRepository,
) -> None:
    stored: list[bytes] = []
    monkeypatch.setattr(
        mineru_ocr_routes.object_storage,
        "put_bytes",
        lambda _bucket, _name, data, **_kwargs: stored.append(data)
        or "minio://ocr-artifacts/upload.pdf",
    )

    response = client.post(
        "/internal/ocr/mineru/tasks/upload",
        content=b"%PDF",
        headers={
            "X-AICheck-Ocr-Metadata-B64": _metadata_header(
                {
                    "fileName": "uploaded.pdf",
                    "pageRanges": "1-999",
                }
            )
        },
    )

    assert response.json()["code"] != 0
    assert stored == []
