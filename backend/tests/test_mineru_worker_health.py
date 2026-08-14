from __future__ import annotations

import asyncio
import os

import pytest

from apps.api import main as api_main
from apps.mineru_worker.queue import write_heartbeat
from scripts.migrate_backend import apply_migrations

pytestmark = pytest.mark.skipif(
    not os.getenv("AICHECK_TEST_POSTGRES_URL"),
    reason="AICHECK_TEST_POSTGRES_URL is required for worker health integration tests",
)


def test_health_reports_fresh_mineru_worker(
    isolated_postgres_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    apply_migrations(isolated_postgres_url)
    monkeypatch.setenv("AICHECK_DATABASE_URL", isolated_postgres_url)
    monkeypatch.setenv("AICHECK_MINERU_EXECUTION_MODE", "postgres")
    write_heartbeat(
        isolated_postgres_url,
        "mineru-test",
        {"activeCount": 2, "lastError": None},
    )

    payload = api_main.mineru_worker_health_status()

    assert payload["required"] is True
    assert payload["ready"] is True
    assert payload["instanceId"] == "mineru-test"
    assert payload["activeCount"] == 2
    assert payload["lastSeenAt"]
    assert payload["lastError"] is None


def test_health_payload_exposes_mineru_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = {
        "required": True,
        "ready": True,
        "instanceId": "mineru-test",
        "activeCount": 0,
        "lastSeenAt": "2026-08-05T00:00:00+00:00",
        "lastError": None,
    }
    monkeypatch.setattr(api_main, "mineru_worker_health_status", lambda: expected)
    monkeypatch.setattr(api_main.repo, "postgres_enabled", False)
    monkeypatch.setattr(api_main.repo, "sqlite_enabled", False)
    monkeypatch.setattr(api_main.repo, "postgres_dsn", None)
    monkeypatch.setattr(api_main.repo, "sync_postgres", None)
    monkeypatch.setattr(api_main, "raw_vault_health_status", lambda: {"ready": True})
    monkeypatch.setattr(api_main, "review_workflow_metrics", lambda: {"reviewWorkerHeartbeat": {"ready": True}})

    async def ready() -> bool:
        return True

    async def temporal() -> dict[str, object]:
        return {"ready": True}

    monkeypatch.setattr(api_main.security_sessions, "ready", ready)
    monkeypatch.setattr(api_main, "temporal_health_status", temporal)

    payload = asyncio.run(api_main.health_payload())

    assert payload["mineruWorker"] == expected
