"""Atomic OCR-only probes must not export deterministic checks or mutate runs."""

import io
import json
from copy import deepcopy

import pytest
from test_export_jev_seven_project_snapshot import _state

from scripts.export_jev_seven_project_snapshot import build_snapshot
from scripts.run_jev_atomic_evaluation import (
    atomic_cases,
    discover_atomic_cases,
    r19_cases,
    run_cases,
)


def _snapshot():
    state = _state()
    state["projects"][0]["businessPackSnapshot"] = {"atomicChecks": [
        {"id": "AC-25", "nodeId": 25, "instruction": "材料性能表证明要求满足吗"}]}
    state["review_runs"] = [{"reviewRunId": "RR-1", "projectId": state["projects"][0]["id"],
                             "nodeId": 25, "reviewMode": "formal", "inputDocumentVersionIds": ["V-0"]}]
    state["rule_check_results"] = [{"reviewRunId": "RR-1", "atomicCheckResults": [
        {"atomicCheckId": "AC-25", "result": "failed"}]}]
    return build_snapshot(state)


def test_dry_run_keeps_rule_result_local_and_does_not_call_jev():
    snapshot = _snapshot()
    original = deepcopy(snapshot)
    cases = atomic_cases(snapshot)
    assert len(cases) == 1
    report = run_cases(cases, send=False, limit=1, max_requests=1,
                       ask=lambda *_args, **_kwargs: 1 / 0)
    assert report["plannedRequestCount"] == 1
    assert report["attemptedRequestCount"] == 0
    assert report["review_runs"][0]["jevSecondOpinions"]["status"] == "ready"
    assert snapshot == original


def test_live_fake_jev_receives_ocr_and_fixed_question_without_rule_result(monkeypatch):
    from scripts import run_jev_atomic_evaluation as evaluation

    monkeypatch.setattr(evaluation, "jev_enabled", lambda: True)
    called = []

    def fake_ask(text, questions, *, observe):
        called.append((text, questions))
        assert "approved OCR 0" in text
        assert all(value not in text for value in ("P-2026-6B15AE", "RR-1", "V-0", "failed"))
        assert "currentResult" not in str(questions)
        assert "rule_check_results" not in str(questions)
        observe({"elapsedSeconds": 0.25, "usage": {"cost_usd": 0.001}})
        return {key: {"type": "choice", "choice": "passed", "confidence": 0.75}
                for key in questions}

    report = run_cases(atomic_cases(_snapshot()), send=True, limit=1, max_requests=1, ask=fake_ask)
    assert len(called) == 1
    assert report["statusCounts"] == {"completed": 1}
    assert report["providerReportedCostUSD"] == 0.001
    assert report["review_runs"][0]["jevSecondOpinions"]["atomic"][0]["choice"] == "passed"
    assert report["rule_check_results"][0]["atomicCheckResults"][0]["result"] == "failed"


def test_atomic_gateway_json_body_does_not_include_local_metadata(monkeypatch):
    from libs.review_orchestrator import jev_client

    for name in ("AICHECK_JEV_ENABLED", "AICHECK_JEV_DATA_EGRESS_APPROVED"):
        monkeypatch.setenv(name, "true")
    monkeypatch.setenv("AICHECK_JEV_API_KEY", "rotated-test-key")
    captured = []

    def fake_open(request, *, timeout):
        payload = json.loads(request.data)
        captured.append(payload)
        return io.BytesIO(json.dumps({"model": jev_client.MODEL, "answers": {"q0": {
            "type": "choice", "choice": "passed", "confidence": 0.75}}}).encode())

    monkeypatch.setattr(jev_client.urllib.request, "urlopen", fake_open)
    report = run_cases(atomic_cases(_snapshot()), send=True, limit=1, max_requests=1)
    assert report["statusCounts"] == {"completed": 1}
    assert captured[0]["state"] == "[第 1 页] approved OCR 0"
    assert all(value not in json.dumps(captured[0]) for value in (
        "P-2026-6B15AE", "RR-1", "V-0", "rotated-test-key", "currentResult"))


