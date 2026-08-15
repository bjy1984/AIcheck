from __future__ import annotations

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


@pytest.mark.parametrize(
    "run_status",
    [
        None,
        "queued",
        "running",
        "waiting_human_input",
        "waiting_human_review",
        "failed",
        "cancelled",
    ],
)
def test_review_b_node_conclusion_permission_is_independent_of_review_run(
    run_status,
) -> None:
    repo.state["review_runs"] = [
        item
        for item in repo.state["review_runs"]
        if item.get("projectId") != PROJECT_ID
        or int(item.get("nodeId") or 0) != NODE_ID
    ]
    if run_status:
        repo.state["review_runs"].insert(
            0,
            {
                "id": f"RRUN-DECOUPLE-{run_status}",
                "reviewRunId": f"RRUN-DECOUPLE-{run_status}",
                "projectId": PROJECT_ID,
                "nodeId": NODE_ID,
                "status": run_status,
                "revision": 1,
            },
        )

    workspace = assert_ok(
        client.get(
            f"/api/projects/{PROJECT_ID}/inspection/nodes/{NODE_ID}/review-workspace",
            headers=HEADERS,
        )
    )

    assert workspace["permissions"]["canSubmitReviewOpinion"] is True


def test_review_b_return_correction_projection_only_lists_submitted_bindings() -> None:
    repo.state["documents"].extend(
        [
            {
                "id": "DOC-RETURNABLE",
                "projectId": PROJECT_ID,
                "fileName": "已提交设计许可证.pdf",
                "materialTypeName": "设计单位许可证",
                "materialCategory": "设计文件",
            },
            {
                "id": "DOC-DRAFT",
                "projectId": PROJECT_ID,
                "fileName": "尚未提交资料.pdf",
                "materialTypeName": "设计人员证明",
                "materialCategory": "设计文件",
            },
        ]
    )
    repo.state["bindings"].extend(
        [
            {
                "id": "BIND-RETURNABLE",
                "projectId": PROJECT_ID,
                "nodeId": NODE_ID,
                "documentId": "DOC-RETURNABLE",
                "fileName": "已提交设计许可证.pdf",
                "bindingStatus": "已提交",
            },
            {
                "id": "BIND-DRAFT",
                "projectId": PROJECT_ID,
                "nodeId": NODE_ID,
                "documentId": "DOC-DRAFT",
                "fileName": "尚未提交资料.pdf",
                "bindingStatus": "草稿挂载",
            },
        ]
    )

    workspace = assert_ok(
        client.get(
            f"/api/projects/{PROJECT_ID}/inspection/nodes/{NODE_ID}/review-workspace",
            headers=HEADERS,
        )
    )

    assert workspace["permissions"]["canReturnCorrection"] is True
    assert workspace["returnableBindings"] == [
        {
            "id": "BIND-RETURNABLE",
            "documentId": "DOC-RETURNABLE",
            "fileName": "已提交设计许可证.pdf",
            "materialTypeName": "设计单位许可证",
            "materialCategory": "设计文件",
            "bindingStatus": "已提交",
        }
    ]


