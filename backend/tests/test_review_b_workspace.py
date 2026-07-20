from __future__ import annotations

from fastapi.testclient import TestClient

from apps.api import routes as routes_module
from apps.api.main import app
from libs.db.repository import repo


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
            json={"content": "/解释依据"},
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
        "usage": {"prompt_tokens": 120, "completion_tokens": 28},
    }

    events = assert_ok(
        client.get(f"/api/review-sessions/{session['id']}/events", headers=HEADERS)
    )["events"]
    assert "agent.model_call.completed" in {item["eventType"] for item in events}


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
            }
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
    assert execution["usage"] == {"prompt_tokens": 190, "completion_tokens": 34}

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
