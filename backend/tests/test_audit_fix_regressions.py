"""2026-08-07 深度审计修复的回归测试。

覆盖 GitHub issues：
- #3  字段缺失 → evidence_insufficient（不再误判 failed）
- #4  human_review_required 在聚合层保留；人工结论支持「证据不足」
- #5  save_review_opinion 留痕 + AI 结论关联
- #6  聚合器优先级：grounding 一票否决；执行故障不掩盖 failed、不伪装业务结论
- #13 「不适用」结论不再把节点置为「需补正」
- #14 suggestion.result 携带确定性判定
"""
from __future__ import annotations

from fastapi.testclient import TestClient

import libs.review_orchestrator  # noqa: F401  # 先初始化，规避 review_tools 循环导入
from apps.api.main import app
from libs.db.repository import repo
from libs.review_orchestrator.execution import SUGGESTION_RESULT_LABELS
from libs.review_tools import dispatch_business_tool
from libs.review_tools.executor import aggregate_atomic_results, aggregate_tool_results

client = TestClient(app)


def setup_function() -> None:
    repo.reset()
    repo.postgres_enabled = False
    repo.sync_postgres = None
    repo.postgres_dsn = None
    repo.sqlite_enabled = False
    repo.sqlite_path = None


def assert_ok(response):
    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] == 0
    return payload["data"]


# ---------------------------------------------------------------- issue #3


def test_missing_fact_fields_are_evidence_insufficient_not_failed() -> None:
    empty = dispatch_business_tool("check_required", {"requiredFields": ["a.b"], "facts": {}})
    partial = dispatch_business_tool(
        "check_required", {"requiredFields": ["a.b", "a.c"], "facts": {"a": {"b": "X"}}}
    )
    assert empty["result"] == "evidence_insufficient"
    assert partial["result"] == "evidence_insufficient"


def test_present_but_noncompliant_value_is_still_failed() -> None:
    scope = dispatch_business_tool(
        "check_scope_coverage",
        {"grantedScopes": ["GC3"], "requiredScopes": ["GC1"], "coverageMap": {"GC1": ["GC1"]}},
    )
    assert scope["result"] == "failed"


def test_missing_document_body_is_still_failed() -> None:
    documents = dispatch_business_tool(
        "check_document_set_completeness",
        {
            "requiredDocumentTypes": ["drawing_index", "stress_calculation"],
            "uploadedDocumentTypes": ["drawing_index"],
            "parseableDocumentTypes": ["drawing_index"],
        },
    )
    assert documents["result"] == "failed"


# ------------------------------------------------------------ issues #4 #6


def test_aggregator_preserves_human_review_required() -> None:
    assert aggregate_tool_results([{"toolName": "a", "result": "human_review_required"}]) == "human_review_required"
    assert aggregate_atomic_results([{"result": "human_review_required"}]) == "human_review_required"


def test_execution_error_does_not_mask_confirmed_failure() -> None:
    outputs = [
        {"toolName": "a", "result": "failed"},
        {"toolName": "b", "status": "failed"},
    ]
    assert aggregate_tool_results(outputs) == "failed"


def test_execution_error_alone_is_not_a_business_conclusion() -> None:
    outputs = [
        {"toolName": "a", "result": "passed"},
        {"toolName": "b", "status": "error"},
    ]
    assert aggregate_tool_results(outputs) == "execution_error"
    assert aggregate_atomic_results([{"result": "execution_error"}, {"result": "passed"}]) == "execution_error"


def test_grounding_failure_vetoes_failed_conclusion() -> None:
    outputs = [
        {"toolName": "validate_evidence_grounding", "result": "evidence_insufficient"},
        {"toolName": "check_required", "result": "failed"},
    ]
    assert aggregate_tool_results(outputs) == "evidence_insufficient"


def test_failed_takes_priority_over_human_review_and_insufficient() -> None:
    outputs = [
        {"toolName": "a", "result": "failed"},
        {"toolName": "b", "result": "human_review_required"},
        {"toolName": "c", "result": "evidence_insufficient"},
    ]
    assert aggregate_tool_results(outputs) == "failed"


# ------------------------------------------------------- issues #5 #13 #14


def test_not_applicable_opinion_does_not_demand_rectification() -> None:
    saved = assert_ok(
        client.post(
            "/projects/P-2026-HDCP-001/inspection/nodes/24/review-opinions",
            json={"result": "不适用", "opinion": "本节点对该项目不适用。", "evidenceLinkIds": []},
        )
    )
    assert saved["nextStatus"] == "不适用"
    assert repo.node("P-2026-HDCP-001", 24)["status"] == "不适用"


def test_insufficient_evidence_opinion_keeps_node_pending() -> None:
    saved = assert_ok(
        client.post(
            "/projects/P-2026-HDCP-001/inspection/nodes/24/review-opinions",
            json={"result": "证据不足", "opinion": "资料不足，待补件后复核。", "evidenceLinkIds": []},
        )
    )
    assert saved["nextStatus"] == "待审查"


def test_review_opinion_records_audit_and_ai_linkage() -> None:
    repo.state["ai_runs"].insert(
        0,
        {
            "id": "AI-TEST-1",
            "projectId": "P-2026-HDCP-001",
            "nodeId": 24,
            "suggestion": {"id": "SUG-1", "result": "需补正"},
        },
    )
    saved = assert_ok(
        client.post(
            "/projects/P-2026-HDCP-001/inspection/nodes/24/review-opinions",
            json={"result": "不适用", "opinion": "人工推翻 AI 建议。", "evidenceLinkIds": []},
        )
    )
    opinion = saved["opinion"]
    assert saved["auditLogId"]
    assert opinion["aiRunId"] == "AI-TEST-1"
    assert opinion["aiSuggestedResult"] == "需补正"
    assert opinion["overriddenFromAi"] is True
    audit = repo.find_one("audit_logs", saved["auditLogId"])
    assert audit is not None


def test_suggestion_result_labels_cover_all_aggregate_values() -> None:
    for value in ("passed", "failed", "evidence_insufficient", "not_applicable", "human_review_required", "execution_error"):
        assert value in SUGGESTION_RESULT_LABELS
