from __future__ import annotations

import httpx
import pytest

from libs.db.repository import repo
from libs.review_orchestrator.execution import create_review_run_from_ai_run, execute_review_run_inline

from scripts.review_orchestration_100_probe import ProbeConfig, ProbeFailure, ReviewOrchestration100Probe


def envelope(data: dict, code: int = 0) -> httpx.Response:
    return httpx.Response(200, json={"code": code, "data": data, "operationId": "op", "serverTime": "2026-06-29T00:00:00Z"})


def scorecard(score: int = 100, ok: bool = True) -> dict:
    return {
        "schemaVersion": "aicheck-review-orchestration-scorecard-v1",
        "targetScore": 100,
        "score": score,
        "ok": ok,
        "sections": [
            {"name": "workflow", "score": 25, "maxScore": 25, "status": "pass", "blockers": []},
            {"name": "graph", "score": 25, "maxScore": 25, "status": "pass", "blockers": []},
            {"name": "evidence", "score": 30, "maxScore": 30, "status": "pass", "blockers": []},
            {"name": "governance", "score": 20, "maxScore": 20, "status": "pass", "blockers": []},
        ],
        "blockers": [] if ok else ["LangGraph Postgres checkpointer is not active"],
    }


def review_run(status: str = "waiting_human_review") -> dict:
    return {
        "reviewRunId": "RRUN-100",
        "status": status,
        "workflowEngine": "temporal",
        "workflowType": "ReviewRunWorkflow",
        "workflowId": "review-run-RRUN-100",
        "graphEngine": "langgraph",
        "graphRunner": "langgraph",
        "graphExecution": {"runner": "langgraph", "checkpointer": "postgres"},
        "modelGateway": "qwen_runtime",
    }


def graph() -> dict:
    nodes = [
        {"nodeKey": "load_context", "status": "succeeded"},
        {"nodeKey": "load_ocr_result", "status": "succeeded"},
        {"nodeKey": "run_rule_engine", "status": "succeeded"},
        {"nodeKey": "retrieve_knowledge", "status": "succeeded"},
        {"nodeKey": "llm_generate_findings", "status": "succeeded"},
        {"nodeKey": "quality_gate", "status": "succeeded"},
    ]
    return {
        "nodes": nodes,
        "edges": [{"source": nodes[index]["nodeKey"], "target": nodes[index + 1]["nodeKey"]} for index in range(len(nodes) - 1)],
    }


def temporal() -> dict:
    return {
        "workflowEngine": "temporal",
        "workflowType": "ReviewRunWorkflow",
        "workflowId": "review-run-RRUN-100",
        "historyPolicy": "ids_hashes_versions_only",
        "payloadCodecRequired": True,
    }


def transport(*, low_score: bool = False, skipped_signal: bool = False) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/auth/login":
            return envelope({"token": "token", "user": {"role": "inspection"}})
        if path.endswith("/inspection/nodes/24/ai-recheck"):
            return envelope({"dispatch": {"mode": "temporal", "status": "started", "reviewRunId": "RRUN-100"}})
        if path == "/api/review-runs/RRUN-100":
            return envelope({"run": review_run()})
        if path == "/api/review-runs/RRUN-100/graph":
            return envelope(graph())
        if path == "/api/review-runs/RRUN-100/timeline":
            return envelope({"events": [{"eventType": "review_run.waiting_human", "status": "waiting_human_review"}]})
        if path == "/api/fde/review-runs/RRUN-100":
            card = scorecard(84, False) if low_score else scorecard()
            return envelope({"run": review_run(), "graph": graph(), "temporal": temporal(), "scorecard": card})
        if path == "/api/review-runs/RRUN-100/human-decision":
            status = "skipped" if skipped_signal else "sent"
            return envelope({"reviewRun": review_run("accepted_by_human"), "temporalSignal": {"status": status}})
        raise AssertionError(f"unexpected request {request.method} {path}")

    return httpx.MockTransport(handler)


def config() -> ProbeConfig:
    return ProbeConfig(
        api_base="http://api",
        project_id="P-2026-HDCP-001",
        node_id=24,
        wait_seconds=1,
        poll_seconds=0.01,
        timeout_seconds=1,
        decision="accept",
    )


