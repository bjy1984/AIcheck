from __future__ import annotations

import json
import threading
import time

import pytest
from fastapi.testclient import TestClient

from apps.api import routes as routes_module
from apps.api.main import app
from libs.db.repository import repo


@pytest.fixture(autouse=True)
def _inline_conversation_execution(monkeypatch):
    """既有用例沿用同步（inline）契约；background 异步执行在专门用例中覆盖。"""
    monkeypatch.setenv("AICHECK_REVIEW_CONVERSATION_EXECUTION_MODE", "inline")


client = TestClient(app)
HEADERS = {"X-Role": "inspection", "X-User-Id": "USER-INSPECTION-001"}
PROJECT_ID = "P-2026-HDCP-001"
NODE_ID = 1


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


def create_session() -> dict:
    payload = assert_ok(
        client.post(
            f"/api/projects/{PROJECT_ID}/inspection/nodes/{NODE_ID}/review-sessions",
            headers={**HEADERS, "Idempotency-Key": "review-b-session-test"},
            json={"currentTask": "核对设计单位许可证"},
        )
    )
    return payload["session"]


def call_review_agent_tool(
    tool_name: str,
    arguments: dict,
    *,
    evidence_links: list[dict],
) -> dict:
    project = repo.require_project(PROJECT_ID) or {}
    return routes_module.review_conversation_agent_tool_output(
        tool_name,
        arguments,
        session={"projectId": PROJECT_ID, "nodeId": NODE_ID},
        project=project,
        node=repo.node(PROJECT_ID, NODE_ID) or {"nodeId": NODE_ID},
        basis={},
        basis_items=[],
        readiness={},
        evidence_links=evidence_links,
        review_run=None,
    )


def test_review_b_workspace_creates_and_recovers_node_session() -> None:
    before = assert_ok(
        client.get(
            f"/api/projects/{PROJECT_ID}/inspection/nodes/{NODE_ID}/review-workspace",
            headers=HEADERS,
        )
    )
    assert before["schemaVersion"] == "ReviewWorkspaceProjection@1.0.0"
    assert before["node"]["nodeId"] == NODE_ID
    assert before["session"] is None
    assert before["permissions"]["canManageEvidence"] is True

    session = create_session()
    assert session["projectId"] == PROJECT_ID
    assert session["nodeId"] == NODE_ID
    assert session["currentTask"] == "核对设计单位许可证"
    assert session["etag"].startswith('W/"review-session-')

    active = assert_ok(
        client.get(
            f"/api/projects/{PROJECT_ID}/inspection/nodes/{NODE_ID}/review-sessions/active",
            headers=HEADERS,
        )
    )
    after = assert_ok(
        client.get(
            f"/api/projects/{PROJECT_ID}/inspection/nodes/{NODE_ID}/review-workspace",
            headers=HEADERS,
        )
    )
    assert active["session"]["id"] == session["id"]
    assert after["session"]["id"] == session["id"]
    assert after["contextSummary"]["currentTask"] == "核对设计单位许可证"