def test_request_cap_and_failed_latest_prevent_outbound(monkeypatch):
    from scripts import run_jev_atomic_evaluation as evaluation

    monkeypatch.setattr(evaluation, "jev_enabled", lambda: True)
    cases = atomic_cases(_snapshot())
    cases.append(deepcopy(cases[0]))
    cases[1]["reviewRunId"] = cases[1]["run"]["reviewRunId"] = "RR-2"
    with pytest.raises(ValueError, match="evaluation_request_budget_exceeded"):
        run_cases(cases, send=True, limit=2, max_requests=1,
                  ask=lambda *_args, **_kwargs: 1 / 0)
    snapshot = _snapshot()
    old = snapshot["ocr_parse_results"][0]
    old["finishedAt"] = "2026-09-01T00:00:00Z"
    snapshot["ocr_parse_results"].append({**old, "id": "NEW", "finishedAt": "2026-09-02T00:00:00Z",
                                          "status": "failed"})
    report = run_cases(atomic_cases(snapshot), send=True, limit=1, max_requests=1,
                       ask=lambda *_args, **_kwargs: 1 / 0)
    assert report["statusCounts"] == {"ocr_not_ready": 1}
    assert report["attemptedRequestCount"] == 0


def test_atomic_preflight_count_change_rejects_before_outbound(monkeypatch):
    from scripts import run_jev_atomic_evaluation as evaluation

    monkeypatch.setattr(evaluation, "jev_enabled", lambda: True)
    with pytest.raises(ValueError, match="evaluation_preflight_request_count_changed"):
        run_cases(atomic_cases(_snapshot()), send=True, limit=1, max_requests=2,
                  expected_requests=2, ask=lambda *_args, **_kwargs: 1 / 0)


def test_conflicting_local_rule_results_are_not_used_as_comparison_truth():
    snapshot = _snapshot()
    snapshot["rule_check_results"].append({"reviewRunId": "RR-1", "atomicCheckResults": [
        {"atomicCheckId": "AC-25", "result": "passed"}]})
    cases, counts = discover_atomic_cases(snapshot)
    assert cases == []
    assert counts["contradictory_local_rule_results"] == 1


def test_r19_is_eight_separate_ocr_only_semantic_comparisons(monkeypatch):
    from libs.review_orchestrator.r19_agent import R19_REVIEW_QUESTIONS
    from scripts import run_jev_atomic_evaluation as evaluation

    monkeypatch.setattr(evaluation, "jev_enabled", lambda: True)
    state = _state()
    state["review_runs"] = [{"reviewRunId": "RR-R19", "projectId": state["projects"][0]["id"],
                             "nodeId": 19, "reviewMode": "formal", "inputDocumentVersionIds": ["V-0"]}]
    state["rule_check_results"] = [{"reviewRunId": "RR-R19", "atomicCheckResults": [
        {"atomicCheckId": item["questionId"], "result": "evidence_insufficient"}
        for item in R19_REVIEW_QUESTIONS]}]
    cases = r19_cases(build_snapshot(state))
    assert len(cases) == 1 and len(cases[0]["questions"]) == 16

    def fake_ask(text, questions, *, observe):
        assert "approved OCR 0" in text and "RR-R19" not in text
        observe({"elapsedSeconds": 0.2, "usage": {}})
        return {key: {"type": "choice", "choice": "applicable" if key.startswith("a") else "passed",
                      "confidence": 0.8} for key in questions}

    report = run_cases(cases, send=True, limit=1, max_requests=1, ask=fake_ask)
    opinion = report["review_runs"][0]["jevSecondOpinions"]
    assert opinion["comparisonSource"] == "r19_semantic_review"
    assert len(opinion["atomic"]) == 8
    assert all(row["choice"] == "passed" for row in opinion["atomic"])