def test_review_orchestration_100_probe_passes_for_temporal_langgraph_postgres_scorecard() -> None:
    with httpx.Client(base_url="http://api", transport=transport()) as client:
        report = ReviewOrchestration100Probe(client, config()).run()

    assert report["summary"]["ok"] is True
    assert report["summary"]["dispatchMode"] == "temporal"
    assert report["summary"]["workflowEngine"] == "temporal"
    assert report["summary"]["graphRunner"] == "langgraph"
    assert report["summary"]["checkpointer"] == "postgres"
    assert report["summary"]["scorecardScore"] == 100
    assert report["summary"]["temporalSignalStatus"] == "sent"


def test_review_orchestration_100_probe_rejects_low_scorecard() -> None:
    with httpx.Client(base_url="http://api", transport=transport(low_score=True)) as client:
        with pytest.raises(ProbeFailure, match="did not reach local orchestration 100"):
            ReviewOrchestration100Probe(client, config()).run()


def test_review_orchestration_100_probe_requires_temporal_signal() -> None:
    with httpx.Client(base_url="http://api", transport=transport(skipped_signal=True)) as client:
        with pytest.raises(ProbeFailure, match="not sent to Temporal"):
            ReviewOrchestration100Probe(client, config()).run()


def test_formal_review_completion_converges_node_to_waiting_human(monkeypatch) -> None:
    node = repo.node("P-2026-HDCP-001", 24)
    node["status"] = "业务核验中"
    ai_run = {
        "id": "AIRUN-STATE-SYNC",
        "projectId": "P-2026-HDCP-001",
        "nodeId": 24,
        "subject": "状态收敛测试",
        "model": "review-chat",
        "reviewMode": "formal",
        "advisoryOnly": False,
        "previousNodeStatus": "待审查",
        "auditInputMode": "ocr_llm",
        "suggestion": {"id": "AIS-STATE-SYNC", "confidence": 0, "manualConfirmItems": []},
        "evidenceLinks": [],
        "inputDocumentVersionIds": [],
    }
    repo.state["ai_runs"].insert(0, ai_run)
    run = create_review_run_from_ai_run(ai_run, mode="inline")

    def fake_graph(review_run, context, **kwargs):
        review_run["findingDrafts"] = [
            {"description": "证据不足，需人工确认", "confidence": 0.2}
        ]
        return {"runner": "langgraph", "checkpointer": "postgres", "nodeCount": 6}

    monkeypatch.setattr("libs.review_orchestrator.graph.execute_review_graph", fake_graph)

    result = execute_review_run_inline(run["reviewRunId"])

    assert result["status"] == "waiting_human_review"
    assert repo.node("P-2026-HDCP-001", 24)["status"] == "待人工确认"
    assert run["stateTransition"]["reason"] == "formal_review_waiting_human_review"
    assert ai_run["stateTransition"]["to"] == "待人工确认"


def test_gap_precheck_completion_does_not_change_node_status(monkeypatch) -> None:
    node = repo.node("P-2026-HDCP-001", 24)
    node["status"] = "待审查"
    ai_run = {
        "id": "AIRUN-GAP-STATE",
        "projectId": "P-2026-HDCP-001",
        "nodeId": 24,
        "subject": "缺项预审状态测试",
        "model": "review-chat",
        "reviewMode": "gap_precheck",
        "advisoryOnly": True,
        "previousNodeStatus": "待审查",
        "auditInputMode": "ocr_llm",
        "suggestion": {"id": "AIS-GAP-STATE", "confidence": 0, "manualConfirmItems": []},
        "evidenceLinks": [],
        "inputDocumentVersionIds": [],
    }
    repo.state["ai_runs"].insert(0, ai_run)
    run = create_review_run_from_ai_run(ai_run, mode="inline")

    def fake_graph(review_run, context, **kwargs):
        review_run["findingDrafts"] = [
            {"description": "缺少必传资料", "confidence": 0.4}
        ]
        return {"runner": "langgraph", "checkpointer": "postgres", "nodeCount": 6}

    monkeypatch.setattr("libs.review_orchestrator.graph.execute_review_graph", fake_graph)

    result = execute_review_run_inline(run["reviewRunId"])

    assert result["status"] == "waiting_human_review"
    assert repo.node("P-2026-HDCP-001", 24)["status"] == "待审查"
    assert run["advisoryOnly"] is True