def test_review_b_routes_and_api_are_limited_to_inspection_role() -> None:
    routes = assert_ok(client.get("/api/auth/routes?role=inspection"))
    assert "/ai-review-b" in [route["path"] for route in routes]

    forbidden = client.get(
        f"/api/projects/{PROJECT_ID}/inspection/nodes/{NODE_ID}/review-workspace",
        headers={"X-Role": "contractor"},
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["code"] != 0


def test_review_b_messages_return_structured_basis_and_pollable_events() -> None:
    session = create_session()
    response = assert_ok(
        client.post(
            f"/api/review-sessions/{session['id']}/messages",
            headers={
                **HEADERS,
                "Idempotency-Key": "review-b-message-test",
                "If-Match": session["etag"],
            },
            json={"content": "/标准条款"},
        )
    )
    assert response["status"] == "completed"
    assert response["userMessage"]["role"] == "user"
    assert response["assistantMessage"]["role"] == "assistant"
    assert any(
        block["type"] == "basis_card"
        for block in response["assistantMessage"]["contentBlocks"]
    )
    basis_block = next(
        block
        for block in response["assistantMessage"]["contentBlocks"]
        if block["type"] == "basis_card"
    )
    assert basis_block["items"][0]["sourceLocatorId"].startswith("LOC-")
    assert basis_block["items"][0]["standardCode"] == "TSG D7006—2020"
    assert "压力管道监督检验规则" in basis_block["items"][0]["standardName"]
    assert basis_block["items"][0]["previewUrl"].startswith("/api/knowledge/files/")
    assert basis_block["items"][0]["sourcePage"] > 0

    messages = assert_ok(
        client.get(f"/api/review-sessions/{session['id']}/messages", headers=HEADERS)
    )
    events = assert_ok(
        client.get(f"/api/review-sessions/{session['id']}/events", headers=HEADERS)
    )
    assert [item["sequence"] for item in messages["messages"]] == [1, 2]
    assert events["schema"] == "review-event/v1"
    assert events["transport"] == "polling"
    assert events["lastSequence"] >= 3
    assert all(item["payloadHash"].startswith("sha256:") for item in events["events"])
    assert [item["eventType"] for item in events["events"][:3]] == [
        "session.created",
        "user.message.created",
        "agent.message.completed",
    ]

    stale_update = client.post(
        f"/api/review-sessions/{session['id']}/actions/set_current_task",
        headers={
            **HEADERS,
            "Idempotency-Key": "review-b-stale-session-test",
            "If-Match": session["etag"],
        },
        json={"currentTask": "并发写入不应覆盖新上下文"},
    )
    assert stale_update.status_code == 409


def test_review_b_search_evidence_separates_located_candidates_and_advisory_files(
    monkeypatch,
) -> None:
    point = next(
        item
        for item in repo.state["admin_config"]["materialReviewPoints"]
        if int(item.get("nodeId") or 0) == NODE_ID
    )
    common = {
        "projectId": PROJECT_ID,
        "nodeId": NODE_ID,
        "reviewPointId": point["id"],
        "documentId": "DOC-REVIEW-B-EVIDENCE",
        "documentVersionId": "DV-REVIEW-B-EVIDENCE",
        "fileName": "设计单位许可证.pdf",
        "manualStatus": "pending",
        "manualStatusLabel": "待确认",
        "supportStatus": "命中",
        "confidence": 0.92,
        "source": "material_targeting",
    }
    repo.state["node_evidence_links"].extend(
        [
            {
                **common,
                "id": "NEL-REVIEW-B-FORMAL",
                "pageNo": 2,
                "bbox": [10, 20, 260, 60],
                "fieldName": "许可范围",
                "quotedText": "许可范围：压力管道设计 GC2",
                "formalEvidenceEligible": True,
                "evidenceTier": "formal",
            },
            {
                **common,
                "id": "NEL-REVIEW-B-ADVISORY",
                "pageNo": 1,
                "bbox": None,
                "fieldName": "资料类型",
                "quotedText": "设计单位许可证",
                "formalEvidenceEligible": False,
                "evidenceTier": "advisory",
            },
            {
                **common,
                "id": "NEL-REVIEW-B-HIDDEN",
                "tenantId": "TENANT-NOT-VISIBLE",
                "documentVersionId": "DV-REVIEW-B-HIDDEN",
                "pageNo": 3,
                "bbox": [10, 20, 260, 60],
                "quotedText": "不可见租户证据",
                "formalEvidenceEligible": True,
                "evidenceTier": "formal",
            },
        ]
    )
    session = create_session()
    live_call = {}

    def fake_search_project_evidence(repository, **kwargs):
        live_call.update(kwargs)
        return {
            "formalCandidates": [
                {
                    **common,
                    "id": "EVC-LIVE-FORMAL",
                    "pageNo": 2,
                    "bbox": [10, 20, 260, 60],
                    "quotedText": "许可证有效期至 2028-12-31",
                    "formalEvidenceEligible": True,
                    "evidenceTier": "formal",
                    "bm25Rank": 1,
                    "denseRank": 2,
                    "fusedScore": 0.027,
                },
                {
                    **common,
                    "id": "EVC-LIVE-OUT-OF-SCOPE",
                    "documentVersionId": "DV-REVIEW-B-OUT-OF-SCOPE",
                    "pageNo": 4,
                    "bbox": [10, 20, 260, 60],
                    "quotedText": "服务误返的范围外候选",
                    "formalEvidenceEligible": True,
                    "evidenceTier": "formal",
                    "bm25Rank": 2,
                    "denseRank": None,
                    "fusedScore": 0.016,
                },
            ],
            "advisoryCandidates": [
                {
                    **common,
                    "id": "EVC-LIVE-ADVISORY",
                    "pageNo": 1,
                    "bbox": None,
                    "quotedText": "设计单位许可证",
                    "formalEvidenceEligible": False,
                    "evidenceTier": "advisory",
                    "rejectionReasons": ["missing_bbox"],
                    "bm25Rank": 2,
                    "denseRank": 1,
                    "fusedScore": 0.026,
                }
            ],
            "allCandidates": [],
            "trace": {"retrievalTraceId": "RTR-LIVE-1"},
            "degraded": False,
            "fallbackReason": None,
        }

    monkeypatch.setattr(
        routes_module,
        "search_project_evidence",
        fake_search_project_evidence,
        raising=False,
    )

    response = assert_ok(
        client.post(
            f"/api/review-sessions/{session['id']}/messages",
            headers={
                **HEADERS,
                "Idempotency-Key": "review-b-evidence-tier-test",
                "If-Match": session["etag"],
            },
            json={"content": "/检索证据 许可证有效期"},
        )
    )
    cards = [
        block
        for block in response["assistantMessage"]["contentBlocks"]
        if block["type"] == "evidence_card"
    ]

    assert [card["title"] for card in cards] == [
        "可定位证据候选",
        "可能相关文件（缺少事实定位）",
    ]
    assert live_call["query"] == "许可证有效期"
    assert live_call["document_version_ids"] == ["DV-REVIEW-B-EVIDENCE"]
    assert cards[0]["retrievalTraceId"] == "RTR-LIVE-1"
    assert cards[0]["fallbackUsed"] is False
    assert cards[0]["evidenceLinkIds"] == []
    assert [item["id"] for item in cards[0]["items"]] == ["EVC-LIVE-FORMAL"]
    assert cards[0]["items"][0]["selectable"] is False
    assert cards[0]["items"][0]["fusedScore"] > 0
    assert cards[1]["advisory"] is True
    assert cards[1]["retrievalTraceId"] == "RTR-LIVE-1"
    assert cards[1]["evidenceLinkIds"] == []
    assert [item["id"] for item in cards[1]["items"]] == ["EVC-LIVE-ADVISORY"]
    assert cards[1]["items"][0]["selectable"] is False
    assert response["assistantMessage"]["execution"]["modelCalled"] is False


def test_review_b_search_evidence_falls_back_to_precomputed_cards(monkeypatch) -> None:
    point = next(
        item
        for item in repo.state["admin_config"]["materialReviewPoints"]
        if int(item.get("nodeId") or 0) == NODE_ID
    )
    common = {
        "projectId": PROJECT_ID,
        "nodeId": NODE_ID,
        "reviewPointId": point["id"],
        "documentId": "DOC-REVIEW-B-FALLBACK",
        "documentVersionId": "DV-REVIEW-B-FALLBACK",
        "fileName": "设计单位许可证.pdf",
        "manualStatus": "pending",
        "manualStatusLabel": "待确认",
        "supportStatus": "命中",
        "confidence": 0.92,
        "source": "material_targeting",
    }
    repo.state["node_evidence_links"].extend(
        [
            {
                **common,
                "id": "NEL-REVIEW-B-FALLBACK-FORMAL",
                "pageNo": 2,
                "bbox": [10, 20, 260, 60],
                "quotedText": "许可范围：压力管道设计 GC2",
                "formalEvidenceEligible": True,
                "evidenceTier": "formal",
            },
            {
                **common,
                "id": "NEL-REVIEW-B-FALLBACK-ADVISORY",
                "pageNo": 1,
                "bbox": None,
                "quotedText": "设计单位许可证",
                "formalEvidenceEligible": False,
                "evidenceTier": "advisory",
            },
        ]
    )

    def broken_search_project_evidence(repository, **kwargs):
        raise RuntimeError("retrieval unavailable")

    monkeypatch.setattr(
        routes_module,
        "search_project_evidence",
        broken_search_project_evidence,
    )
    session = create_session()
    response = assert_ok(
        client.post(
            f"/api/review-sessions/{session['id']}/messages",
            headers={
                **HEADERS,
                "Idempotency-Key": "review-b-evidence-fallback-test",
                "If-Match": session["etag"],
            },
            json={"content": "/检索证据 许可证有效期"},
        )
    )
    cards = [
        block
        for block in response["assistantMessage"]["contentBlocks"]
        if block["type"] == "evidence_card"
    ]

    assert [item["id"] for item in cards[0]["items"]] == [
        "NEL-REVIEW-B-FALLBACK-FORMAL"
    ]
    assert [item["id"] for item in cards[1]["items"]] == [
        "NEL-REVIEW-B-FALLBACK-ADVISORY"
    ]
    assert cards[0]["evidenceLinkIds"] == ["NEL-REVIEW-B-FALLBACK-FORMAL"]
    assert cards[1]["evidenceLinkIds"] == ["NEL-REVIEW-B-FALLBACK-ADVISORY"]
    assert "selectable" not in cards[0]["items"][0]
    assert "selectable" not in cards[1]["items"][0]
    assert all(card["fallbackUsed"] is True for card in cards)
    assert all(card["retrievalTraceId"] is None for card in cards)
    assert all(card["fallbackReason"] == "live_retrieval_exception" for card in cards)


def test_review_b_search_evidence_without_tail_builds_node_query(monkeypatch) -> None:
    point = next(
        item
        for item in repo.state["admin_config"]["materialReviewPoints"]
        if int(item.get("nodeId") or 0) == NODE_ID
    )
    visible_link = {
        "id": "NEL-REVIEW-B-DEFAULT-QUERY",
        "projectId": PROJECT_ID,
        "nodeId": NODE_ID,
        "reviewPointId": point["id"],
        "documentId": "DOC-REVIEW-B-DEFAULT-QUERY",
        "documentVersionId": "DV-REVIEW-B-DEFAULT-QUERY",
        "fileName": "设计单位许可证.pdf",
        "manualStatus": "pending",
        "pageNo": 2,
        "bbox": [10, 20, 260, 60],
        "quotedText": "许可范围：压力管道设计 GC2",
        "formalEvidenceEligible": True,
        "evidenceTier": "formal",
    }
    repo.state["node_evidence_links"].append(visible_link)
    live_call = {}

    def fake_search_project_evidence(repository, **kwargs):
        live_call.update(kwargs)
        candidate = {
            **visible_link,
            "id": "EVC-REVIEW-B-DEFAULT-QUERY",
            "bm25Rank": 1,
            "denseRank": None,
            "fusedScore": 0.016,
        }
        return {
            "formalCandidates": [candidate],
            "advisoryCandidates": [],
            "allCandidates": [candidate],
            "trace": {"retrievalTraceId": "RTR-LIVE-DEFAULT-QUERY"},
            "degraded": False,
            "fallbackReason": None,
        }

    monkeypatch.setattr(
        routes_module,
        "search_project_evidence",
        fake_search_project_evidence,
    )
    session = create_session()
    assert_ok(
        client.post(
            f"/api/review-sessions/{session['id']}/messages",
            headers={
                **HEADERS,
                "Idempotency-Key": "review-b-evidence-default-query-test",
                "If-Match": session["etag"],
            },
            json={"content": "/检索证据"},
        )
    )

    assert live_call["query"]
    assert "核对设计单位许可证" in live_call["query"]
    assert live_call["document_version_ids"] == ["DV-REVIEW-B-DEFAULT-QUERY"]


def test_review_b_search_evidence_successful_no_hit_renders_empty_live_result(
    monkeypatch,
) -> None:
    point = next(
        item
        for item in repo.state["admin_config"]["materialReviewPoints"]
        if int(item.get("nodeId") or 0) == NODE_ID
    )
    repo.state["node_evidence_links"].append(
        {
            "id": "NEL-REVIEW-B-NO-LIVE-HIT",
            "projectId": PROJECT_ID,
            "nodeId": NODE_ID,
            "reviewPointId": point["id"],
            "documentId": "DOC-REVIEW-B-NO-LIVE-HIT",
            "documentVersionId": "DV-REVIEW-B-NO-LIVE-HIT",
            "fileName": "设计单位许可证.pdf",
            "manualStatus": "pending",
            "pageNo": 2,
            "bbox": [10, 20, 260, 60],
            "quotedText": "许可范围：压力管道设计 GC2",
            "formalEvidenceEligible": True,
            "evidenceTier": "formal",
        }
    )

    def empty_search_project_evidence(repository, **kwargs):
        return {
            "formalCandidates": [],
            "advisoryCandidates": [],
            "allCandidates": [],
            "trace": {"retrievalTraceId": "RTR-LIVE-NO-HIT"},
            "degraded": False,
            "fallbackReason": None,
        }

    monkeypatch.setattr(
        routes_module,
        "search_project_evidence",
        empty_search_project_evidence,
    )
    session = create_session()
    response = assert_ok(
        client.post(
            f"/api/review-sessions/{session['id']}/messages",
            headers={
                **HEADERS,
                "Idempotency-Key": "review-b-evidence-no-live-hit-test",
                "If-Match": session["etag"],
            },
            json={"content": "/检索证据 不存在的证据"},
        )
    )
    card = next(
        block
        for block in response["assistantMessage"]["contentBlocks"]
        if block["type"] == "evidence_card"
    )

    assert card["items"] == []
    assert card["fallbackUsed"] is False
    assert card["fallbackReason"] is None
    assert card["retrievalTraceId"] == "RTR-LIVE-NO-HIT"


def test_review_b_search_evidence_never_calls_live_service_with_empty_allowlist(
    monkeypatch,
) -> None:
    repo.state["node_evidence_links"] = []
    called = False

    def forbidden_project_wide_search(repository, **kwargs):
        nonlocal called
        called = True
        return {
            "formalCandidates": [],
            "advisoryCandidates": [],
            "allCandidates": [],
            "trace": {"retrievalTraceId": "RTR-PROJECT-WIDE"},
        }

    monkeypatch.setattr(
        routes_module,
        "search_project_evidence",
        forbidden_project_wide_search,
    )
    session = create_session()
    response = assert_ok(
        client.post(
            f"/api/review-sessions/{session['id']}/messages",
            headers={
                **HEADERS,
                "Idempotency-Key": "review-b-evidence-empty-scope-test",
                "If-Match": session["etag"],
            },
            json={"content": "/检索证据 许可证"},
        )
    )
    card = next(
        block
        for block in response["assistantMessage"]["contentBlocks"]
        if block["type"] == "evidence_card"
    )

    assert called is False
    assert card["items"] == []
    assert card["fallbackUsed"] is True
    assert card["fallbackReason"] == "empty_visible_evidence_scope"


def test_review_b_free_form_message_uses_configured_qwen_runtime(monkeypatch) -> None:
    class FakeQwenRuntime:
        def chat_sync(self, messages, model, **kwargs):
            assert model == "review-chat"
            assert '"fixedBasis"' in messages[-1]["content"]
            assert "许可证有效期风险" in messages[-1]["content"]
            assert "[显示文本](basis:basisRefId)" in messages[0]["content"]
            assert "不得直接展示 LOC" in messages[0]["content"]
            assert kwargs["temperature"] == 0.1
            return {
                "id": "chatcmpl-review-b-test",
                "provider": "test-qwen",
                "model": "qwen-review-test",
                "choices": [
                    {
                        "message": {
                            "content": "当前证据仍需人工确认；建议先核对许可证有效期与施工周期。"
                        }
                    }
                ],
                "usage": {"prompt_tokens": 120, "completion_tokens": 28},
            }

    monkeypatch.setenv("AICHECK_REVIEW_CONVERSATION_LLM_EXECUTION", "litellm")
    monkeypatch.setattr(routes_module, "qwen_runtime_client", lambda: FakeQwenRuntime())
    session = create_session()
    response = assert_ok(
        client.post(
            f"/api/review-sessions/{session['id']}/messages",
            headers={
                **HEADERS,
                "Idempotency-Key": "review-b-free-form-qwen-test",
                "If-Match": session["etag"],
            },
            json={"content": "请结合当前证据说明许可证有效期风险。"},
        )
    )
    text_blocks = [
        block["text"]
        for block in response["assistantMessage"]["contentBlocks"]
        if block["type"] == "text"
    ]
    assert text_blocks == ["当前证据仍需人工确认；建议先核对许可证有效期与施工周期。"]
    text_block = next(
        block
        for block in response["assistantMessage"]["contentBlocks"]
        if block["type"] == "text"
    )
    basis_references = [
        reference for reference in text_block["references"] if reference["kind"] == "basis"
    ]
    assert basis_references
    assert basis_references[0]["referenceId"].startswith("LOC-")
    assert basis_references[0]["label"] == "TSG D7006—2020 第 D2.1 条"
    assert not basis_references[0]["label"].startswith(("LOC-", "STD-"))
    assert basis_references[0]["basis"]["previewAvailable"] is True
    assert response["assistantMessage"]["execution"] == {
        "executionId": response["assistantMessage"]["execution"]["executionId"],
        "mode": "llm_agent",
        "modelCalled": True,
        "agentEnabled": True,
        "toolCallCount": 0,
        "turnCount": 1,
        "provider": "test-qwen",
        "model": "qwen-review-test",
        "usage": {
            "inputTokens": 120,
            "outputTokens": 28,
            "totalTokens": 148,
        },
    }

    events = assert_ok(
        client.get(f"/api/review-sessions/{session['id']}/events", headers=HEADERS)
    )["events"]
    assert "agent.model_call.completed" in {item["eventType"] for item in events}


def test_review_b_agent_omits_usage_when_provider_reports_none(monkeypatch) -> None:
    class UnmeteredRuntime:
        def chat_sync(self, messages, model, **kwargs):
            return {
                "id": "chatcmpl-agent-unmetered",
                "provider": "test-qwen",
                "model": "qwen-agent-test",
                "choices": [{"message": {"content": "当前调用未返回 Token 计量信息。"}}],
                "usage": {},
            }

    monkeypatch.setenv("AICHECK_REVIEW_CONVERSATION_LLM_EXECUTION", "litellm")
    monkeypatch.setattr(routes_module, "qwen_runtime_client", lambda: UnmeteredRuntime())
    session = create_session()
    response = assert_ok(
        client.post(
            f"/api/review-sessions/{session['id']}/messages",
            headers={
                **HEADERS,
                "Idempotency-Key": "review-b-agent-unmetered-test",
                "If-Match": session["etag"],
            },
            json={"content": "请说明当前节点状态。"},
        )
    )

    assert "usage" not in response["assistantMessage"]["execution"]


def test_review_b_agent_runs_bounded_read_only_tool_loop(monkeypatch) -> None:
    class FakeAgentRuntime:
        def __init__(self) -> None:
            self.turn = 0

        def chat_sync(self, messages, model, **kwargs):
            self.turn += 1
            assert model == "review-chat"
            assert kwargs["tool_choice"] == "auto"
            assert {item["function"]["name"] for item in kwargs["tools"]} >= {
                "get_review_context",
                "search_node_evidence",
                "get_fixed_basis",
                "check_design_license_scope",
                "check_date_covers",
                "check_all_equal",
                "extract_table_records",
            }
            assert '"nodeEvidence"' in messages[-1]["content"] or any(
                '"nodeEvidence"' in str(message.get("content") or "") for message in messages
            )
            if self.turn == 1:
                return {
                    "id": "chatcmpl-agent-turn-1",
                    "provider": "test-qwen",
                    "model": "qwen-agent-test",
                    "choices": [
                        {
                            "message": {
                                "content": "",
                                "tool_calls": [
                                    {
                                        "id": "call-review-context",
                                        "type": "function",
                                        "function": {
                                            "name": "get_review_context",
                                            "arguments": "{}",
                                        },
                                    }
                                ],
                            }
                        }
                    ],
                    "usage": {"prompt_tokens": 80, "completion_tokens": 12},
                }
            assert any(message.get("role") == "tool" for message in messages)
            assert "evidenceReadiness" in next(
                message["content"] for message in messages if message.get("role") == "tool"
            )
            return {
                "id": "chatcmpl-agent-turn-2",
                "provider": "test-qwen",
                "model": "qwen-agent-test",
                "choices": [
                    {
                        "message": {
                            "content": "当前资料尚未满足全部要求，建议先补齐缺项并由监检人员确认。"
                        }
                    }
                ],
                "usage": {"prompt_tokens": 110, "completion_tokens": 22},
            }

    runtime = FakeAgentRuntime()
    monkeypatch.setenv("AICHECK_REVIEW_CONVERSATION_LLM_EXECUTION", "litellm")
    monkeypatch.setattr(routes_module, "qwen_runtime_client", lambda: runtime)
    session = create_session()
    response = assert_ok(
        client.post(
            f"/api/review-sessions/{session['id']}/messages",
            headers={
                **HEADERS,
                "Idempotency-Key": "review-b-agent-tool-loop-test",
                "If-Match": session["etag"],
            },
            json={"content": "请核查当前节点资料是否完整，并说明下一步。"},
        )
    )

    execution = response["assistantMessage"]["execution"]
    assert execution["mode"] == "llm_agent"
    assert execution["modelCalled"] is True
    assert execution["agentEnabled"] is True
    assert execution["toolCallCount"] == 1
    assert execution["turnCount"] == 2
    assert execution["usage"] == {
        "inputTokens": 190,
        "outputTokens": 34,
        "totalTokens": 224,
    }

    events = assert_ok(
        client.get(f"/api/review-sessions/{session['id']}/events", headers=HEADERS)
    )["events"]
    event_types = [item["eventType"] for item in events]
    assert event_types.count("agent.model_call.started") == 2
    assert event_types.count("agent.model_call.completed") == 2
    assert "agent.tool_call.started" in event_types
    assert "agent.tool_call.completed" in event_types
    assert "agent.execution.completed" in event_types
    assert "agent.model_call.failed" not in event_types


def test_review_b_agent_search_uses_hybrid_evidence_service(monkeypatch) -> None:
    visible_link = {
        "id": "NEL-AGENT-VISIBLE",
        "projectId": PROJECT_ID,
        "nodeId": NODE_ID,
        "documentId": "DOC-AGENT-VISIBLE",
        "documentVersionId": "DV-AGENT-VISIBLE",
        "fileName": "设计单位许可证.pdf",
        "manualStatus": "pending",
        "pageNo": 2,
        "bbox": [10, 20, 260, 60],
        "quotedText": "许可范围：压力管道设计 GC2",
        "formalEvidenceEligible": True,
        "evidenceTier": "formal",
    }
    called = {}
    formal = {
        **visible_link,
        "id": "EVC-AGENT-FORMAL",
        "candidateId": "EVC-AGENT-FORMAL",
        "bm25Rank": 1,
        "denseRank": 2,
        "fusedScore": 0.027,
    }
    advisory = {
        **visible_link,
        "id": "EVC-AGENT-ADVISORY",
        "candidateId": "EVC-AGENT-ADVISORY",
        "pageNo": 1,
        "bbox": None,
        "quotedText": "设计单位许可证",
        "formalEvidenceEligible": False,
        "evidenceTier": "advisory",
        "rejectionReasons": ["missing_bbox"],
        "bm25Rank": 2,
        "denseRank": 1,
        "fusedScore": 0.026,
    }
    out_of_scope = {
        **formal,
        "id": "EVC-AGENT-OUT-OF-SCOPE",
        "candidateId": "EVC-AGENT-OUT-OF-SCOPE",
        "documentVersionId": "DV-AGENT-HIDDEN",
    }

    def fake_search_project_evidence(repository, **kwargs):
        called.update(kwargs)
        return {
            "formalCandidates": [formal, out_of_scope],
            "advisoryCandidates": [advisory],
            "allCandidates": [formal, advisory, out_of_scope],
            "trace": {"retrievalTraceId": "RTR-AGENT-1"},
            "degraded": False,
            "fallbackReason": None,
        }

    monkeypatch.setattr(
        routes_module,
        "search_project_evidence",
        fake_search_project_evidence,
    )
    output = call_review_agent_tool(
        "search_node_evidence",
        {"query": "许可证有效期"},
        evidence_links=[visible_link],
    )

    assert called["project_id"] == PROJECT_ID
    assert called["node_id"] == NODE_ID
    assert called["document_version_ids"] == ["DV-AGENT-VISIBLE"]
    assert called["query"] == "许可证有效期"
    assert output["projectId"] == PROJECT_ID
    assert output["retrievalTraceId"] == "RTR-AGENT-1"
    assert output["fallbackUsed"] is False
    assert output["candidateCount"] == 2
    assert output["formalCandidateCount"] == 1
    assert output["advisoryCandidateCount"] == 1
    assert [item["candidateId"] for item in output["candidates"]] == [
        "EVC-AGENT-FORMAL",
        "EVC-AGENT-ADVISORY",
    ]
    assert output["candidates"][0]["bm25Rank"] == 1
    assert output["candidates"][0]["denseRank"] == 2
    assert output["candidates"][0]["fusedScore"] == 0.027
    assert output["candidates"][0]["evidenceTier"] == "formal"
    assert output["candidates"][1]["evidenceTier"] == "advisory"


def test_review_b_agent_search_includes_advisory_only_visible_version(
    monkeypatch,
) -> None:
    point = next(
        item
        for item in repo.state["admin_config"]["materialReviewPoints"]
        if int(item.get("nodeId") or 0) == NODE_ID
    )
    advisory_link = {
        "id": "NEL-AGENT-ADVISORY-ONLY",
        "projectId": PROJECT_ID,
        "nodeId": NODE_ID,
        "reviewPointId": point["id"],
        "documentId": "DOC-AGENT-ADVISORY-ONLY",
        "documentVersionId": "DV-AGENT-ADVISORY-ONLY",
        "fileName": "待定位许可证.pdf",
        "manualStatus": "pending",
        "manualStatusLabel": "待确认",
        "pageNo": 1,
        "bbox": None,
        "quotedText": "设计单位许可证",
        "formalEvidenceEligible": False,
        "evidenceTier": "advisory",
        "rejectionReasons": ["missing_bbox"],
    }
    repo.state["node_evidence_links"].append(advisory_link)
    in_scope_candidate = {
        **advisory_link,
        "id": "EVC-AGENT-ADVISORY-ONLY-FORMAL",
        "candidateId": "EVC-AGENT-ADVISORY-ONLY-FORMAL",
        "pageNo": 3,
        "bbox": [10, 20, 260, 60],
        "quotedText": "许可证有效期至 2028-12-31",
        "formalEvidenceEligible": True,
        "evidenceTier": "formal",
        "rejectionReasons": [],
        "bm25Rank": 1,
        "denseRank": 1,
        "fusedScore": 0.027,
    }
    out_of_scope_candidate = {
        **in_scope_candidate,
        "id": "EVC-AGENT-ADVISORY-ONLY-OUT-OF-SCOPE",
        "candidateId": "EVC-AGENT-ADVISORY-ONLY-OUT-OF-SCOPE",
        "documentVersionId": "DV-AGENT-OUT-OF-SCOPE",
    }
    service_call = {}

    def fake_search_project_evidence(repository, **kwargs):
        service_call.update(kwargs)
        candidates = [in_scope_candidate, out_of_scope_candidate]
        return {
            "formalCandidates": candidates,
            "advisoryCandidates": [],
            "allCandidates": candidates,
            "trace": {"retrievalTraceId": "RTR-AGENT-ADVISORY-ONLY"},
            "degraded": False,
            "fallbackReason": None,
        }

    tool_output = {}

    class AdvisoryOnlySearchRuntime:
        def __init__(self) -> None:
            self.turn = 0

        def chat_sync(self, messages, model, **kwargs):
            self.turn += 1
            if self.turn == 1:
                return {
                    "id": "chatcmpl-agent-advisory-only-1",
                    "provider": "test-qwen",
                    "model": "qwen-agent-test",
                    "choices": [
                        {
                            "message": {
                                "content": "",
                                "tool_calls": [
                                    {
                                        "id": "call-agent-advisory-only-search",
                                        "type": "function",
                                        "function": {
                                            "name": "search_node_evidence",
                                            "arguments": json.dumps(
                                                {"query": "许可证有效期"},
                                                ensure_ascii=False,
                                            ),
                                        },
                                    }
                                ],
                            }
                        }
                    ],
                    "usage": {"prompt_tokens": 80, "completion_tokens": 12},
                }
            tool_message = next(
                message for message in reversed(messages) if message.get("role") == "tool"
            )
            tool_output.update(json.loads(tool_message["content"]))
            return {
                "id": "chatcmpl-agent-advisory-only-2",
                "provider": "test-qwen",
                "model": "qwen-agent-test",
                "choices": [{"message": {"content": "已检索当前节点可见版本。"}}],
                "usage": {"prompt_tokens": 110, "completion_tokens": 18},
            }

    monkeypatch.setenv("AICHECK_REVIEW_CONVERSATION_LLM_EXECUTION", "litellm")
    monkeypatch.setattr(routes_module, "qwen_runtime_client", AdvisoryOnlySearchRuntime)
    monkeypatch.setattr(
        routes_module,
        "search_project_evidence",
        fake_search_project_evidence,
    )
    session = create_session()

    response = assert_ok(
        client.post(
            f"/api/review-sessions/{session['id']}/messages",
            headers={
                **HEADERS,
                "Idempotency-Key": "review-b-agent-advisory-only-scope-test",
                "If-Match": session["etag"],
            },
            json={"content": "检索许可证有效期证据。"},
        )
    )

    assert response["status"] == "completed"
    assert service_call["document_version_ids"] == ["DV-AGENT-ADVISORY-ONLY"]
    assert [item["candidateId"] for item in tool_output["candidates"]] == [
        "EVC-AGENT-ADVISORY-ONLY-FORMAL"
    ]
    assert tool_output["candidates"][0]["manualStatus"] == "pending"
    assert tool_output["candidates"][0]["formalEvidenceEligible"] is True


def test_review_b_agent_search_uses_visible_manual_status_scope(monkeypatch) -> None:
    confirmed_link = {
        "id": "NEL-AGENT-CONFIRMED",
        "projectId": PROJECT_ID,
        "nodeId": NODE_ID,
        "documentId": "DOC-AGENT-CONFIRMED",
        "documentVersionId": "DV-AGENT-CONFIRMED",
        "fileName": "已确认许可证.pdf",
        "manualStatus": "confirmed",
        "manualStatusLabel": "已确认",
        "pageNo": 2,
        "bbox": [10, 20, 260, 60],
        "quotedText": "许可证有效期至 2028-12-31",
        "formalEvidenceEligible": True,
        "evidenceTier": "formal",
    }
    pending_link = {
        **confirmed_link,
        "id": "NEL-AGENT-PENDING",
        "documentId": "DOC-AGENT-PENDING",
        "documentVersionId": "DV-AGENT-PENDING",
        "fileName": "待确认许可证.pdf",
        "manualStatus": "pending",
        "manualStatusLabel": "待确认",
    }
    live_candidates = [
        {
            **confirmed_link,
            "id": "EVC-AGENT-CONFIRMED",
            "candidateId": "EVC-AGENT-CONFIRMED",
            "manualStatus": "pending",
            "manualStatusLabel": "待确认",
            "bm25Rank": 1,
            "denseRank": 1,
            "fusedScore": 0.027,
        },
        {
            **pending_link,
            "id": "EVC-AGENT-PENDING",
            "candidateId": "EVC-AGENT-PENDING",
            "manualStatus": "pending",
            "manualStatusLabel": "待确认",
            "bm25Rank": 2,
            "denseRank": 2,
            "fusedScore": 0.026,
        },
    ]
    calls = []

    def fake_search_project_evidence(repository, **kwargs):
        calls.append(kwargs)
        return {
            "formalCandidates": live_candidates,
            "advisoryCandidates": [],
            "allCandidates": live_candidates,
            "trace": {"retrievalTraceId": f"RTR-STATUS-{len(calls)}"},
            "degraded": False,
            "fallbackReason": None,
        }

    monkeypatch.setattr(
        routes_module,
        "search_project_evidence",
        fake_search_project_evidence,
    )
    confirmed = call_review_agent_tool(
        "search_node_evidence",
        {"query": "许可证", "manualStatus": "confirmed"},
        evidence_links=[confirmed_link, pending_link],
    )
    pending = call_review_agent_tool(
        "search_node_evidence",
        {"query": "许可证", "manualStatus": "pending"},
        evidence_links=[confirmed_link, pending_link],
    )
    unfiltered = call_review_agent_tool(
        "search_node_evidence",
        {"query": "许可证"},
        evidence_links=[confirmed_link, pending_link],
    )

    expected_visible_versions = [
        "DV-AGENT-CONFIRMED",
        "DV-AGENT-PENDING",
    ]
    assert calls[0]["document_version_ids"] == expected_visible_versions
    assert calls[1]["document_version_ids"] == expected_visible_versions
    assert calls[2]["document_version_ids"] == expected_visible_versions
    assert [item["candidateId"] for item in confirmed["candidates"]] == [
        "EVC-AGENT-CONFIRMED"
    ]
    assert confirmed["candidates"][0]["manualStatus"] == "confirmed"
    assert confirmed["candidates"][0]["manualStatusLabel"] == "已确认"
    assert [item["candidateId"] for item in pending["candidates"]] == [
        "EVC-AGENT-PENDING"
    ]
    assert pending["candidates"][0]["manualStatus"] == "pending"
    assert pending["candidates"][0]["manualStatusLabel"] == "待确认"
    assert [item["manualStatus"] for item in unfiltered["candidates"]] == [
        "confirmed",
        "pending",
    ]


def test_review_b_agent_search_status_filter_matches_same_version_evidence_identity(
    monkeypatch,
) -> None:
    shared = {
        "projectId": PROJECT_ID,
        "nodeId": NODE_ID,
        "documentId": "DOC-AGENT-SHARED-STATUS",
        "documentVersionId": "DV-AGENT-SHARED-STATUS",
        "fileName": "同版许可证.pdf",
        "formalEvidenceEligible": True,
        "evidenceTier": "formal",
    }
    confirmed_link = {
        **shared,
        "id": "NEL-AGENT-SHARED-CONFIRMED",
        "manualStatus": "confirmed",
        "manualStatusLabel": "已确认",
        "pageNo": 2,
        "bbox": [10, 20, 260, 60],
        "quotedText": "许可证有效期至 2028-12-31",
    }
    pending_link = {
        **shared,
        "id": "NEL-AGENT-SHARED-PENDING",
        "manualStatus": "pending",
        "manualStatusLabel": "待确认",
        "pageNo": 3,
        "bbox": [10, 70, 260, 110],
        "quotedText": "许可范围：压力管道设计 GC2",
    }
    confirmed_candidate = {
        **confirmed_link,
        "id": "EVC-AGENT-SHARED-CONFIRMED",
        "candidateId": "EVC-AGENT-SHARED-CONFIRMED",
        "evidenceLinkId": "NEL-AGENT-SHARED-CONFIRMED",
        "manualStatus": "pending",
        "manualStatusLabel": "待确认",
        "bm25Rank": 1,
        "denseRank": 1,
        "fusedScore": 0.027,
    }
    pending_candidate = {
        **pending_link,
        "id": "EVC-AGENT-SHARED-PENDING",
        "candidateId": "EVC-AGENT-SHARED-PENDING",
        "bm25Rank": 2,
        "denseRank": 2,
        "fusedScore": 0.026,
    }
    unmatched_candidate = {
        **pending_candidate,
        "id": "EVC-AGENT-SHARED-UNMATCHED",
        "candidateId": "EVC-AGENT-SHARED-UNMATCHED",
        "pageNo": 4,
        "bbox": [10, 120, 260, 160],
        "quotedText": "服务新增但未关联可见 evidence 的候选",
        "bm25Rank": 3,
        "denseRank": 3,
        "fusedScore": 0.025,
    }
    calls = []

    def fake_search_project_evidence(repository, **kwargs):
        calls.append(kwargs)
        candidates = [
            confirmed_candidate,
            pending_candidate,
            unmatched_candidate,
        ]
        return {
            "formalCandidates": candidates,
            "advisoryCandidates": [],
            "allCandidates": candidates,
            "trace": {"retrievalTraceId": f"RTR-SHARED-STATUS-{len(calls)}"},
            "degraded": False,
            "fallbackReason": None,
        }

    monkeypatch.setattr(
        routes_module,
        "search_project_evidence",
        fake_search_project_evidence,
    )
    confirmed = call_review_agent_tool(
        "search_node_evidence",
        {"query": "许可证", "manualStatus": "confirmed"},
        evidence_links=[confirmed_link, pending_link],
    )
    pending = call_review_agent_tool(
        "search_node_evidence",
        {"query": "许可证", "manualStatus": "pending"},
        evidence_links=[confirmed_link, pending_link],
    )

    assert calls[0]["document_version_ids"] == ["DV-AGENT-SHARED-STATUS"]
    assert calls[1]["document_version_ids"] == ["DV-AGENT-SHARED-STATUS"]
    assert [item["candidateId"] for item in confirmed["candidates"]] == [
        "EVC-AGENT-SHARED-CONFIRMED"
    ]
    assert confirmed["candidates"][0]["manualStatus"] == "confirmed"
    assert [item["candidateId"] for item in pending["candidates"]] == [
        "EVC-AGENT-SHARED-PENDING"
    ]
    assert pending["candidates"][0]["manualStatus"] == "pending"


def test_review_b_agent_search_locator_fallback_requires_valid_bbox(
    monkeypatch,
) -> None:
    shared = {
        "projectId": PROJECT_ID,
        "nodeId": NODE_ID,
        "documentId": "DOC-AGENT-LOCATOR-BBOX",
        "documentVersionId": "DV-AGENT-LOCATOR-BBOX",
        "fileName": "定位框有效性.pdf",
        "manualStatus": "confirmed",
        "manualStatusLabel": "已确认",
        "formalEvidenceEligible": True,
        "evidenceTier": "formal",
    }
    invalid_bboxes = [
        [],
        [10, 20, 260],
        [10, 20, 260, 60, 999],
        ["left", 20, 260, 60],
        [10, 20, 10, 60],
        [10, 20, 260, 20],
    ]
    invalid_links = [
        {
            **shared,
            "id": f"NEL-AGENT-INVALID-BBOX-{index}",
            "pageNo": index,
            "bbox": bbox,
            "quotedText": f"无效定位框证据 {index}",
        }
        for index, bbox in enumerate(invalid_bboxes, start=1)
    ]
    invalid_candidates = [
        {
            **link,
            "id": f"EVC-AGENT-INVALID-BBOX-{index}",
            "candidateId": f"EVC-AGENT-INVALID-BBOX-{index}",
        }
        for index, link in enumerate(invalid_links, start=1)
    ]
    valid_link = {
        **shared,
        "id": "NEL-AGENT-VALID-BBOX",
        "pageNo": 20,
        "bbox": [10, 20, 260, 60],
        "quotedText": "有效四坐标定位证据",
    }
    valid_locator_candidate = {
        **valid_link,
        "id": "EVC-AGENT-VALID-BBOX",
        "candidateId": "EVC-AGENT-VALID-BBOX",
    }
    id_link = {
        **shared,
        "id": "NEL-AGENT-ID-WITH-INVALID-BBOX",
        "pageNo": 21,
        "bbox": [],
        "quotedText": "显式证据 ID 优先于定位框",
    }
    id_candidate = {
        **id_link,
        "id": "EVC-AGENT-ID-WITH-INVALID-BBOX",
        "candidateId": "EVC-AGENT-ID-WITH-INVALID-BBOX",
        "evidenceLinkId": "NEL-AGENT-ID-WITH-INVALID-BBOX",
    }
    live_candidates = [
        *invalid_candidates,
        valid_locator_candidate,
        id_candidate,
    ]

    def fake_search_project_evidence(repository, **kwargs):
        return {
            "formalCandidates": live_candidates,
            "advisoryCandidates": [],
            "allCandidates": live_candidates,
            "trace": {"retrievalTraceId": "RTR-LOCATOR-BBOX"},
            "degraded": False,
            "fallbackReason": None,
        }

    monkeypatch.setattr(
        routes_module,
        "search_project_evidence",
        fake_search_project_evidence,
    )
    output = call_review_agent_tool(
        "search_node_evidence",
        {"query": "定位框", "manualStatus": "confirmed"},
        evidence_links=[*invalid_links, valid_link, id_link],
    )

    assert [item["candidateId"] for item in output["candidates"]] == [
        "EVC-AGENT-VALID-BBOX",
        "EVC-AGENT-ID-WITH-INVALID-BBOX",
    ]


def test_review_b_agent_search_exception_fallback_keeps_same_version_status_identity(
    monkeypatch,
) -> None:
    shared = {
        "projectId": PROJECT_ID,
        "nodeId": NODE_ID,
        "documentId": "DOC-AGENT-SHARED-FALLBACK",
        "documentVersionId": "DV-AGENT-SHARED-FALLBACK",
        "fileName": "同版许可证.pdf",
        "pageNo": 2,
        "bbox": [10, 20, 260, 60],
        "formalEvidenceEligible": True,
        "evidenceTier": "formal",
    }
    confirmed_link = {
        **shared,
        "id": "NEL-AGENT-SHARED-FALLBACK-CONFIRMED",
        "manualStatus": "confirmed",
        "manualStatusLabel": "已确认",
        "quotedText": "许可证有效期至 2028-12-31",
    }
    pending_link = {
        **shared,
        "id": "NEL-AGENT-SHARED-FALLBACK-PENDING",
        "manualStatus": "pending",
        "manualStatusLabel": "待确认",
        "pageNo": 3,
        "bbox": [10, 70, 260, 110],
        "quotedText": "许可范围：压力管道设计 GC2",
    }

    def broken_search_project_evidence(repository, **kwargs):
        raise RuntimeError("retrieval unavailable")

    monkeypatch.setattr(
        routes_module,
        "search_project_evidence",
        broken_search_project_evidence,
    )
    confirmed = call_review_agent_tool(
        "search_node_evidence",
        {"query": "许可证", "manualStatus": "confirmed"},
        evidence_links=[confirmed_link, pending_link],
    )
    pending = call_review_agent_tool(
        "search_node_evidence",
        {"query": "许可证", "manualStatus": "pending"},
        evidence_links=[confirmed_link, pending_link],
    )
    unfiltered = call_review_agent_tool(
        "search_node_evidence",
        {"query": "许可证"},
        evidence_links=[confirmed_link, pending_link],
    )

    assert [item["evidenceLinkId"] for item in confirmed["candidates"]] == [
        "NEL-AGENT-SHARED-FALLBACK-CONFIRMED"
    ]
    assert [item["evidenceLinkId"] for item in pending["candidates"]] == [
        "NEL-AGENT-SHARED-FALLBACK-PENDING"
    ]
    assert [item["manualStatus"] for item in unfiltered["candidates"]] == [
        "confirmed",
        "pending",
    ]
    assert confirmed["fallbackUsed"] is True
    assert pending["fallbackUsed"] is True


def test_review_b_agent_search_falls_back_only_on_service_exception(monkeypatch) -> None:
    visible_links = [
        {
            "id": "NEL-AGENT-FALLBACK-FORMAL",
            "projectId": PROJECT_ID,
            "nodeId": NODE_ID,
            "documentId": "DOC-AGENT-FALLBACK",
            "documentVersionId": "DV-AGENT-FALLBACK",
            "fileName": "设计单位许可证.pdf",
            "manualStatus": "pending",
            "pageNo": 2,
            "bbox": [10, 20, 260, 60],
            "quotedText": "许可范围：压力管道设计 GC2",
        },
        {
            "id": "NEL-AGENT-FALLBACK-ADVISORY",
            "projectId": PROJECT_ID,
            "nodeId": NODE_ID,
            "documentId": "DOC-AGENT-FALLBACK",
            "documentVersionId": "DV-AGENT-FALLBACK",
            "fileName": "设计单位许可证.pdf",
            "manualStatus": "pending",
            "pageNo": 1,
            "bbox": None,
            "quotedText": "设计单位许可证",
            "formalEvidenceEligible": False,
            "evidenceTier": "advisory",
            "rejectionReasons": ["missing_bbox"],
        },
    ]

    def broken_search_project_evidence(repository, **kwargs):
        raise RuntimeError("retrieval unavailable")

    monkeypatch.setattr(
        routes_module,
        "search_project_evidence",
        broken_search_project_evidence,
    )
    output = call_review_agent_tool(
        "search_node_evidence",
        {"query": "许可证有效期"},
        evidence_links=visible_links,
    )

    assert output["fallbackUsed"] is True
    assert output["fallbackReason"] == "live_retrieval_exception"
    assert output["retrievalTraceId"] is None
    assert output["candidateCount"] == 2
    assert [item["candidateId"] for item in output["candidates"]] == [
        "NEL-AGENT-FALLBACK-FORMAL",
        "NEL-AGENT-FALLBACK-ADVISORY",
    ]
    assert [item["evidenceLinkId"] for item in output["candidates"]] == [
        "NEL-AGENT-FALLBACK-FORMAL",
        "NEL-AGENT-FALLBACK-ADVISORY",
    ]
    assert output["candidates"][0]["formalEvidenceEligible"] is True
    assert output["candidates"][0]["evidenceTier"] == "formal"
    assert output["candidates"][1]["formalEvidenceEligible"] is False
    assert output["candidates"][1]["evidenceTier"] == "advisory"
    assert output["formalCandidateCount"] == 1
    assert output["advisoryCandidateCount"] == 1


def test_review_b_agent_search_successful_no_hit_returns_zero_candidates(
    monkeypatch,
) -> None:
    visible_link = {
        "id": "NEL-AGENT-NO-HIT",
        "projectId": PROJECT_ID,
        "nodeId": NODE_ID,
        "documentId": "DOC-AGENT-NO-HIT",
        "documentVersionId": "DV-AGENT-NO-HIT",
        "fileName": "设计单位许可证.pdf",
        "manualStatus": "pending",
        "pageNo": 2,
        "bbox": [10, 20, 260, 60],
        "quotedText": "许可范围：压力管道设计 GC2",
        "formalEvidenceEligible": True,
        "evidenceTier": "formal",
    }

    def empty_search_project_evidence(repository, **kwargs):
        return {
            "formalCandidates": [],
            "advisoryCandidates": [],
            "allCandidates": [],
            "trace": {"retrievalTraceId": "RTR-AGENT-NO-HIT"},
            "degraded": False,
            "fallbackReason": None,
        }

    monkeypatch.setattr(
        routes_module,
        "search_project_evidence",
        empty_search_project_evidence,
    )
    output = call_review_agent_tool(
        "search_node_evidence",
        {"query": "不存在的证据"},
        evidence_links=[visible_link],
    )

    assert output["retrievalTraceId"] == "RTR-AGENT-NO-HIT"
    assert output["candidateCount"] == 0
    assert output["candidates"] == []
    assert output["queryMissed"] is True
    assert output["fallbackUsed"] is False
    assert output["fallbackReason"] is None


def test_review_b_agent_search_never_calls_service_with_empty_allowlist(
    monkeypatch,
) -> None:
    called = False

    def forbidden_project_wide_search(repository, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("project-wide search must not run")

    monkeypatch.setattr(
        routes_module,
        "search_project_evidence",
        forbidden_project_wide_search,
    )
    output = call_review_agent_tool(
        "search_node_evidence",
        {"query": "许可证"},
        evidence_links=[],
    )

    assert called is False
    assert output["candidateCount"] == 0
    assert output["candidates"] == []
    assert output["fallbackUsed"] is False
    assert output["fallbackReason"] == "empty_visible_evidence_scope"


def _tool_call_response(turn: int) -> dict:
    return {
        "id": f"chatcmpl-agent-turn-{turn}",
        "provider": "test-qwen",
        "model": "qwen-agent-test",
        "choices": [
            {
                "message": {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": f"call-loop-{turn}",
                            "type": "function",
                            "function": {"name": "get_review_context", "arguments": "{}"},
                        }
                    ],
                }
            }
        ],
        "usage": {"prompt_tokens": 50, "completion_tokens": 8},
    }


