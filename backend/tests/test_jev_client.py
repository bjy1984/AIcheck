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


def test_compatible_api_endpoint_can_switch_only_to_an_approved_host(monkeypatch):
    monkeypatch.setenv("AICHECK_JEV_API_URL", "https://jev.example.test/v2/systemone")
    with pytest.raises(ValueError, match="jev_endpoint_not_approved"):
        jev_client.jev_endpoint()
    monkeypatch.setenv("AICHECK_JEV_APPROVED_HOSTS", "api.typesafe.ai,jev.example.test")
    assert jev_client.jev_endpoint() == "https://jev.example.test/v2/systemone"
    monkeypatch.setenv("AICHECK_JEV_API_URL", "http://jev.example.test/v2/systemone")
    with pytest.raises(ValueError, match="jev_endpoint_not_approved"):
        jev_client.jev_endpoint()


def test_gateway_splits_large_question_sets_and_combines_typed_answers(monkeypatch):
    monkeypatch.setenv("AICHECK_JEV_ENABLED", "true")
    monkeypatch.setenv("AICHECK_JEV_DATA_EGRESS_APPROVED", "true")
    monkeypatch.setenv("AICHECK_JEV_API_KEY", "new-test-key")
    requests = []

    def fake_open(request, *, timeout):
        payload = json.loads(request.data)
        requests.append((payload, timeout))
        answers = {key: {"type": "choice", "choice": "yes", "confidence": 0.9}
                   for key in payload["questions"]}
        return io.BytesIO(json.dumps({"model": jev_client.MODEL, "answers": answers}).encode())

    monkeypatch.setattr(jev_client.urllib.request, "urlopen", fake_open)
    questions = {f"q{index}": {"type": "choice", "instructions": "审查" * 100,
                              "criteria": {"yes": "有", "no": "无"}} for index in range(60)}
    answers = jev_client.ask_jev("完整原文" * 4_000, questions)

    assert len(requests) > 1
    assert set(answers) == set(questions)
    assert all(len(json.dumps(payload, ensure_ascii=False)) <= jev_client.MAX_REQUEST_CHARS
               for payload, _ in requests)


def test_gateway_rejects_oversized_single_question_before_network(monkeypatch):
    monkeypatch.setenv("AICHECK_JEV_ENABLED", "true")
    monkeypatch.setenv("AICHECK_JEV_DATA_EGRESS_APPROVED", "true")
    monkeypatch.setenv("AICHECK_JEV_API_KEY", "new-test-key")
    monkeypatch.setattr(jev_client.urllib.request, "urlopen", lambda *_args, **_kwargs: 1 / 0)

    with pytest.raises(ValueError, match="jev_request_overlong"):
        jev_client.ask_jev("长" * 39_900, {"q": {"type": "choice", "instructions": "审查",
                                              "criteria": {"yes": "有"}}})


def test_gateway_rejects_boolean_confidence(monkeypatch):
    monkeypatch.setenv("AICHECK_JEV_ENABLED", "true")
    monkeypatch.setenv("AICHECK_JEV_DATA_EGRESS_APPROVED", "true")
    monkeypatch.setenv("AICHECK_JEV_API_KEY", "new-test-key")
    monkeypatch.setattr(jev_client.urllib.request, "urlopen", lambda *_args, **_kwargs: io.BytesIO(
        b'{"model":"jev-1.13.0","answers":{"q":{"type":"choice","choice":"yes","confidence":true}}}'))

    with pytest.raises(ValueError, match="jev_invalid_choice_answer"):
        jev_client.ask_jev("state", {"q": {"type": "choice", "criteria": {"yes": "有"}}})


def test_optional_observer_receives_only_numeric_billing_metadata(monkeypatch):
    monkeypatch.setenv("AICHECK_JEV_ENABLED", "true")
    monkeypatch.setenv("AICHECK_JEV_DATA_EGRESS_APPROVED", "true")
    monkeypatch.setenv("AICHECK_JEV_API_KEY", "new-test-key")
    payload = {"model": jev_client.MODEL, "answers": {"q": {
        "type": "choice", "choice": "yes", "confidence": 0.9}},
        "usage": {"input_tokens": 12, "output_tokens": 3, "cost_usd": 0.001,
                  "secret": "must-not-leak", "total_tokens": True}}
    monkeypatch.setattr(jev_client.urllib.request, "urlopen", lambda *_args, **_kwargs: io.BytesIO(
        json.dumps(payload).encode()))
    observed = []
    jev_client.ask_jev("private OCR", {"q": {"type": "choice", "criteria": {"yes": "有"}}},
                       observe=observed.append)
    assert len(observed) == 1
    assert observed[0]["questionCount"] == 1
    assert observed[0]["status"] == "completed"
    assert observed[0]["usage"] == {"input_tokens": 12, "output_tokens": 3, "cost_usd": 0.001}
    assert "private OCR" not in str(observed)
    assert "new-test-key" not in str(observed)


