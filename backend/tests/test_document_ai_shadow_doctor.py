from __future__ import annotations

from scripts.document_ai_shadow_doctor import build_document_ai_shadow_doctor


class FakeClient:
    enabled = True

    def public_config(self):
        return {"enabled": True, "baseUrl": "http://127.0.0.1:18300", "apiKeyConfigured": True}

    def health(self):
        return {"status": "ok"}

    def ready(self):
        return {"ready": True}

    def doctor(self):
        return {"status": "ok", "mode": "shadow", "advisoryOnly": True}


def test_shadow_doctor_is_disabled_cleanly_by_default(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_DOCUMENT_AI_MODE", "off")

    report = build_document_ai_shadow_doctor(FakeClient())

    assert report["status"] == "disabled"
    assert report["ok"] is True
    assert report["formalEvidenceReady"] is False


def test_shadow_doctor_requires_all_remote_probes(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_DOCUMENT_AI_MODE", "shadow")

    report = build_document_ai_shadow_doctor(FakeClient())

    assert report["status"] == "ready"
    assert report["ok"] is True
    assert {item["name"] for item in report["checks"]} == {"health", "ready", "doctor"}


def test_shadow_doctor_fails_closed_when_readiness_fails(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_DOCUMENT_AI_MODE", "shadow")

    class NotReadyClient(FakeClient):
        def ready(self):
            return {"ready": False}

    report = build_document_ai_shadow_doctor(NotReadyClient())

    assert report["status"] == "blocked"
    assert "DOCUMENT_AI_READY_FAILED" in report["blockers"]