def test_review_b_agent_forces_final_answer_at_max_turns(monkeypatch) -> None:
    class GreedyToolRuntime:
        def __init__(self) -> None:
            self.turn = 0
            self.tool_choices = []

        def chat_sync(self, messages, model, **kwargs):
            self.turn += 1
            self.tool_choices.append(kwargs["tool_choice"])
            if kwargs["tool_choice"] == "none":
                assert "轮次上限" in str(messages[-1].get("content") or "")
                return {
                    "id": "chatcmpl-agent-final",
                    "provider": "test-qwen",
                    "model": "qwen-agent-test",
                    "choices": [{"message": {"content": "已基于工具结果收束：资料就绪度不足，建议人工补齐后复核。"}}],
                    "usage": {"prompt_tokens": 60, "completion_tokens": 16},
                }
            return _tool_call_response(self.turn)

    runtime = GreedyToolRuntime()
    monkeypatch.setenv("AICHECK_REVIEW_CONVERSATION_LLM_EXECUTION", "litellm")
    monkeypatch.setenv("AICHECK_REVIEW_CONVERSATION_AGENT_MAX_TURNS", "3")
    monkeypatch.setattr(routes_module, "qwen_runtime_client", lambda: runtime)
    session = create_session()
    response = assert_ok(
        client.post(
            f"/api/review-sessions/{session['id']}/messages",
            headers={
                **HEADERS,
                "Idempotency-Key": "review-b-agent-forced-final-test",
                "If-Match": session["etag"],
            },
            json={"content": "请核查名称一致性。"},
        )
    )
    execution = response["assistantMessage"]["execution"]
    assert execution["mode"] == "llm_agent"
    assert execution["turnCount"] == 3
    assert runtime.tool_choices == ["auto", "auto", "none"]
    text_blocks = [
        block["text"]
        for block in response["assistantMessage"]["contentBlocks"]
        if block.get("type") == "text"
    ]
    assert any("已基于工具结果收束" in text for text in text_blocks)
    # 第二轮重复调用同参工具应命中缓存去重。
    events = assert_ok(
        client.get(f"/api/review-sessions/{session['id']}/events", headers=HEADERS)
    )["events"]
    duplicate_flags = [
        item["payload"].get("duplicate")
        for item in events
        if item["eventType"] == "agent.tool_call.completed"
    ]
    assert duplicate_flags == [False, True]