def test_review_b_return_correction_atomically_creates_opinion_and_todo() -> None:
    repo.state["documents"].append(
        {
            "id": "DOC-ATOMIC-RETURN",
            "projectId": PROJECT_ID,
            "fileName": "需修改的许可证.pdf",
            "materialCategory": "设计文件",
        }
    )
    repo.state["bindings"].append(
        {
            "id": "BIND-ATOMIC-RETURN",
            "projectId": PROJECT_ID,
            "nodeId": NODE_ID,
            "documentId": "DOC-ATOMIC-RETURN",
            "fileName": "需修改的许可证.pdf",
            "bindingStatus": "已提交",
        }
    )
    repo.state["submissions"].append(
        {
            "id": "SUB-ATOMIC-RETURN",
            "submissionId": "SUB-ATOMIC-RETURN",
            "projectId": PROJECT_ID,
            "bindingIds": ["BIND-ATOMIC-RETURN"],
            "withdrawnBindingIds": [],
            "submittedAt": "2026-08-14 10:00:00",
        }
    )
    run = {
        "id": "RRUN-ATOMIC-RETURN",
        "reviewRunId": "RRUN-ATOMIC-RETURN",
        "projectId": PROJECT_ID,
        "nodeId": NODE_ID,
        "status": "running",
        "revision": 1,
    }
    repo.state["review_runs"].insert(0, run)
    workspace = assert_ok(
        client.get(
            f"/api/projects/{PROJECT_ID}/inspection/nodes/{NODE_ID}/review-workspace",
            headers=HEADERS,
        )
    )
    before = {
        "opinions": len(repo.state["review_opinions"]),
        "rectifications": len(repo.state["rectifications"]),
        "todos": len(repo.state["todos"]),
        "audits": len(repo.state["audit_logs"]),
    }

    result = assert_ok(
        client.post(
            f"/api/projects/{PROJECT_ID}/inspection/nodes/{NODE_ID}/actions/return-correction",
            headers={
                **HEADERS,
                "If-Match": workspace["project"]["etag"],
                "Idempotency-Key": "review-b-atomic-return",
            },
            json={
                "mode": "return_correction",
                "reason": "许可证范围与项目不一致，请修改。",
                "opinion": "许可证范围与项目不一致，请修改。",
                "bindingIds": ["BIND-ATOMIC-RETURN"],
                "evidenceLinkIds": [],
            },
        )
    )

    assert result["rectificationType"] == "return_correction"
    assert result["opinion"]["result"] == "需补正"
    assert len(repo.state["review_opinions"]) == before["opinions"] + 1
    assert len(repo.state["rectifications"]) == before["rectifications"] + 1
    assert len(repo.state["todos"]) == before["todos"] + 1
    assert len(repo.state["audit_logs"]) == before["audits"] + 1
    assert repo.find_one("bindings", "BIND-ATOMIC-RETURN")["bindingStatus"] == "需补正"
    assert run["status"] == "running"
    assert "humanDecision" not in run

    repeated = assert_ok(
        client.post(
            f"/api/projects/{PROJECT_ID}/inspection/nodes/{NODE_ID}/actions/return-correction",
            headers={
                **HEADERS,
                "If-Match": workspace["project"]["etag"],
                "Idempotency-Key": "review-b-atomic-return",
            },
            json={
                "mode": "return_correction",
                "reason": "许可证范围与项目不一致，请修改。",
                "opinion": "许可证范围与项目不一致，请修改。",
                "bindingIds": ["BIND-ATOMIC-RETURN"],
                "evidenceLinkIds": [],
            },
        )
    )
    assert repeated["rectification"]["id"] == result["rectification"]["id"]
    assert len(repo.state["review_opinions"]) == before["opinions"] + 1
    assert len(repo.state["rectifications"]) == before["rectifications"] + 1
    assert len(repo.state["todos"]) == before["todos"] + 1
    assert len(repo.state["audit_logs"]) == before["audits"] + 1


def test_review_b_supplement_request_creates_task_without_binding(
    monkeypatch,
) -> None:
    original_readiness = routes_module.build_node_evidence_readiness

    def readiness_with_missing(*args, **kwargs):
        readiness = original_readiness(*args, **kwargs)
        readiness["missingRequirements"] = [
            {
                "id": "REQ-MISSING-DESIGN-LICENSE",
                "nodeId": NODE_ID,
                "name": "设计单位许可证",
                "requiredType": "必传",
                "materialTypeCode": "DESIGN_LICENSE",
                "responsibleParty": "施工单位",
                "matchedBindingCount": 0,
                "matchedFileNames": [],
                "fulfilled": False,
            }
        ]
        readiness["missingCount"] = 1
        return readiness

    monkeypatch.setattr(routes_module, "build_node_evidence_readiness", readiness_with_missing)
    workspace = assert_ok(
        client.get(
            f"/api/projects/{PROJECT_ID}/inspection/nodes/{NODE_ID}/review-workspace",
            headers=HEADERS,
        )
    )
    before_binding_count = len(repo.state["bindings"])

    result = assert_ok(
        client.post(
            f"/api/projects/{PROJECT_ID}/inspection/nodes/{NODE_ID}/actions/return-correction",
            headers={
                **HEADERS,
                "If-Match": workspace["project"]["etag"],
                "Idempotency-Key": "review-b-supplement-request",
            },
            json={
                "mode": "supplement_request",
                "reason": "请补充提交设计单位许可证。",
                "opinion": "缺少设计单位许可证，需补充后复核。",
                "bindingIds": [],
                "supplementRequirements": [
                    {
                        "id": "REQ-MISSING-DESIGN-LICENSE",
                        "source": "system",
                        "name": "设计单位许可证",
                    },
                    {
                        "id": "MANUAL-AUTHORIZATION",
                        "source": "manual",
                        "name": "项目负责人授权书",
                    }
                ],
            },
        )
    )

    assert result["rectificationType"] == "supplement_request"
    assert result["opinion"]["result"] == "需补正"
    assert result["rectification"]["supplementRequirements"][0]["id"] == (
        "REQ-MISSING-DESIGN-LICENSE"
    )
    assert result["rectification"]["supplementRequirements"][1] == {
        "id": "MANUAL-AUTHORIZATION",
        "source": "manual",
        "name": "项目负责人授权书",
        "note": None,
    }
    assert len(repo.state["bindings"]) == before_binding_count
    assert repo.state["todos"][0]["targetId"] == result["rectification"]["id"]


