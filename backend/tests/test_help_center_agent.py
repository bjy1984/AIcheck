"""对话 Agent 回答「系统怎么用」：模型调 search_help_docs，教程内容回到下一轮，再据此作答。

模型是假的，这里验证的是接线：工具在 Agent 的工具清单里、分发到检索、结果以 tool 消息回到模型、
执行事件里记下“命中 N 节使用教程”。真实模型会不会照教程回答，要看生产实测。
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from apps.api import routes as routes_module
from apps.api.main import app
from libs.db.repository import repo


@pytest.fixture(autouse=True)
def _inline_conversation_execution(monkeypatch):
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
            headers={**HEADERS, "Idempotency-Key": "help-center-session-test"},
            json={"currentTask": "核对设计单位许可证"},
        )
    )
    return payload["session"]


def test_agent_looks_up_help_docs_for_a_how_to_question(monkeypatch) -> None:
    class HowToRuntime:
        def __init__(self) -> None:
            self.turn = 0
            self.tool_names_offered: set[str] = set()
            self.tool_message = ""

        def chat_sync(self, messages, model, **kwargs):
            self.turn += 1
            self.tool_names_offered = {item["function"]["name"] for item in kwargs["tools"]}
            if self.turn == 1:
                return {
                    "id": "chatcmpl-help-1",
                    "provider": "test-qwen",
                    "model": "qwen-help-test",
                    "choices": [
                        {
                            "message": {
                                "content": "",
                                "tool_calls": [
                                    {
                                        "id": "call-help-1",
                                        "type": "function",
                                        "function": {
                                            "name": "search_help_docs",
                                            "arguments": json.dumps({"query": "怎么退回补正"}, ensure_ascii=False),
                                        },
                                    }
                                ],
                            }
                        }
                    ],
                    "usage": {"prompt_tokens": 60, "completion_tokens": 10},
                }
            self.tool_message = next(m["content"] for m in messages if m.get("role") == "tool")
            return {
                "id": "chatcmpl-help-2",
                "provider": "test-qwen",
                "model": "qwen-help-test",
                "choices": [{"message": {"content": "退回补正要写明资料项、问题和整改要求（见《节点审查流程》）。"}}],
                "usage": {"prompt_tokens": 90, "completion_tokens": 20},
            }

    runtime = HowToRuntime()
    monkeypatch.setenv("AICHECK_REVIEW_CONVERSATION_LLM_EXECUTION", "litellm")
    monkeypatch.setattr(routes_module, "qwen_runtime_client", lambda: runtime)
    session = create_session()
    response = assert_ok(
        client.post(
            f"/api/review-sessions/{session['id']}/messages",
            headers={
                **HEADERS,
                "Idempotency-Key": "help-center-howto-test",
                "If-Match": session["etag"],
            },
            json={"content": "退回补正怎么操作？"},
        )
    )

    # 工具清单里有它，教程内容作为 tool 消息回到了第二轮
    assert "search_help_docs" in runtime.tool_names_offered
    tool_payload = json.loads(runtime.tool_message)
    assert tool_payload["sectionCount"] >= 1
    assert any("退回补正" in section["heading"] for section in tool_payload["sections"])
    assert "出自哪一节" in tool_payload["note"]

    execution = response["assistantMessage"]["execution"]
    assert execution["toolCallCount"] == 1
    assert execution["turnCount"] == 2
    text = next(b["text"] for b in response["assistantMessage"]["contentBlocks"] if b["type"] == "text")
    assert "节点审查流程" in text

    events = assert_ok(client.get(f"/api/review-sessions/{session['id']}/events", headers=HEADERS))["events"]
    assert "agent.tool_call.completed" in {item["eventType"] for item in events}
    assert "命中" in json.dumps(events, ensure_ascii=False) and "节使用教程" in json.dumps(events, ensure_ascii=False)