def test_review_b_agent_fallback_keeps_tool_results(monkeypatch) -> None:
    class BrokenFinalRuntime:
        def __init__(self) -> None:
            self.turn = 0

        def chat_sync(self, messages, model, **kwargs):
            self.turn += 1
            if kwargs["tool_choice"] == "none":
                # 最终收束轮输出为空，触发降级。
                return {
                    "id": "chatcmpl-agent-empty",
                    "provider": "test-qwen",
                    "model": "qwen-agent-test",
                    "choices": [{"message": {"content": ""}}],
                    "usage": {},
                }
            return _tool_call_response(self.turn)

    monkeypatch.setenv("AICHECK_REVIEW_CONVERSATION_LLM_EXECUTION", "litellm")
    monkeypatch.setenv("AICHECK_REVIEW_CONVERSATION_AGENT_MAX_TURNS", "2")
    monkeypatch.setattr(routes_module, "qwen_runtime_client", lambda: BrokenFinalRuntime())
    session = create_session()
    response = assert_ok(
        client.post(
            f"/api/review-sessions/{session['id']}/messages",
            headers={
                **HEADERS,
                "Idempotency-Key": "review-b-agent-fallback-test",
                "If-Match": session["etag"],
            },
            json={"content": "请核查名称一致性。"},
        )
    )
    execution = response["assistantMessage"]["execution"]
    assert execution["mode"] == "deterministic_fallback"
    assert execution["toolCallCount"] == 1
    assert execution["usage"] == {
        "inputTokens": 50,
        "outputTokens": 8,
        "totalTokens": 58,
    }
    text_blocks = [
        block["text"]
        for block in response["assistantMessage"]["contentBlocks"]
        if block.get("type") == "text"
    ]
    assert any("已完成的工具核查结果" in text for text in text_blocks)
    assert any("get_review_context" in text for text in text_blocks)