def test_review_b_empty_supplement_request_writes_nothing() -> None:
    workspace = assert_ok(
        client.get(
            f"/api/projects/{PROJECT_ID}/inspection/nodes/{NODE_ID}/review-workspace",
            headers=HEADERS,
        )
    )
    before = {
        key: len(repo.state[key])
        for key in ("review_opinions", "rectifications", "todos")
    }
    before_audit_count = len(repo.state["audit_logs"])

    response = client.post(
        f"/api/projects/{PROJECT_ID}/inspection/nodes/{NODE_ID}/actions/return-correction",
        headers={
            **HEADERS,
            "If-Match": workspace["project"]["etag"],
            "Idempotency-Key": "review-b-empty-supplement",
        },
        json={
            "mode": "supplement_request",
            "reason": "请补充资料。",
            "opinion": "请补充资料。",
            "bindingIds": [],
            "supplementRequirements": [],
        },
    )

    assert response.json()["code"] != 0
    assert {
        key: len(repo.state[key])
        for key in ("review_opinions", "rectifications", "todos")
    } == before
    assert len(repo.state["audit_logs"]) == before_audit_count + 1


def test_review_b_latest_human_decision_prefers_node_review_opinion() -> None:
    repo.state["review_runs"].insert(
        0,
        {
            "id": "RRUN-DECOUPLE-PRECEDENCE",
            "reviewRunId": "RRUN-DECOUPLE-PRECEDENCE",
            "projectId": PROJECT_ID,
            "nodeId": NODE_ID,
            "status": "accepted_by_human",
            "humanDecision": {"decision": "accept", "comment": "AI feedback only"},
            "revision": 1,
        },
    )
    opinion = {
        "id": "OPN-DECOUPLE",
        "projectId": PROJECT_ID,
        "nodeId": NODE_ID,
        "result": "证据不足",
        "opinion": "节点正式结论",
        "createdAt": "2026-08-14 12:00:00",
    }
    repo.state["review_opinions"].insert(0, opinion)

    workspace = assert_ok(
        client.get(
            f"/api/projects/{PROJECT_ID}/inspection/nodes/{NODE_ID}/review-workspace",
            headers=HEADERS,
        )
    )

    assert workspace["latestHumanDecision"] == opinion


def test_node_review_opinion_does_not_mutate_running_review_run() -> None:
    repo.state["review_runs"] = [
        item
        for item in repo.state["review_runs"]
        if item.get("projectId") != PROJECT_ID
        or int(item.get("nodeId") or 0) != NODE_ID
    ]
    run = {
        "id": "RRUN-DECOUPLE-INVARIANT",
        "reviewRunId": "RRUN-DECOUPLE-INVARIANT",
        "projectId": PROJECT_ID,
        "nodeId": NODE_ID,
        "status": "running",
        "revision": 1,
    }
    repo.state["review_runs"].insert(0, run)
    workspace = assert_ok(
        client.get(
            f"/api/projects/{PROJECT_ID}/inspection/nodes/{NODE_ID}/review-workspace",
            headers=HEADERS,
        )
    )

    response = assert_ok(
        client.post(
            f"/api/projects/{PROJECT_ID}/inspection/nodes/{NODE_ID}/review-opinions",
            headers={
                **HEADERS,
                "Idempotency-Key": "review-b-node-opinion-independent",
                "If-Match": workspace["project"]["etag"],
            },
            json={
                "result": "证据不足",
                "opinion": "先形成节点人工结论",
                "evidenceLinkIds": [],
            },
        )
    )

    assert response["opinion"]["result"] == "证据不足"
    assert run["status"] == "running"
    assert "humanDecision" not in run


def test_review_b_routes_and_api_are_limited_to_inspection_role() -> None:
    routes = assert_ok(client.get("/api/auth/routes?role=inspection"))
    assert "/ai-review-b" in [route["path"] for route in routes]
    workbench_route = next(route for route in routes if route["path"] == "/workbench")
    assert workbench_route["redirect"] == "/ai-review-b"

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


def test_review_b_search_evidence_separates_located_candidates_and_advisory_files() -> None:
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
        ]
    )
    session = create_session()

    response = assert_ok(
        client.post(
            f"/api/review-sessions/{session['id']}/messages",
            headers={
                **HEADERS,
                "Idempotency-Key": "review-b-evidence-tier-test",
                "If-Match": session["etag"],
            },
            json={"content": "/检索证据"},
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
    assert [item["id"] for item in cards[0]["items"]] == ["NEL-REVIEW-B-FORMAL"]
    assert cards[1]["advisory"] is True
    assert [item["id"] for item in cards[1]["items"]] == ["NEL-REVIEW-B-ADVISORY"]
    assert response["assistantMessage"]["execution"]["modelCalled"] is False


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

    # 2026-08-14 从 routes.py 搬到 libs/review_conversation_blocks（纯数据整形，
    # 与请求无关）。这里直接引新家，别再经由路由模块转一手。
    from libs.review_conversation_blocks import review_basis_display_label

    assert [review_basis_display_label(item) for item, _ in cases] == [
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
