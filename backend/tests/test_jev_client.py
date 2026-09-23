from __future__ import annotations

import io
import json

import pytest

from libs.review_orchestrator import jev_client


def test_old_key_or_single_flag_cannot_enable_outbound_request(monkeypatch):
    monkeypatch.setenv("JEV_KEY", "old-exposed-key")
    monkeypatch.setenv("AICHECK_JEV_ENABLED", "true")
    monkeypatch.delenv("AICHECK_JEV_DATA_EGRESS_APPROVED", raising=False)
    monkeypatch.delenv("AICHECK_JEV_API_KEY", raising=False)
    monkeypatch.setattr(jev_client.urllib.request, "urlopen", lambda *_args, **_kwargs: 1 / 0)
    assert not jev_client.jev_enabled()
    with pytest.raises(RuntimeError, match="jev_data_egress_not_enabled"):
        jev_client.ask_jev("state", {"q": {"type": "choice", "criteria": {"yes": "yes"}}})


def test_pinned_model_and_complete_typed_response(monkeypatch):
    monkeypatch.setenv("AICHECK_JEV_ENABLED", "true")
    monkeypatch.setenv("AICHECK_JEV_DATA_EGRESS_APPROVED", "true")
    monkeypatch.setenv("AICHECK_JEV_API_KEY", "new-test-key")
    assert not jev_client.jev_stage_enabled("TABLE_CLASSIFICATION")
    monkeypatch.setenv("AICHECK_JEV_TABLE_CLASSIFICATION_ENABLED", "true")
    assert jev_client.jev_stage_enabled("TABLE_CLASSIFICATION")
    assert not jev_client.jev_stage_enabled("CLAIM_SHADOW")
    requests = []

    def fake_open(request, *, timeout):
        requests.append((request, timeout))
        return io.BytesIO(json.dumps({"model": "jev-1.13.0", "answers": {"q": {
            "type": "choice", "choice": "yes", "confidence": 0.94}}}).encode())

    monkeypatch.setattr(jev_client.urllib.request, "urlopen", fake_open)
    question = {"q": {"type": "choice", "criteria": {"yes": "yes", "no": "no"}}}
    assert jev_client.ask_jev("state", question)["q"]["choice"] == "yes"
    assert json.loads(requests[0][0].data)["model"] == "jev-1.13.0"
    assert requests[0][0].full_url == "https://api.typesafe.ai/v1/systemone"


def test_wrong_model_response_is_rejected(monkeypatch):
    monkeypatch.setenv("AICHECK_JEV_ENABLED", "true")
    monkeypatch.setenv("AICHECK_JEV_DATA_EGRESS_APPROVED", "true")
    monkeypatch.setenv("AICHECK_JEV_API_KEY", "new-test-key")
    monkeypatch.setattr(jev_client.urllib.request, "urlopen", lambda *_args, **_kwargs: io.BytesIO(
        b'{"model":"jev-latest","answers":{"q":{"type":"choice","choice":"yes","confidence":1}}}'))
    with pytest.raises(ValueError, match="jev_unexpected_model_version"):
        jev_client.ask_jev("state", {"q": {"type": "choice", "criteria": {"yes": "yes"}}})
