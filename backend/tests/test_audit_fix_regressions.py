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


# ------------------------------------------------------------ issue #5 D-1


def test_fact_correction_lifecycle_with_audit() -> None:
    saved = assert_ok(
        client.post(
            "/projects/P-2026-HDCP-001/inspection/nodes/24/fact-corrections",
            json={
                "factPath": "welderCertificate.certificateNo",
                "originalValue": "T2026-O01",
                "correctedValue": "TS2026-001",
                "reason": "OCR 把 S 识别成 5。",
            },
        )
    )
    correction = saved["correction"]
    assert saved["auditLogId"]
    assert correction["status"] == "active"
    assert correction["correctedBy"]
    assert repo.find_one("audit_logs", saved["auditLogId"]) is not None

    # 同 factPath 再次修正 → 旧记录被 supersede
    second = assert_ok(
        client.post(
            "/projects/P-2026-HDCP-001/inspection/nodes/24/fact-corrections",
            json={"factPath": "welderCertificate.certificateNo", "correctedValue": "TS2026-002"},
        )
    )
    assert correction["id"] in second["correction"]["supersedes"]
    listed = assert_ok(client.get("/projects/P-2026-HDCP-001/inspection/nodes/24/fact-corrections?status=active"))
    assert [item["id"] for item in listed] == [second["correction"]["id"]]

    # 撤销
    revoked = assert_ok(
        client.post(
            f"/projects/P-2026-HDCP-001/inspection/nodes/24/fact-corrections/{second['correction']['id']}/revoke",
            json={},
        )
    )
    assert revoked["correction"]["status"] == "revoked"


def test_fact_correction_rejects_invalid_path() -> None:
    response = client.post(
        "/projects/P-2026-HDCP-001/inspection/nodes/24/fact-corrections",
        json={"factPath": "a..b; drop", "correctedValue": "x"},
    )
    assert response.json()["code"] != 0


def test_fact_corrections_overlay_only_target_node() -> None:
    from libs.review_orchestrator.execution import apply_node_fact_corrections

    state = {
        "fact_corrections": [
            {
                "id": "FCOR-1",
                "projectId": "P-1",
                "nodeId": 24,
                "factPath": "welderCertificate.certificateNo",
                "correctedValue": "TS2026-001",
                "status": "active",
                "createdAt": "2026-08-07T00:00:00Z",
            },
            {
                "id": "FCOR-2",
                "projectId": "P-1",
                "nodeId": 25,
                "factPath": "weldingProcedure.wpsNo",
                "correctedValue": "WPS-9",
                "status": "active",
                "createdAt": "2026-08-07T00:00:00Z",
            },
            {
                "id": "FCOR-3",
                "projectId": "P-1",
                "nodeId": 24,
                "factPath": "welderCertificate.validUntil",
                "correctedValue": "2027-01-01",
                "status": "revoked",
                "createdAt": "2026-08-07T00:00:00Z",
            },
        ]
    }
    facts = {"welderCertificate": {"certificateNo": "T2026-O01"}}
    applied = apply_node_fact_corrections(state, "P-1", 24, facts)

    # 仅本节点、仅 active 的修正生效（节点独立原则）
    assert facts["welderCertificate"]["certificateNo"] == "TS2026-001"
    assert "validUntil" not in facts["welderCertificate"]
    assert "weldingProcedure" not in facts
    assert [item["correctionId"] for item in applied] == ["FCOR-1"]
