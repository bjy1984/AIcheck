from __future__ import annotations

import zipfile
from io import BytesIO

from fastapi.testclient import TestClient

from apps.api import routes
from apps.api.main import app
from libs.db.repository import repo
from libs.raw_vault import InMemoryRawVaultStore, RawCapture, RawCaptureContext

client = TestClient(app)


def setup_function() -> None:
    repo.reset()


def raw_fixture(monkeypatch):
    store = InMemoryRawVaultStore()
    capture = RawCapture(store=store)
    context = RawCaptureContext(
        tenant_id="tenant-default",
        run_stream_id="RRUN-RAW-1",
        review_run_id="RRUN-RAW-1",
    )
    event = capture.capture_bytes(
        context,
        "llm.response.received",
        b'{ "original": true }\n',
        "application/json",
    )
    events = store.events_for_run("tenant-default", "RRUN-RAW-1")
    monkeypatch.setattr(routes, "_raw_vault_events", lambda _request, _run_id: (events, 0))
    monkeypatch.setattr(
        routes,
        "_raw_vault_payload",
        lambda _request, event_id, _events: store.payload_for(event_id),
    )
    return event


def test_fde_can_list_verify_and_export_raw_vault(monkeypatch) -> None:
    raw_fixture(monkeypatch)

    summary = client.get(
        "/api/fde/review-runs/RRUN-RAW-1/raw-vault",
        headers={"X-Role": "fde"},
    ).json()["data"]
    verified = client.post(
        "/api/fde/review-runs/RRUN-RAW-1/raw-vault/verify",
        headers={"X-Role": "fde"},
    ).json()["data"]
    exported = client.get(
        "/api/fde/review-runs/RRUN-RAW-1/raw-vault/export",
        headers={"X-Role": "fde"},
    )

    assert summary["status"] == "complete"
    assert verified["status"] == "verified"
    assert exported.status_code == 200
    assert "manifest.json" in zipfile.ZipFile(BytesIO(exported.content)).namelist()


def test_non_fde_cannot_read_raw_vault(monkeypatch) -> None:
    raw_fixture(monkeypatch)
    response = client.get(
        "/api/fde/review-runs/RRUN-RAW-1/raw-vault",
        headers={"X-Role": "contractor"},
    )
    assert response.json()["code"] != 0


def test_payload_returns_exact_bytes_and_hash_header(monkeypatch) -> None:
    event = raw_fixture(monkeypatch)
    monkeypatch.setattr(
        routes,
        "postgres_events_for_run",
        lambda _dsn, _tenant, _run_id: (
            routes._raw_vault_events(None, "RRUN-RAW-1")[0],
            0,
        ),
    )
    monkeypatch.setenv("AICHECK_DATABASE_URL", "postgresql://unused")

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def execute(self, *_args):
            return self

        def fetchone(self):
            return ("RRUN-RAW-1",)

    import psycopg

    monkeypatch.setattr(psycopg, "connect", lambda *_args, **_kwargs: FakeConnection())
    response = client.get(
        f"/api/fde/raw-vault/events/{event.id}/payload",
        headers={"X-Role": "fde"},
    )
    assert response.content == b'{ "original": true }\n'
    assert response.headers["X-Raw-Payload-SHA256"] == event.payload_hash
