from __future__ import annotations

from apps.api.main import raw_vault_health_status


def test_raw_vault_readiness_reports_unconfigured_without_dependencies(monkeypatch) -> None:
    monkeypatch.delenv("AICHECK_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("AICHECK_MINIO_ENDPOINT", raising=False)

    status = raw_vault_health_status()

    assert status["configured"] is False
    assert status["ready"] is False
    assert status["pendingCount"] == 0
    assert status["integrityFailureCount"] == 0
