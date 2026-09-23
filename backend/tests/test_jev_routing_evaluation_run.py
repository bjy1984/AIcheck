"""The live evaluation runner must enforce a budget and never export OCR text."""

import io
import json
import stat
from copy import deepcopy

import pytest

from libs.review_orchestrator import jev_client
from scripts import run_jev_routing_evaluation as runner


def _case(version="V"):
    return {"state": {"documents": [{"id": version, "projectId": "P"}],
                      "versions": [{"id": version, "documentId": version}],
                      "ocr_parse_results": [{"documentVersionId": version,
                                             "fragments": [{"pageNo": 1, "text": "PRIVATE-OCR-CONTENT"}]}]},
            "scope": {"projectId": "P", "nodeId": "待归属", "inputDocumentVersionIds": [version]},
            "projectId": "P", "documentId": version, "documentVersionId": version,
            "questions": {"node_25": {"type": "choice", "instructions": "材料归属",
                                       "criteria": {"yes": "属于", "no": "不属于", "uncertain": "不确定"}}},
            "nodeIds": {"node_25": 25}, "overlongNodeIds": [],
            "existingNodeIds": [], "humanRejectedNodeIds": []}


def test_dry_run_counts_requests_without_calling_jev_or_exporting_ocr():
    report = runner.run_cases([_case()], send=False, limit=1, max_requests=1,
                              ask=lambda *_args, **_kwargs: 1 / 0)
    assert report["plannedRequestCount"] == 1
    assert report["attemptedRequestCount"] == 0
    assert report["costStatus"] == "not_run"
    assert report["shadows"][0]["status"] == "ready"
    assert "PRIVATE-OCR-CONTENT" not in json.dumps(report)


def test_paid_request_budget_rejects_whole_batch_before_first_call(monkeypatch):
    monkeypatch.setattr(runner, "jev_enabled", lambda: True)
    called = []
    with pytest.raises(ValueError, match="evaluation_request_budget_exceeded"):
        runner.run_cases([_case("V1"), _case("V2")], send=True, limit=2, max_requests=1,
                         ask=lambda *_args, **_kwargs: called.append(True))
    assert called == []


def test_changed_preflight_count_rejects_before_outbound(monkeypatch):
    monkeypatch.setattr(runner, "jev_enabled", lambda: True)
    called = []
    with pytest.raises(ValueError, match="evaluation_preflight_request_count_changed"):
        runner.run_cases([_case()], send=True, limit=1, max_requests=2,
                         expected_requests=2, ask=lambda *_args, **_kwargs: called.append(True))
    assert called == []


def test_live_shadow_is_metadata_only_and_cost_is_reported_only_when_provider_supplies_it(monkeypatch):
    monkeypatch.setattr(runner, "jev_enabled", lambda: True)

    def recorded_answer(state, questions, *, observe):
        assert "PRIVATE-OCR-CONTENT" in state
        assert all(value not in state for value in ("工程：", "节点：", "文件：", "版本：", "已核实", "EVAL-V"))
        observe({"elapsedSeconds": 0.42, "usage": {"cost_usd": 0.002}})
        return {key: {"type": "choice", "choice": "yes", "confidence": 0.93}
                for key in questions}

    report = runner.run_cases([_case()], send=True, limit=1, max_requests=1, ask=recorded_answer)
    assert report["attemptedRequestCount"] == 1
    assert report["providerReportedCostUSD"] == 0.002
    assert report["costStatus"] == "provider_reported"
    assert report["shadows"][0]["status"] == "completed"
    assert report["shadows"][0]["suggestedNodeIds"] == [25]
    assert "PRIVATE-OCR-CONTENT" not in json.dumps(report)


def test_latest_failed_parse_is_skipped_and_private_output_uses_0600(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "jev_enabled", lambda: True)
    case = _case()
    old = case["state"]["ocr_parse_results"][0]
    old.update(id="OLD", finishedAt="2026-09-01T00:00:00Z")
    latest = deepcopy(old)
    latest.update(id="NEW", finishedAt="2026-09-02T00:00:00Z", status="failed")
    case["state"]["ocr_parse_results"].append(latest)
    report = runner.run_cases([case], send=True, limit=1, max_requests=1,
                              ask=lambda *_args, **_kwargs: 1 / 0)
    assert report["shadows"][0]["status"] == "ocr_not_ready"
    assert report["attemptedRequestCount"] == 0
    path = tmp_path / "shadows.jsonl"
    runner._private_write(path, json.dumps(report["shadows"][0]))
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    with pytest.raises(FileExistsError):
        runner._private_write(path, "overwrite")


def test_failed_live_request_counts_attempt_and_elapsed_time(monkeypatch):
    monkeypatch.setattr(runner, "jev_enabled", lambda: True)

    def failed_answer(_state, _questions, *, observe):
        observe({"elapsedSeconds": 1.25, "usage": {}, "status": "transport_error"})
        raise OSError("private transport diagnostic")

    report = runner.run_cases([_case()], send=True, limit=1, max_requests=1, ask=failed_answer)
    assert report["attemptedRequestCount"] == 1
    assert report["elapsedSeconds"] == 1.25
    assert report["statusCounts"] == {"unavailable": 1}
    assert report["costStatus"] == "not_reported_by_api"
    assert "private transport diagnostic" not in json.dumps(report)


def test_gateway_request_body_contains_ocr_and_fixed_question_only(monkeypatch):
    for name in ("AICHECK_JEV_ENABLED", "AICHECK_JEV_DATA_EGRESS_APPROVED"):
        monkeypatch.setenv(name, "true")
    monkeypatch.setenv("AICHECK_JEV_API_KEY", "rotated-test-key")
    case = _case("V-SECRET")
    case["projectId"] = case["scope"]["projectId"] = "P-SECRET"
    case["state"]["documents"][0].update(projectId="P-SECRET", fileName="PRIVATE-FILENAME.pdf")
    captured = []

    def fake_open(request, *, timeout):
        captured.append(json.loads(request.data))
        return io.BytesIO(json.dumps({"model": jev_client.MODEL, "answers": {"node_25": {
            "type": "choice", "choice": "yes", "confidence": 0.91}}}).encode())

    monkeypatch.setattr(jev_client.urllib.request, "urlopen", fake_open)
    report = runner.run_cases([case], send=True, limit=1, max_requests=1)
    assert report["statusCounts"] == {"completed": 1}
    assert captured[0]["state"] == "[第 1 页] PRIVATE-OCR-CONTENT"
    assert set(captured[0]) == {"state", "model", "questions"}
    assert all(value not in json.dumps(captured[0]) for value in (
        "P-SECRET", "V-SECRET", "PRIVATE-FILENAME", "已核实", "rotated-test-key"))