def test_review_b_event_stream_emits_events_and_completes() -> None:
    session = create_session()
    with client.stream(
        "GET",
        f"/api/review-sessions/{session['id']}/events/stream",
        params={"timeout_seconds": 1},
        headers=HEADERS,
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        body = "".join(response.iter_text())
    assert "session.created" in body
    assert "event: done" in body


def test_review_b_agent_formal_judgment_tool_runs_atomic_chain(monkeypatch) -> None:
    class FormalJudgmentRuntime:
        def __init__(self) -> None:
            self.turn = 0
            self.tool_payloads: list[str] = []

        def chat_sync(self, messages, model, **kwargs):
            self.turn += 1
            assert {item["function"]["name"] for item in kwargs["tools"]} >= {
                "run_node_formal_judgment",
                "assemble_node_judgment_facts",
            }
            if self.turn == 1:
                return {
                    "id": "chatcmpl-formal-turn-1",
                    "provider": "test-qwen",
                    "model": "qwen-agent-test",
                    "choices": [
                        {
                            "message": {
                                "content": "",
                                "tool_calls": [
                                    {
                                        "id": "call-formal-judgment",
                                        "type": "function",
                                        "function": {
                                            "name": "run_node_formal_judgment",
                                            "arguments": "{}",
                                        },
                                    }
                                ],
                            }
                        }
                    ],
                    "usage": {"prompt_tokens": 90, "completion_tokens": 10},
                }
            self.tool_payloads = [
                str(message.get("content") or "")
                for message in messages
                if message.get("role") == "tool"
            ]
            return {
                "id": "chatcmpl-formal-turn-2",
                "provider": "test-qwen",
                "model": "qwen-agent-test",
                "choices": [{"message": {"content": "已完成整体核查，详见核查结论表格。"}}],
                "usage": {"prompt_tokens": 130, "completion_tokens": 30},
            }

    runtime = FormalJudgmentRuntime()
    monkeypatch.setenv("AICHECK_REVIEW_CONVERSATION_LLM_EXECUTION", "litellm")
    monkeypatch.setattr(routes_module, "qwen_runtime_client", lambda: runtime)
    session = create_session()
    response = assert_ok(
        client.post(
            f"/api/review-sessions/{session['id']}/messages",
            headers={
                **HEADERS,
                "Idempotency-Key": "review-b-formal-judgment-test",
                "If-Match": session["etag"],
            },
            json={"content": "请对当前节点做整体核查。"},
        )
    )
    execution = response["assistantMessage"]["execution"]
    assert execution["mode"] == "llm_agent"
    assert execution["toolCallCount"] == 1
    # 工具结果进入模型上下文，且带 advisory 标注供模型转述。
    assert runtime.tool_payloads
    assert '"advisory": true' in runtime.tool_payloads[0]
    assert "bindingSetLifecycleStatus" in runtime.tool_payloads[0]

    events = assert_ok(
        client.get(f"/api/review-sessions/{session['id']}/events", headers=HEADERS)
    )["events"]
    completed = [
        item
        for item in events
        if item["eventType"] == "agent.tool_call.completed"
        and item["payload"].get("toolName") == "run_node_formal_judgment"
    ]
    assert completed
    assert str(completed[0]["payload"].get("summary") or "").startswith("正式判定链")


def test_review_b_formal_judgment_rejects_agent_type_nodes() -> None:
    project = repo.require_project(PROJECT_ID) or {}
    for node_id in (12, 19):
        output = routes_module.review_conversation_formal_judgment(
            project=project,
            node={"nodeId": node_id},
            evidence_links=[],
        )
        assert output["status"] == "rejected"
        assert output["errorCode"] == "REVIEW_AGENT_NODE_REQUIRES_HUMAN_TASK"


def test_review_b_message_references_preserve_evidence_locator() -> None:
    references = routes_module.review_message_source_references(
        [],
        [
            {
                "id": "E-LINK-001",
                "projectId": PROJECT_ID,
                "nodeId": NODE_ID,
                "objectType": "documentVersion",
                "objectId": "DV-001",
                "documentId": "DOC-001",
                "documentVersionId": "DV-001",
                "fileName": "设计单位许可证.pdf",
                "pageNo": 2,
                "quotedText": "许可范围：压力管道设计",
            }
        ],
    )

    assert references == [
        {
            "kind": "evidence",
            "referenceId": "E-LINK-001",
            "label": "设计单位许可证.pdf",
            "aliases": ["E-LINK-001", "设计单位许可证.pdf"],
            "evidence": {
                "id": "E-LINK-001",
                "projectId": PROJECT_ID,
                "nodeId": NODE_ID,
                "objectType": "documentVersion",
                "objectId": "DV-001",
                "documentId": "DOC-001",
                "documentVersionId": "DV-001",
                "fileName": "设计单位许可证.pdf",
                "pageNo": 2,
                "quotedText": "许可范围：压力管道设计",
            },
        }
    ]


def test_review_b_basis_labels_hide_internal_locator_ids() -> None:
    cases = [
        (
            {"standardCode": "TSG D7006—2020", "clauseNo": "D2.1"},
            "TSG D7006—2020 第 D2.1 条",
        ),
        (
            {"standardCode": "TSG 31—2025", "clauseNo": "3.1.1-3.1.2"},
            "TSG 31—2025 第 3.1.1～3.1.2 条",
        ),
        (
            {"standardCode": "TSG 07—2019", "clauseNo": "E1.1、E1.2.2"},
            "TSG 07—2019 第 E1.1、E1.2.2 条",
        ),
        (
            {
                "standardCode": "市场监管总局公告2021年第41号",
                "clauseNo": "附件1：特种设备生产单位许可目录",
            },
            "市场监管总局公告 2021 年第 41 号 附件 1",
        ),
    ]

    assert [routes_module.review_basis_display_label(item) for item, _ in cases] == [
        expected for _, expected in cases
    ]


def test_review_b_workspace_exposes_review_run_human_task_and_audit_view() -> None:
    review_run_id = "RRUN-REVIEW-B-001"
    repo.state["review_runs"].insert(
        0,
        {
            "id": review_run_id,
            "reviewRunId": review_run_id,
            "projectId": PROJECT_ID,
            "nodeId": NODE_ID,
            "status": "waiting_human_input",
            "currentStep": "wait_for_human",
            "ruleVersion": "R01-v1",
            "revision": 1,
            "humanInputTasks": [
                {
                    "taskId": "HIT-REVIEW-B-001",
                    "taskType": "official_registry_license_verification",
                    "nodeId": NODE_ID,
                    "title": "人工核验许可证",
                    "description": "查询权威登记信息",
                    "status": "pending",
                    "required": True,
                    "inputHash": "sha256:review-b-task",
                    "createdAt": "2026-07-18 10:00:00",
                    "updatedAt": "2026-07-18 10:00:00",
                }
            ],
            "findingDrafts": [],
            "createdAt": "2026-07-18 10:00:00",
        },
    )

    workspace = assert_ok(
        client.get(
            f"/api/projects/{PROJECT_ID}/inspection/nodes/{NODE_ID}/review-workspace",
            params={"reviewRunId": review_run_id},
            headers=HEADERS,
        )
    )
    audit = assert_ok(
        client.get(f"/api/review-runs/{review_run_id}/audit-view", headers=HEADERS)
    )

    assert workspace["activeReviewRun"]["reviewRunId"] == review_run_id
    assert workspace["contextSummary"]["processTodoCount"] == 1
    assert workspace["permissions"]["canSubmitHumanInput"] is True
    assert workspace["permissions"]["canSubmitHumanDecision"] is False
    assert audit["reviewRun"]["reviewRunId"] == review_run_id
    assert audit["activeHumanInputTask"]["taskId"] == "HIT-REVIEW-B-001"


def _wait_for_assistant_completion(
    session_id: str, message_id: str, timeout_seconds: float = 8.0
) -> dict:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        payload = assert_ok(
            client.get(f"/api/review-sessions/{session_id}/messages", headers=HEADERS)
        )
        message = next(
            (item for item in payload["messages"] if item["id"] == message_id), None
        )
        if message and message.get("status") != "running":
            return message
        time.sleep(0.05)
    raise AssertionError("assistant message did not finalize in time")


def test_review_b_background_execution_returns_running_placeholder(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_REVIEW_CONVERSATION_EXECUTION_MODE", "background")
    monkeypatch.setenv("AICHECK_REVIEW_CONVERSATION_LLM_EXECUTION", "litellm")

    class FakeQwenRuntime:
        def chat_sync(self, messages, model, **kwargs):
            return {
                "provider": "test-qwen",
                "model": "qwen-review-test",
                "choices": [{"message": {"content": "后台执行完成的最终结论。"}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 6},
            }

    monkeypatch.setattr(routes_module, "qwen_runtime_client", lambda: FakeQwenRuntime())
    session = create_session()
    response = assert_ok(
        client.post(
            f"/api/review-sessions/{session['id']}/messages",
            headers={
                **HEADERS,
                "Idempotency-Key": "review-b-async-accept-test",
                "If-Match": session["etag"],
            },
            json={"content": "请核查当前节点证据。"},
        )
    )
    assert response["status"] == "accepted"
    assert response["assistantMessage"]["status"] == "running"
    assert response["assistantMessage"]["execution"]["mode"] == "llm_agent"

    finalized = _wait_for_assistant_completion(
        session["id"], response["assistantMessage"]["id"]
    )
    assert finalized["status"] == "completed"
    assert finalized["execution"]["mode"] == "llm_agent"
    assert any(
        "最终结论" in str(block.get("text") or "") for block in finalized["contentBlocks"]
    )
    # 完成后重新分配 sequence，保证增量拉取（sequence > after）能看到最终内容。
    assert finalized["sequence"] > response["assistantMessage"]["sequence"]

    event_types = {
        item["eventType"]
        for item in assert_ok(
            client.get(f"/api/review-sessions/{session['id']}/events", headers=HEADERS)
        )["events"]
    }
    assert "agent.execution.accepted" in event_types
    assert "agent.message.completed" in event_types


def test_review_b_second_message_rejected_while_execution_active(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_REVIEW_CONVERSATION_EXECUTION_MODE", "background")
    monkeypatch.setenv("AICHECK_REVIEW_CONVERSATION_LLM_EXECUTION", "litellm")
    release = threading.Event()

    class BlockingQwenRuntime:
        def chat_sync(self, messages, model, **kwargs):
            release.wait(timeout=5)
            return {
                "provider": "test-qwen",
                "model": "qwen-review-test",
                "choices": [{"message": {"content": "执行完成。"}}],
            }

    monkeypatch.setattr(
        routes_module, "qwen_runtime_client", lambda: BlockingQwenRuntime()
    )
    session = create_session()
    accepted = assert_ok(
        client.post(
            f"/api/review-sessions/{session['id']}/messages",
            headers={
                **HEADERS,
                "Idempotency-Key": "review-b-busy-first",
                "If-Match": session["etag"],
            },
            json={"content": "整体核查当前节点。"},
        )
    )
    assert accepted["status"] == "accepted"

    busy = client.post(
        f"/api/review-sessions/{session['id']}/messages",
        headers={
            **HEADERS,
            "Idempotency-Key": "review-b-busy-second",
            "If-Match": accepted["session"]["etag"],
        },
        json={"content": "再问一个问题。"},
    )
    assert busy.status_code == 409
    assert busy.json()["code"] != 0

    release.set()
    _wait_for_assistant_completion(session["id"], accepted["assistantMessage"]["id"])


def test_review_b_cancel_action_stops_background_execution(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_REVIEW_CONVERSATION_EXECUTION_MODE", "background")
    monkeypatch.setenv("AICHECK_REVIEW_CONVERSATION_LLM_EXECUTION", "litellm")
    release = threading.Event()

    class SlowToolLoopRuntime:
        def chat_sync(self, messages, model, **kwargs):
            release.wait(timeout=5)
            return {
                "provider": "test-qwen",
                "model": "qwen-review-test",
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call-cancel-1",
                                    "function": {
                                        "name": "get_review_context",
                                        "arguments": "{}",
                                    },
                                }
                            ],
                        }
                    }
                ],
            }

    monkeypatch.setattr(
        routes_module, "qwen_runtime_client", lambda: SlowToolLoopRuntime()
    )
    session = create_session()
    accepted = assert_ok(
        client.post(
            f"/api/review-sessions/{session['id']}/messages",
            headers={
                **HEADERS,
                "Idempotency-Key": "review-b-cancel-first",
                "If-Match": session["etag"],
            },
            json={"content": "整体核查当前节点。"},
        )
    )
    assert accepted["status"] == "accepted"

    cancel = assert_ok(
        client.post(
            f"/api/review-sessions/{session['id']}/actions/cancel_execution",
            headers={**HEADERS, "Idempotency-Key": "review-b-cancel-action"},
            json={},
        )
    )
    assert cancel["cancelRequested"] is True
    release.set()

    finalized = _wait_for_assistant_completion(
        session["id"], accepted["assistantMessage"]["id"]
    )
    assert finalized["status"] == "cancelled"
    assert finalized["execution"]["mode"] == "cancelled"
    assert finalized["execution"]["failureReason"] == "USER_CANCELLED"

    event_types = {
        item["eventType"]
        for item in assert_ok(
            client.get(f"/api/review-sessions/{session['id']}/events", headers=HEADERS)
        )["events"]
    }
    assert "agent.execution.cancel_requested" in event_types
    assert "agent.execution.cancelled" in event_types


def test_review_b_cancel_action_without_active_execution_fails() -> None:
    session = create_session()
    response = client.post(
        f"/api/review-sessions/{session['id']}/actions/cancel_execution",
        headers={**HEADERS, "Idempotency-Key": "review-b-cancel-idle"},
        json={},
    )
    assert response.status_code != 200 or response.json()["code"] != 0