def test_observer_records_failed_request_latency_without_private_data(monkeypatch):
    monkeypatch.setenv("AICHECK_JEV_ENABLED", "true")
    monkeypatch.setenv("AICHECK_JEV_DATA_EGRESS_APPROVED", "true")
    monkeypatch.setenv("AICHECK_JEV_API_KEY", "new-test-key")

    def fail_request(*_args, **_kwargs):
        raise OSError("private transport diagnostic")

    monkeypatch.setattr(jev_client.urllib.request, "urlopen", fail_request)
    observed = []
    with pytest.raises(OSError):
        jev_client.ask_jev("private OCR", {"q": {"type": "choice", "criteria": {"yes": "有"}}},
                           observe=observed.append)
    assert observed[0]["status"] == "transport_error"
    assert observed[0]["elapsedSeconds"] >= 0
    assert "private OCR" not in str(observed)
    assert "private transport diagnostic" not in str(observed)


def _http_error(code, body):
    import urllib.error
    return urllib.error.HTTPError("https://api.typesafe.ai/v1/systemone", code, "error", {}, io.BytesIO(body))


def _enabled(monkeypatch):
    monkeypatch.setenv("AICHECK_JEV_ENABLED", "true")
    monkeypatch.setenv("AICHECK_JEV_DATA_EGRESS_APPROVED", "true")
    monkeypatch.setenv("AICHECK_JEV_API_KEY", "new-test-key")
    monkeypatch.setattr(jev_client.time, "sleep", lambda _seconds: None)


def test_overloaded_service_is_retried_then_answers(monkeypatch):
    # 2026-09-23 实测：118 次请求里有 1 次 529 system_overloaded，重试即恢复。
    _enabled(monkeypatch)
    calls = []

    def flaky(_request, *, timeout):
        calls.append(timeout)
        if len(calls) < 3:
            raise _http_error(529 if len(calls) == 1 else 429, b'{"detail":{"error_type":"system_overloaded"}}')
        return io.BytesIO(json.dumps({"model": "jev-1.13.0", "answers": {"q": {
            "type": "choice", "choice": "yes", "confidence": 0.9}}}).encode())

    monkeypatch.setattr(jev_client.urllib.request, "urlopen", flaky)
    assert jev_client.ask_jev("state", {"q": {"type": "choice", "criteria": {"yes": "有"}}})["q"]["choice"] == "yes"
    assert len(calls) == 3


def test_token_limit_is_reported_as_overlong_without_retry(monkeypatch):
    # 密集中文约 3.3 万字就超过约 32.8k token，4 万字符上限挡不住。
    _enabled(monkeypatch)
    calls = []

    def refuse(_request, *, timeout):
        calls.append(timeout)
        raise _http_error(400, b'{"detail":{"error_type":"max_tokens_exceeded"}}')

    monkeypatch.setattr(jev_client.urllib.request, "urlopen", refuse)
    with pytest.raises(ValueError, match="jev_request_overlong"):
        jev_client.ask_jev("state", {"q": {"type": "choice", "criteria": {"yes": "有"}}})
    assert len(calls) == 1


def test_persistent_overload_and_other_errors_still_fail(monkeypatch):
    _enabled(monkeypatch)
    calls = []

    def overloaded(_request, *, timeout):
        calls.append(timeout)
        raise _http_error(529, b"{}")

    monkeypatch.setattr(jev_client.urllib.request, "urlopen", overloaded)
    with pytest.raises(OSError):
        jev_client.ask_jev("state", {"q": {"type": "choice", "criteria": {"yes": "有"}}})
    assert len(calls) == 1 + len(jev_client.RETRY_DELAYS_SECONDS)
    monkeypatch.setattr(jev_client.urllib.request, "urlopen",
                        lambda *_a, **_k: (_ for _ in ()).throw(_http_error(401, b"{}")))
    with pytest.raises(OSError):
        jev_client.ask_jev("state", {"q": {"type": "choice", "criteria": {"yes": "有"}}})