def test_review_b_natural_language_with_command_words_goes_to_agent(monkeypatch) -> None:
    """自然语言问题即使包含“补充证据/查看条款”字样，也不应被斜线命令劫持。"""

    class FakeQwenRuntime:
        def chat_sync(self, messages, model, **kwargs):
            return {
                "provider": "test-qwen",
                "model": "qwen-review-test",
                "choices": [{"message": {"content": "这是 Agent 的回答。"}}],
            }

    monkeypatch.setenv("AICHECK_REVIEW_CONVERSATION_LLM_EXECUTION", "litellm")
    monkeypatch.setattr(routes_module, "qwen_runtime_client", lambda: FakeQwenRuntime())
    session = create_session()
    response = assert_ok(
        client.post(
            f"/api/review-sessions/{session['id']}/messages",
            headers={
                **HEADERS,
                "Idempotency-Key": "review-b-slash-exact-test",
                "If-Match": session["etag"],
            },
            json={"content": "为什么不能补充证据？帮我查看条款相关的问题。"},
        )
    )
    assert response["assistantMessage"]["execution"]["mode"] == "llm_agent"
    text_blocks = [
        block["text"]
        for block in response["assistantMessage"]["contentBlocks"]
        if block["type"] == "text"
    ]
    assert text_blocks == ["这是 Agent 的回答。"]


def test_review_b_session_tool_memory_reuses_results_across_messages(monkeypatch) -> None:
    calls = {"count": 0}
    observed = {"previous_findings_in_context": False, "memory_notice_in_tool_result": False}

    class MemoryQwenRuntime:
        def chat_sync(self, messages, model, **kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                return {
                    "provider": "test-qwen",
                    "model": "qwen-review-test",
                    "choices": [
                        {
                            "message": {
                                "content": "",
                                "tool_calls": [
                                    {
                                        "id": "call-mem-1",
                                        "function": {
                                            "name": "get_review_context",
                                            "arguments": "{}",
                                        },
                                    }
                                ],
                            }
                        }
                    ],
                }
            if calls["count"] == 2:
                return {
                    "provider": "test-qwen",
                    "model": "qwen-review-test",
                    "choices": [{"message": {"content": "第一条消息的结论。"}}],
                }
            if calls["count"] == 3:
                observed["previous_findings_in_context"] = (
                    '"previousToolFindings"' in str(messages[1].get("content") or "")
                    and "get_review_context" in str(messages[1].get("content") or "")
                )
                return {
                    "provider": "test-qwen",
                    "model": "qwen-review-test",
                    "choices": [
                        {
                            "message": {
                                "content": "",
                                "tool_calls": [
                                    {
                                        "id": "call-mem-2",
                                        "function": {
                                            "name": "get_review_context",
                                            "arguments": "{}",
                                        },
                                    }
                                ],
                            }
                        }
                    ],
                }
            observed["memory_notice_in_tool_result"] = any(
                "fromSessionMemory" in str(item.get("content") or "")
                for item in messages
                if item.get("role") == "tool"
            )
            return {
                "provider": "test-qwen",
                "model": "qwen-review-test",
                "choices": [{"message": {"content": "第二条消息的结论。"}}],
            }

    monkeypatch.setenv("AICHECK_REVIEW_CONVERSATION_LLM_EXECUTION", "litellm")
    monkeypatch.setattr(routes_module, "qwen_runtime_client", lambda: MemoryQwenRuntime())
    session = create_session()
    first = assert_ok(
        client.post(
            f"/api/review-sessions/{session['id']}/messages",
            headers={
                **HEADERS,
                "Idempotency-Key": "review-b-memory-first",
                "If-Match": session["etag"],
            },
            json={"content": "请核对当前节点的规则与就绪状态。"},
        )
    )
    assert first["assistantMessage"]["execution"]["toolCallCount"] == 1
    second = assert_ok(
        client.post(
            f"/api/review-sessions/{session['id']}/messages",
            headers={
                **HEADERS,
                "Idempotency-Key": "review-b-memory-second",
                "If-Match": first["session"]["etag"],
            },
            json={"content": "再确认一次上下文情况。"},
        )
    )
    assert second["assistantMessage"]["execution"]["mode"] == "llm_agent"
    assert calls["count"] == 4
    assert observed["previous_findings_in_context"] is True
    assert observed["memory_notice_in_tool_result"] is True


def test_review_b_token_budget_forces_early_final_answer(monkeypatch) -> None:
    """初始上下文即超预算时，应发出 budget.exhausted 事件并在首轮强制收束。"""
    point = next(
        item
        for item in repo.state["admin_config"]["materialReviewPoints"]
        if int(item.get("nodeId") or 0) == NODE_ID
    )
    for index in range(12):
        repo.state["node_evidence_links"].append(
            {
                "id": f"NEL-BUDGET-{index:02d}",
                "projectId": PROJECT_ID,
                "nodeId": NODE_ID,
                "reviewPointId": point["id"],
                "documentId": f"DOC-BUDGET-{index:02d}",
                "documentVersionId": f"DV-BUDGET-{index:02d}",
                "fileName": f"预算测试证据{index:02d}.pdf",
                "manualStatus": "pending",
                "supportStatus": "命中",
                "confidence": 0.9,
                "source": "material_targeting",
                "pageNo": 1,
                "fieldName": "内容",
                "quotedText": "证" * 600,
                "formalEvidenceEligible": True,
                "evidenceTier": "formal",
            }
        )

    class BudgetQwenRuntime:
        def chat_sync(self, messages, model, **kwargs):
            assert kwargs.get("tool_choice") == "none"
            assert "Token 预算上限" in str(messages[-1].get("content") or "")
            assert '"contextTrimmed": true' in str(messages[1].get("content") or "")
            return {
                "provider": "test-qwen",
                "model": "qwen-review-test",
                "choices": [{"message": {"content": "预算受限下的最终结论。"}}],
            }

    monkeypatch.setenv("AICHECK_REVIEW_CONVERSATION_LLM_EXECUTION", "litellm")
    monkeypatch.setenv("AICHECK_REVIEW_CONVERSATION_INPUT_TOKEN_BUDGET", "4000")
    monkeypatch.setattr(routes_module, "qwen_runtime_client", lambda: BudgetQwenRuntime())
    session = create_session()
    response = assert_ok(
        client.post(
            f"/api/review-sessions/{session['id']}/messages",
            headers={
                **HEADERS,
                "Idempotency-Key": "review-b-budget-test",
                "If-Match": session["etag"],
            },
            json={"content": "请全面核查当前节点全部证据。"},
        )
    )
    execution = response["assistantMessage"]["execution"]
    assert execution["mode"] == "llm_agent"
    assert execution["turnCount"] == 1
    assert execution["toolCallCount"] == 0
    event_types = {
        item["eventType"]
        for item in assert_ok(
            client.get(f"/api/review-sessions/{session['id']}/events", headers=HEADERS)
        )["events"]
    }
    assert "agent.budget.exhausted" in event_types


def test_review_b_agent_executions_recorded_and_queryable(monkeypatch) -> None:
    class FakeQwenRuntime:
        def chat_sync(self, messages, model, **kwargs):
            return {
                "provider": "test-qwen",
                "model": "qwen-review-test",
                "choices": [{"message": {"content": "执行记录测试回答。"}}],
            }

    monkeypatch.setenv("AICHECK_REVIEW_CONVERSATION_LLM_EXECUTION", "litellm")
    monkeypatch.setattr(routes_module, "qwen_runtime_client", lambda: FakeQwenRuntime())
    session = create_session()

    # 斜线命令走确定性路径，不产生 Agent 执行记录。
    slash = assert_ok(
        client.post(
            f"/api/review-sessions/{session['id']}/messages",
            headers={
                **HEADERS,
                "Idempotency-Key": "review-b-exec-slash",
                "If-Match": session["etag"],
            },
            json={"content": "/标准条款"},
        )
    )
    assert slash["status"] == "completed"
    empty = assert_ok(
        client.get(
            f"/api/review-sessions/{session['id']}/agent-executions", headers=HEADERS
        )
    )
    assert empty["executions"] == []

    free_form = assert_ok(
        client.post(
            f"/api/review-sessions/{session['id']}/messages",
            headers={
                **HEADERS,
                "Idempotency-Key": "review-b-exec-agent",
                "If-Match": slash["session"]["etag"],
            },
            json={"content": "请核查当前节点。"},
        )
    )
    executions = assert_ok(
        client.get(
            f"/api/review-sessions/{session['id']}/agent-executions", headers=HEADERS
        )
    )["executions"]
    assert len(executions) == 1
    record = executions[0]
    assert record["status"] == "completed"
    assert record["executionMode"] == "inline"
    assert record["assistantMessageId"] == free_form["assistantMessage"]["id"]
    assert record["turnCount"] >= 1
    assert record["finishedAt"]


def test_review_b_content_delta_events_are_emitted(monkeypatch) -> None:
    calls = {"count": 0}

    class DeltaQwenRuntime:
        def chat_sync(self, messages, model, **kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                return {
                    "provider": "test-qwen",
                    "model": "qwen-review-test",
                    "choices": [
                        {
                            "message": {
                                "content": "初步说明：我先核对当前上下文。",
                                "reasoning_content": "需要先读取节点上下文再判断。",
                                "tool_calls": [
                                    {
                                        "id": "call-delta-1",
                                        "function": {
                                            "name": "get_review_context",
                                            "arguments": "{}",
                                        },
                                    }
                                ],
                            }
                        }
                    ],
                }
            return {
                "provider": "test-qwen",
                "model": "qwen-review-test",
                "choices": [{"message": {"content": "最终结论：证据不足，需人工确认。"}}],
            }

    monkeypatch.setenv("AICHECK_REVIEW_CONVERSATION_LLM_EXECUTION", "litellm")
    monkeypatch.setattr(routes_module, "qwen_runtime_client", lambda: DeltaQwenRuntime())
    session = create_session()
    assert_ok(
        client.post(
            f"/api/review-sessions/{session['id']}/messages",
            headers={
                **HEADERS,
                "Idempotency-Key": "review-b-delta-test",
                "If-Match": session["etag"],
            },
            json={"content": "请核查当前节点证据情况。"},
        )
    )
    events = assert_ok(
        client.get(f"/api/review-sessions/{session['id']}/events", headers=HEADERS)
    )["events"]
    message_deltas = [
        item for item in events if item["eventType"] == "agent.message.delta"
    ]
    reasoning_deltas = [
        item for item in events if item["eventType"] == "agent.reasoning.delta"
    ]
    assert any("初步说明" in str(item["payload"].get("content") or "") for item in message_deltas)
    assert any("最终结论" in str(item["payload"].get("content") or "") for item in message_deltas)
    assert any(
        "节点上下文" in str(item["payload"].get("content") or "") for item in reasoning_deltas
    )
    assert all(item["payload"].get("executionId") for item in message_deltas)


def test_review_b_single_tool_failure_does_not_kill_answer(monkeypatch) -> None:
    """单工具错误隔离：工具抛异常应转为结构化失败结果回馈模型，回答仍完成。"""
    calls = {"count": 0}
    observed = {"failed_tool_result_in_context": False}

    class ToolFailureRuntime:
        def chat_sync(self, messages, model, **kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                return {
                    "provider": "test-qwen",
                    "model": "qwen-review-test",
                    "choices": [
                        {
                            "message": {
                                "content": "",
                                "tool_calls": [
                                    {
                                        "id": "call-fail-1",
                                        "function": {
                                            "name": "get_review_context",
                                            "arguments": "{}",
                                        },
                                    }
                                ],
                            }
                        }
                    ],
                }
            observed["failed_tool_result_in_context"] = any(
                '"status": "failed"' in str(item.get("content") or "")
                or '"failed"' in str(item.get("content") or "")
                for item in messages
                if item.get("role") == "tool"
            )
            return {
                "provider": "test-qwen",
                "model": "qwen-review-test",
                "choices": [{"message": {"content": "尽管工具失败，仍给出结论：证据不足。"}}],
            }

    def broken_tool_output(tool_name, arguments, **kwargs):
        raise RuntimeError("tool exploded")

    monkeypatch.setenv("AICHECK_REVIEW_CONVERSATION_LLM_EXECUTION", "litellm")
    monkeypatch.setattr(routes_module, "qwen_runtime_client", lambda: ToolFailureRuntime())
    monkeypatch.setattr(
        routes_module, "review_conversation_agent_tool_output", broken_tool_output
    )
    session = create_session()
    response = assert_ok(
        client.post(
            f"/api/review-sessions/{session['id']}/messages",
            headers={
                **HEADERS,
                "Idempotency-Key": "review-b-tool-isolation",
                "If-Match": session["etag"],
            },
            json={"content": "请核查当前节点。"},
        )
    )
    execution = response["assistantMessage"]["execution"]
    assert execution["mode"] == "llm_agent"
    assert execution["toolCallCount"] == 1
    assert observed["failed_tool_result_in_context"] is True
    events = assert_ok(
        client.get(f"/api/review-sessions/{session['id']}/events", headers=HEADERS)
    )["events"]
    failed_tool_events = [
        item
        for item in events
        if item["eventType"] == "agent.tool_call.completed"
        and item["payload"].get("status") == "failed"
    ]
    assert failed_tool_events


def test_review_b_model_timeout_retries_once(monkeypatch) -> None:
    from libs.integrations.errors import IntegrationServiceError

    calls = {"count": 0}

    class FlakyRuntime:
        def chat_sync(self, messages, model, **kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                raise IntegrationServiceError(
                    "QwenRuntime", "chat.completions", reason="TIMEOUTEXCEPTION"
                )
            return {
                "provider": "test-qwen",
                "model": "qwen-review-test",
                "choices": [{"message": {"content": "重试后成功的回答。"}}],
            }

    monkeypatch.setenv("AICHECK_REVIEW_CONVERSATION_LLM_EXECUTION", "litellm")
    monkeypatch.setattr(routes_module, "qwen_runtime_client", lambda: FlakyRuntime())
    session = create_session()
    response = assert_ok(
        client.post(
            f"/api/review-sessions/{session['id']}/messages",
            headers={
                **HEADERS,
                "Idempotency-Key": "review-b-model-retry",
                "If-Match": session["etag"],
            },
            json={"content": "请核查当前节点。"},
        )
    )
    execution = response["assistantMessage"]["execution"]
    assert execution["mode"] == "llm_agent"
    assert execution["turnCount"] == 1
    assert calls["count"] == 2
    event_types = {
        item["eventType"]
        for item in assert_ok(
            client.get(f"/api/review-sessions/{session['id']}/events", headers=HEADERS)
        )["events"]
    }
    assert "agent.model_call.retried" in event_types


def test_review_b_streamed_deltas_replace_per_turn_emission(monkeypatch) -> None:
    """串流模式：stream_handler 片段缓冲后发出 streamed delta，且不再重复发整轮 delta。"""

    class StreamingRuntime:
        def chat_sync(self, messages, model, **kwargs):
            handler = kwargs.get("stream_handler")
            assert handler is not None, "首次尝试应携带 stream_handler"
            handler("content", "第一段")
            handler("content", "第二段结论完成。")
            return {
                "provider": "test-qwen",
                "model": "qwen-review-test",
                "choices": [{"message": {"content": "第一段第二段结论完成。"}}],
            }

    monkeypatch.setenv("AICHECK_REVIEW_CONVERSATION_LLM_EXECUTION", "litellm")
    monkeypatch.setattr(routes_module, "qwen_runtime_client", lambda: StreamingRuntime())
    session = create_session()
    response = assert_ok(
        client.post(
            f"/api/review-sessions/{session['id']}/messages",
            headers={
                **HEADERS,
                "Idempotency-Key": "review-b-streamed-delta",
                "If-Match": session["etag"],
            },
            json={"content": "请核查当前节点。"},
        )
    )
    assert response["assistantMessage"]["execution"]["mode"] == "llm_agent"
    message_deltas = [
        item
        for item in assert_ok(
            client.get(f"/api/review-sessions/{session['id']}/events", headers=HEADERS)
        )["events"]
        if item["eventType"] == "agent.message.delta"
    ]
    assert len(message_deltas) == 1
    assert message_deltas[0]["payload"].get("streamed") is True
    assert message_deltas[0]["payload"].get("content") == "第一段第二段结论完成。"


def test_review_b_celery_mode_falls_back_to_thread_when_dispatch_disabled(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_REVIEW_CONVERSATION_EXECUTION_MODE", "celery")
    monkeypatch.setenv("AICHECK_REVIEW_CONVERSATION_LLM_EXECUTION", "litellm")
    monkeypatch.delenv("AICHECK_TASK_DISPATCH", raising=False)

    class FakeQwenRuntime:
        def chat_sync(self, messages, model, **kwargs):
            return {
                "provider": "test-qwen",
                "model": "qwen-review-test",
                "choices": [{"message": {"content": "Celery 回退路径的回答。"}}],
            }

    monkeypatch.setattr(routes_module, "qwen_runtime_client", lambda: FakeQwenRuntime())
    session = create_session()
    accepted = assert_ok(
        client.post(
            f"/api/review-sessions/{session['id']}/messages",
            headers={
                **HEADERS,
                "Idempotency-Key": "review-b-celery-fallback",
                "If-Match": session["etag"],
            },
            json={"content": "请核查当前节点。"},
        )
    )
    assert accepted["status"] == "accepted"
    finalized = _wait_for_assistant_completion(
        session["id"], accepted["assistantMessage"]["id"]
    )
    assert finalized["status"] == "completed"
    event_types = {
        item["eventType"]
        for item in assert_ok(
            client.get(f"/api/review-sessions/{session['id']}/events", headers=HEADERS)
        )["events"]
    }
    assert "agent.execution.dispatch_failed" in event_types
    assert "agent.message.completed" in event_types
    executions = assert_ok(
        client.get(
            f"/api/review-sessions/{session['id']}/agent-executions", headers=HEADERS
        )
    )["executions"]
    assert executions[0]["status"] == "completed"
    assert executions[0]["heartbeatAt"]
    assert executions[0]["heartbeatEpoch"] > 0


def test_review_b_episodic_memory_injected_with_guardrails(monkeypatch) -> None:
    """跨会话情节记忆：历史人工裁定与历史 AI 结论应注入上下文，且系统提示带防锚定护栏。"""
    repo.state["review_runs"].insert(
        0,
        {
            "reviewRunId": "RRUN-EPISODIC-1",
            "projectId": PROJECT_ID,
            "nodeId": NODE_ID,
            "status": "已完成",
            "currentStep": "done",
            "findingDrafts": [],
            "humanDecision": {
                "decision": "accept",
                "comment": "历史裁定：设计许可证覆盖完整施工周期，符合要求。",
                "decidedAt": "2026-07-20 10:00:00",
            },
            "createdAt": "2026-07-20 09:00:00",
            "updatedAt": "2026-07-20 10:00:00",
        },
    )
    repo.state.setdefault("review_opinions", []).insert(
        0,
        {
            "id": "RO-EPISODIC-1",
            "projectId": PROJECT_ID,
            "nodeId": NODE_ID,
            "result": "满足要求",
            "opinion": "上次人工复核意见：证据链完整。",
            "createdAt": "2026-07-21 08:00:00",
        },
    )
    observed = {}

    class FakeQwenRuntime:
        def chat_sync(self, messages, model, **kwargs):
            context_text = str(messages[-1].get("content") or "")
            system_text = str(messages[0].get("content") or "")
            observed["has_episodic"] = '"episodicMemory"' in context_text
            observed["has_human_decision"] = "历史裁定：设计许可证覆盖完整施工周期" in context_text
            observed["has_opinion"] = "上次人工复核意见" in context_text
            observed["has_prior_run"] = '"prior_ai_run_unverified"' in context_text
            observed["guardrail"] = "不得直接照抄" in system_text
            return {
                "provider": "test-qwen",
                "model": "qwen-review-test",
                "choices": [{"message": {"content": "结合历史裁定与当前证据的回答。"}}],
            }

    monkeypatch.setenv("AICHECK_REVIEW_CONVERSATION_LLM_EXECUTION", "litellm")
    monkeypatch.setattr(routes_module, "qwen_runtime_client", lambda: FakeQwenRuntime())
    session = create_session()
    response = assert_ok(
        client.post(
            f"/api/review-sessions/{session['id']}/messages",
            headers={
                **HEADERS,
                "Idempotency-Key": "review-b-episodic-test",
                "If-Match": session["etag"],
            },
            json={"content": "这个节点之前是怎么判的？现在还符合吗？"},
        )
    )
    assert response["assistantMessage"]["execution"]["mode"] == "llm_agent"
    assert observed == {
        "has_episodic": True,
        "has_human_decision": True,
        "has_opinion": True,
        "has_prior_run": True,
        "guardrail": True,
    }, observed


def test_review_b_tool_memory_entries_are_tenant_scoped(monkeypatch) -> None:
    """记忆条目携带 tenantId；读取侧按会话租户过滤，跨租户条目不可见。"""

    class FakeQwenRuntime:
        def __init__(self) -> None:
            self.calls = 0

        def chat_sync(self, messages, model, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return {
                    "provider": "test-qwen",
                    "model": "qwen-review-test",
                    "choices": [
                        {
                            "message": {
                                "content": "",
                                "tool_calls": [
                                    {
                                        "id": "call-tenant-1",
                                        "function": {
                                            "name": "get_review_context",
                                            "arguments": "{}",
                                        },
                                    }
                                ],
                            }
                        }
                    ],
                }
            return {
                "provider": "test-qwen",
                "model": "qwen-review-test",
                "choices": [{"message": {"content": "已核对上下文。"}}],
            }

    monkeypatch.setenv("AICHECK_REVIEW_CONVERSATION_LLM_EXECUTION", "litellm")
    monkeypatch.setattr(routes_module, "qwen_runtime_client", lambda: FakeQwenRuntime())
    session = create_session()
    assert_ok(
        client.post(
            f"/api/review-sessions/{session['id']}/messages",
            headers={
                **HEADERS,
                "Idempotency-Key": "review-b-tenant-memory-test",
                "If-Match": session["etag"],
            },
            json={"content": "请核对当前节点上下文。"},
        )
    )
    entries = [
        item
        for item in repo.state["review_session_tool_memory"]
        if item.get("sessionId") == session["id"]
    ]
    assert entries and "tenantId" in entries[0], entries[:1]
    session_record = repo.find_one("review_sessions", session["id"])
    loaded = routes_module.load_review_session_tool_memory(session_record)
    assert loaded, "memory should be visible for the same tenant"
    for item in entries:
        item["tenantId"] = "TENANT-OTHER"
    assert routes_module.load_review_session_tool_memory(session_record) == {}


def test_review_b_memory_fine_grained_invalidation(monkeypatch) -> None:
    """上下文动作只失效依赖变化范围的记忆：纯函数工具结果跨动作存活。"""
    calls = {"n": 0}
    CHECK_ARGS = '{"validUntil": "2027-01-01", "periodStart": "2026-01-01", "periodEnd": "2026-12-31"}'

    class TwoToolRuntime:
        def chat_sync(self, messages, model, **kwargs):
            calls["n"] += 1
            if calls["n"] in (1, 3):
                return {
                    "provider": "test-qwen",
                    "model": "qwen-review-test",
                    "choices": [
                        {
                            "message": {
                                "content": "",
                                "tool_calls": [
                                    {
                                        "id": f"c-check-{calls['n']}",
                                        "function": {
                                            "name": "check_date_covers",
                                            "arguments": CHECK_ARGS,
                                        },
                                    },
                                    {
                                        "id": f"c-ctx-{calls['n']}",
                                        "function": {
                                            "name": "get_review_context",
                                            "arguments": "{}",
                                        },
                                    },
                                ],
                            }
                        }
                    ],
                }
            return {
                "provider": "test-qwen",
                "model": "qwen-review-test",
                "choices": [{"message": {"content": f"结论 {calls['n']}"}}],
            }

    monkeypatch.setenv("AICHECK_REVIEW_CONVERSATION_LLM_EXECUTION", "litellm")
    monkeypatch.setattr(routes_module, "qwen_runtime_client", lambda: TwoToolRuntime())
    session = create_session()
    first = assert_ok(
        client.post(
            f"/api/review-sessions/{session['id']}/messages",
            headers={
                **HEADERS,
                "Idempotency-Key": "review-b-finegrain-msg1",
                "If-Match": session["etag"],
            },
            json={"content": "请核查有效期覆盖并读取上下文。"},
        )
    )
    entries = [
        item
        for item in repo.state["review_session_tool_memory"]
        if item.get("sessionId") == session["id"]
    ]
    assert {item["toolName"] for item in entries} == {"check_date_covers", "get_review_context"}
    check_entry = next(item for item in entries if item["toolName"] == "check_date_covers")
    context_entry = next(item for item in entries if item["toolName"] == "get_review_context")
    assert check_entry["dependsOn"] == []
    assert "__session_context__" in context_entry["dependsOn"]

    acted = assert_ok(
        client.post(
            f"/api/review-sessions/{session['id']}/actions/set_current_task",
            headers={
                **HEADERS,
                "Idempotency-Key": "review-b-finegrain-action",
                "If-Match": first["session"]["etag"],
            },
            json={"currentTask": "改核对焊工资格"},
        )
    )
    remaining = [
        item["toolName"]
        for item in repo.state["review_session_tool_memory"]
        if item.get("sessionId") == session["id"]
    ]
    assert remaining == ["check_date_covers"], remaining
    invalidated_events = [
        item
        for item in assert_ok(
            client.get(f"/api/review-sessions/{session['id']}/events", headers=HEADERS)
        )["events"]
        if item["eventType"] == "session.memory.invalidated"
    ]
    assert invalidated_events and invalidated_events[-1]["payload"]["invalidatedCount"] == 1
    assert "__session_context__" in invalidated_events[-1]["payload"]["scopes"]

    assert_ok(
        client.post(
            f"/api/review-sessions/{session['id']}/messages",
            headers={
                **HEADERS,
                "Idempotency-Key": "review-b-finegrain-msg2",
                "If-Match": acted["session"]["etag"],
            },
            json={"content": "再核查一次有效期覆盖与上下文。"},
        )
    )
    completed = [
        item["payload"].get("duplicate")
        for item in assert_ok(
            client.get(f"/api/review-sessions/{session['id']}/events", headers=HEADERS)
        )["events"]
        if item["eventType"] == "agent.tool_call.completed"
    ]
    # msg1 两次 fresh；msg2 中纯函数工具命中记忆（True）、上下文工具因失效需重新执行（False）
    assert completed[-2:] == [True, False], completed


def test_review_b_conversation_digest_rolls_and_carries_gaps(monkeypatch) -> None:
    """滚动会话摘要：逐轮记录问题/结论/工具/证据缺口，随会话持久化并注入后续上下文。"""
    calls = {"n": 0, "digest_in_context": False, "gap_carried": False}

    class DigestRuntime:
        def chat_sync(self, messages, model, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                return {
                    "provider": "test-qwen",
                    "model": "qwen-review-test",
                    "choices": [
                        {
                            "message": {
                                "content": "",
                                "tool_calls": [
                                    {
                                        "id": "c-digest-1",
                                        "function": {
                                            "name": "get_review_context",
                                            "arguments": "{}",
                                        },
                                    }
                                ],
                            }
                        }
                    ],
                }
            if calls["n"] == 2:
                return {
                    "provider": "test-qwen",
                    "model": "qwen-review-test",
                    "choices": [
                        {
                            "message": {
                                "content": "初步结论：许可范围符合。\n证据不足：缺少施工进度计划，无法确认有效期覆盖。"
                            }
                        }
                    ],
                }
            context_text = str(messages[-1].get("content") or "")
            calls["digest_in_context"] = '"conversationDigest"' in context_text
            calls["gap_carried"] = "缺少施工进度计划" in context_text
            return {
                "provider": "test-qwen",
                "model": "qwen-review-test",
                "choices": [{"message": {"content": "已承接前述缺口继续核查。"}}],
            }

    monkeypatch.setenv("AICHECK_REVIEW_CONVERSATION_LLM_EXECUTION", "litellm")
    monkeypatch.setattr(routes_module, "qwen_runtime_client", lambda: DigestRuntime())
    session = create_session()
    first = assert_ok(
        client.post(
            f"/api/review-sessions/{session['id']}/messages",
            headers={
                **HEADERS,
                "Idempotency-Key": "review-b-digest-msg1",
                "If-Match": session["etag"],
            },
            json={"content": "请核查许可范围与有效期覆盖。"},
        )
    )
    session_record = repo.find_one("review_sessions", session["id"])
    digest = session_record.get("conversationDigest")
    assert digest and len(digest["exchanges"]) == 1, digest
    exchange = digest["exchanges"][0]
    assert exchange["question"].startswith("请核查许可范围")
    assert exchange["answerSummary"].startswith("初步结论")
    assert exchange["toolsUsed"] == ["get_review_context"]
    assert any("缺少施工进度计划" in gap for gap in digest["gaps"]), digest["gaps"]

    slash = assert_ok(
        client.post(
            f"/api/review-sessions/{session['id']}/messages",
            headers={
                **HEADERS,
                "Idempotency-Key": "review-b-digest-slash",
                "If-Match": first["session"]["etag"],
            },
            json={"content": "/标准条款"},
        )
    )
    digest = repo.find_one("review_sessions", session["id"])["conversationDigest"]
    assert len(digest["exchanges"]) == 2
    assert digest["exchanges"][-1]["mode"] == "deterministic_command"

    assert_ok(
        client.post(
            f"/api/review-sessions/{session['id']}/messages",
            headers={
                **HEADERS,
                "Idempotency-Key": "review-b-digest-msg3",
                "If-Match": slash["session"]["etag"],
            },
            json={"content": "上面提到的缺口现在怎么处理？"},
        )
    )
    assert calls["digest_in_context"] is True
    assert calls["gap_carried"] is True
    digest = repo.find_one("review_sessions", session["id"])["conversationDigest"]
    assert len(digest["exchanges"]) == 3


def test_review_b_fact_ledger_dedup_conflict_and_invalidation(monkeypatch) -> None:
    """事实台账：跨工具事实级去重（佐证累计）、同属性冲突标记与事件、依赖失效。"""
    point = next(
        item
        for item in repo.state["admin_config"]["materialReviewPoints"]
        if int(item.get("nodeId") or 0) == NODE_ID
    )
    repo.state["node_evidence_links"].append(
        {
            "id": "NEL-FACT-1",
            "projectId": PROJECT_ID,
            "nodeId": NODE_ID,
            "reviewPointId": point["id"],
            "documentId": "DOC-FACT-1",
            "documentVersionId": "DV-FACT-1",
            "fileName": "安装单位许可证.pdf",
            "manualStatus": "pending",
            "supportStatus": "命中",
            "confidence": 0.9,
            "source": "material_targeting",
            "pageNo": 1,
            "fieldName": "单位名称",
            "quotedText": "某某安装公司",
            "formalEvidenceEligible": True,
            "evidenceTier": "formal",
        }
    )
    calls = {"n": 0, "ledger_in_context": False, "conflict_in_context": False}
    TOOL_OUTPUTS = {
        "extract_structured_fields": {
            "status": "succeeded",
            "fields": [
                {
                    "fieldCode": "unitName",
                    "fieldValue": "某某安装公司",
                    "pageNo": 1,
                    "documentVersionId": "DV-FACT-1",
                }
            ],
        },
        "get_document_ocr_result": {
            "status": "succeeded",
            "fields": [
                {"code": "unitName", "value": "某某安装公司", "documentVersionId": "DV-FACT-1"}
            ],
        },
        "extract_document_fields": {
            "status": "succeeded",
            "fields": [
                {"code": "unitName", "value": "另一安装公司", "documentVersionId": "DV-FACT-1"}
            ],
        },
    }

    def fake_tool_output(tool_name, arguments, **kwargs):
        return repo.clone(TOOL_OUTPUTS[tool_name])

    class FactRuntime:
        def chat_sync(self, messages, model, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                return {
                    "provider": "test-qwen",
                    "model": "qwen-review-test",
                    "choices": [
                        {
                            "message": {
                                "content": "",
                                "tool_calls": [
                                    {
                                        "id": f"cf-{index}",
                                        "function": {
                                            "name": name,
                                            "arguments": '{"documentVersionIds": ["DV-FACT-1"]}',
                                        },
                                    }
                                    for index, name in enumerate(TOOL_OUTPUTS)
                                ],
                            }
                        }
                    ],
                }
            if calls["n"] == 3:
                context_text = str(messages[-1].get("content") or "")
                calls["ledger_in_context"] = (
                    '"factLedger"' in context_text and "某某安装公司" in context_text
                )
                calls["conflict_in_context"] = '"conflict": true' in context_text
            return {
                "provider": "test-qwen",
                "model": "qwen-review-test",
                "choices": [{"message": {"content": f"结论 {calls['n']}"}}],
            }

    monkeypatch.setenv("AICHECK_REVIEW_CONVERSATION_LLM_EXECUTION", "litellm")
    monkeypatch.setattr(routes_module, "qwen_runtime_client", lambda: FactRuntime())
    monkeypatch.setattr(routes_module, "review_conversation_agent_tool_output", fake_tool_output)
    session = create_session()
    first = assert_ok(
        client.post(
            f"/api/review-sessions/{session['id']}/messages",
            headers={
                **HEADERS,
                "Idempotency-Key": "review-b-fact-msg1",
                "If-Match": session["etag"],
            },
            json={"content": "请提取安装单位名称。"},
        )
    )
    facts = [
        item
        for item in repo.state["review_session_facts"]
        if item.get("sessionId") == session["id"]
    ]
    assert len(facts) == 2, facts
    corroborated = next(item for item in facts if item["value"] == "某某安装公司")
    conflicting = next(item for item in facts if item["value"] == "另一安装公司")
    assert corroborated["corroborationCount"] == 2
    assert set(corroborated["sources"]) == {"extract_structured_fields", "get_document_ocr_result"}
    assert corroborated["conflict"] is True and conflicting["conflict"] is True
    assert "DV-FACT-1" in corroborated["dependsOn"]
    conflict_events = [
        item
        for item in assert_ok(
            client.get(f"/api/review-sessions/{session['id']}/events", headers=HEADERS)
        )["events"]
        if item["eventType"] == "session.fact.conflict"
    ]
    assert conflict_events and conflict_events[-1]["payload"]["attribute"] == "unitName"

    second = assert_ok(
        client.post(
            f"/api/review-sessions/{session['id']}/messages",
            headers={
                **HEADERS,
                "Idempotency-Key": "review-b-fact-msg2",
                "If-Match": first["session"]["etag"],
            },
            json={"content": "单位名称核对结果如何？"},
        )
    )
    assert calls["ledger_in_context"] is True and calls["conflict_in_context"] is True

    acted = assert_ok(
        client.post(
            f"/api/review-sessions/{session['id']}/actions/select_evidence",
            headers={
                **HEADERS,
                "Idempotency-Key": "review-b-fact-action",
                "If-Match": second["session"]["etag"],
            },
            json={"evidenceLinkId": "NEL-FACT-1"},
        )
    )
    remaining = [
        item
        for item in repo.state["review_session_facts"]
        if item.get("sessionId") == session["id"]
    ]
    assert remaining == [], remaining
    invalidated = [
        item
        for item in assert_ok(
            client.get(f"/api/review-sessions/{session['id']}/events", headers=HEADERS)
        )["events"]
        if item["eventType"] == "session.memory.invalidated"
    ]
    assert invalidated and invalidated[-1]["payload"]["invalidatedFactCount"] == 2
    assert acted["session"]["id"] == session["id"]


def test_review_b_context_assembly_is_relevance_ranked(monkeypatch) -> None:
    """上下文组装按问题相关性选入：新近度排不进配额的相关证据应被相关性捞回。"""
    point = next(
        item
        for item in repo.state["admin_config"]["materialReviewPoints"]
        if int(item.get("nodeId") or 0) == NODE_ID
    )
    for index in range(30):
        repo.state["node_evidence_links"].append(
            {
                "id": f"NEL-RANK-{index:02d}",
                "projectId": PROJECT_ID,
                "nodeId": NODE_ID,
                "reviewPointId": point["id"],
                "documentId": f"DOC-RANK-{index:02d}",
                "documentVersionId": f"DV-RANK-{index:02d}",
                "fileName": f"无关文件{index:02d}.pdf",
                "manualStatus": "pending",
                "supportStatus": "命中",
                "confidence": 0.8,
                "source": "material_targeting",
                "pageNo": 1,
                "fieldName": "内容",
                "quotedText": "常规记录",
                "formalEvidenceEligible": True,
                "evidenceTier": "formal",
            }
        )
    # 目标证据放在候选列表最末：纯新近度截取必然排除，只有相关性排序能选入。
    repo.state["node_evidence_links"].append(
        {
            "id": "NEL-RANK-TARGET",
            "projectId": PROJECT_ID,
            "nodeId": NODE_ID,
            "reviewPointId": point["id"],
            "documentId": "DOC-RANK-TARGET",
            "documentVersionId": "DV-RANK-TARGET",
            "fileName": "焊工资格证书.pdf",
            "manualStatus": "pending",
            "supportStatus": "命中",
            "confidence": 0.95,
            "source": "material_targeting",
            "pageNo": 2,
            "fieldName": "资格代码",
            "quotedText": "焊工张三 资格代码 SMAW-6G",
            "formalEvidenceEligible": True,
            "evidenceTier": "formal",
        }
    )
    observed = {}

    class RankRuntime:
        def chat_sync(self, messages, model, **kwargs):
            context_text = str(messages[1].get("content") or "")
            observed["target_selected"] = "焊工张三" in context_text
            observed["truncated_flag"] = '"nodeEvidenceTruncated": true' in context_text
            return {
                "provider": "test-qwen",
                "model": "qwen-review-test",
                "choices": [{"message": {"content": "已按相关证据核查焊工资格。"}}],
            }

    monkeypatch.setenv("AICHECK_REVIEW_CONVERSATION_LLM_EXECUTION", "litellm")
    monkeypatch.setattr(routes_module, "qwen_runtime_client", lambda: RankRuntime())
    session = create_session()
    assert_ok(
        client.post(
            f"/api/review-sessions/{session['id']}/messages",
            headers={
                **HEADERS,
                "Idempotency-Key": "review-b-rank-test",
                "If-Match": session["etag"],
            },
            json={"content": "请核查焊工张三的资格证书是否覆盖 SMAW 工艺。"},
        )
    )
    assert observed == {"target_selected": True, "truncated_flag": True}, observed


def test_review_b_organization_lessons_lifecycle_and_governed_injection(monkeypatch) -> None:
    """治理化组织记忆：反馈蒸馏为 draft；仅 published 注入提示；角色门禁与幂等蒸馏。"""
    repo.state.setdefault("ai_feedback", []).extend(
        [
            {
                "id": "AFB-LESSON-1",
                "projectId": PROJECT_ID,
                "nodeId": NODE_ID,
                "feedbackType": "hallucination",
                "comment": "结论未引用任何证据定位",
            },
            {
                "id": "AFB-LESSON-2",
                "projectId": PROJECT_ID,
                "nodeId": NODE_ID,
                "feedbackType": "rejected_false_positive",
                "comment": "许可范围被误判为不符合",
            },
        ]
    )
    distilled = assert_ok(
        client.post(
            "/api/review-lessons/distill",
            headers={**HEADERS, "Idempotency-Key": "review-b-lesson-distill"},
            json={"nodeId": NODE_ID},
        )
    )
    assert distilled["createdCount"] == 2
    assert all(item["status"] == "draft" for item in distilled["lessons"])
    again = assert_ok(
        client.post(
            "/api/review-lessons/distill",
            headers={**HEADERS, "Idempotency-Key": "review-b-lesson-distill-2"},
            json={"nodeId": NODE_ID},
        )
    )
    assert again["createdCount"] == 0  # 幂等：同一反馈不重复蒸馏

    forbidden = client.post(
        "/api/review-lessons/distill",
        headers={"X-Role": "contractor", "X-User-Id": "USER-C", "Idempotency-Key": "review-b-lesson-forbidden"},
        json={},
    )
    assert forbidden.status_code == 403

    observed = {"draft_leaked": None, "published_injected": None, "governance_prompt": None}

    class LessonRuntime:
        def chat_sync(self, messages, model, **kwargs):
            context_text = str(messages[1].get("content") or "")
            system_text = str(messages[0].get("content") or "")
            observed["draft_leaked"] = "结论未引用任何证据定位" in context_text
            observed["published_injected"] = "许可范围被误判为不符合" in context_text
            observed["governance_prompt"] = "organizationLessons" in system_text
            return {
                "provider": "test-qwen",
                "model": "qwen-review-test",
                "choices": [{"message": {"content": "遵循已发布教训的回答。"}}],
            }

    monkeypatch.setenv("AICHECK_REVIEW_CONVERSATION_LLM_EXECUTION", "litellm")
    monkeypatch.setattr(routes_module, "qwen_runtime_client", lambda: LessonRuntime())
    session = create_session()
    first = assert_ok(
        client.post(
            f"/api/review-sessions/{session['id']}/messages",
            headers={
                **HEADERS,
                "Idempotency-Key": "review-b-lesson-msg1",
                "If-Match": session["etag"],
            },
            json={"content": "请核查当前节点。"},
        )
    )
    # 全部为 draft：任何教训都不得注入
    assert observed["draft_leaked"] is False and observed["published_injected"] is False

    false_positive_lesson = next(
        item for item in distilled["lessons"] if item["feedbackType"] == "rejected_false_positive"
    )
    published = assert_ok(
        client.post(
            f"/api/review-lessons/{false_positive_lesson['id']}/publish",
            headers={**HEADERS, "Idempotency-Key": "review-b-lesson-publish"},
        )
    )
    assert published["lesson"]["status"] == "published"
    assert published["lesson"]["approvedBy"] == "USER-INSPECTION-001"

    assert_ok(
        client.post(
            f"/api/review-sessions/{session['id']}/messages",
            headers={
                **HEADERS,
                "Idempotency-Key": "review-b-lesson-msg2",
                "If-Match": first["session"]["etag"],
            },
            json={"content": "再核查一次当前节点。"},
        )
    )
    # published 注入、draft 仍被隔离、系统提示带治理说明
    assert observed["published_injected"] is True
    assert observed["draft_leaked"] is False
    assert observed["governance_prompt"] is True

    listed = assert_ok(
        client.get("/api/review-lessons", params={"status": "draft"}, headers=HEADERS)
    )
    assert len(listed["lessons"]) == 1  # hallucination 教训仍为 draft
