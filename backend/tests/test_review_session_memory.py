"""「AI审查」对话助手的记忆（apps/api/review_session_memory.py）。

覆盖四件事：会话只认本人、对话历史限天数且旧证据下的回答标过期、新对话带上上一本要点、
个人回答偏好。模型一律打桩，断言落在「交给模型的上下文」和接口返回上。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from apps.api import review_session_memory as memory
from apps.api import routes as routes_module
from apps.api.main import app
from libs.contracts.responses import SERVER_TZ
from libs.db.repository import repo

client = TestClient(app)
PROJECT_ID = "P-2026-HDCP-001"
NODE_ID = 16
OWNER = {"X-Role": "inspection", "X-User-Id": "USER-INSPECTION-001"}
COLLEAGUE = {"X-Role": "inspection", "X-User-Id": "USER-INSPECTION-009"}

ANSWER_NONCONFORM = (
    "| 项目 | 内容 |\n| --- | --- |\n| 结论 | 不符合 |\n"
    "| 关键证据 | [焊工证.pdf](evidence:EVL-1) |\n\n"
    "**焊工证**已于 2026-10-01 过期，需施工方补交有效证书。"
)


@pytest.fixture(autouse=True)
def _isolated_state(monkeypatch):
    monkeypatch.setenv("AICHECK_REVIEW_CONVERSATION_EXECUTION_MODE", "inline")
    repo.reset()
    repo.postgres_enabled = False
    repo.sync_postgres = None
    repo.postgres_dsn = None
    repo.sqlite_enabled = False
    repo.sqlite_path = None
    # 同院同节点的另一位监检：复制本人的成员行，只换人
    owner_member = next(
        row
        for row in repo.state["project_members"]
        if row["userId"] == "USER-INSPECTION-001" and row["projectId"] == PROJECT_ID
    )
    repo.state["project_members"].append(
        {**owner_member, "id": "PM-INSPECTION-009", "userId": "USER-INSPECTION-009", "name": "李工"}
    )


class CapturingRuntime:
    """记下每次交给模型的上下文（最后一条 user 消息里的 JSON）。"""

    def __init__(self, answers: list[str] | None = None):
        self.contexts: list[dict] = []
        self.answers = list(answers or [])

    def chat_sync(self, messages, model, **kwargs):
        payload = messages[1]["content"].rsplit("\n\n", 1)[0]
        self.contexts.append(json.loads(payload))
        text = self.answers.pop(0) if self.answers else "需要人工确认。"
        return {
            "provider": "test",
            "model": "test-model",
            "choices": [{"message": {"content": text}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }


@pytest.fixture
def runtime(monkeypatch) -> CapturingRuntime:
    fake = CapturingRuntime()
    monkeypatch.setenv("AICHECK_REVIEW_CONVERSATION_LLM_EXECUTION", "litellm")
    monkeypatch.setattr(routes_module, "qwen_runtime_client", lambda: fake)
    return fake


def data(response):
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["code"] == 0, payload
    return payload["data"]


def create_session(headers=OWNER, key="memory-session") -> dict:
    return data(
        client.post(
            f"/api/projects/{PROJECT_ID}/inspection/nodes/{NODE_ID}/review-sessions",
            headers={**headers, "Idempotency-Key": key},
            json={"currentTask": "核对焊工资格"},
        )
    )["session"]


def current(session_id: str) -> dict:
    return repo.find_one("review_sessions", session_id)


def ask(session_id: str, text: str, headers=OWNER, key: str | None = None):
    session = current(session_id)
    return client.post(
        f"/api/review-sessions/{session_id}/messages",
        headers={
            **headers,
            "Idempotency-Key": key or f"ask-{hashlib.sha1(text.encode()).hexdigest()[:12]}",
            "If-Match": routes_module.record_etag("review-session", session),
        },
        json={"content": text},
    )


def restart(session_id: str, key="restart-1"):
    session = current(session_id)
    return client.post(
        f"/api/review-sessions/{session_id}/restart",
        headers={
            **OWNER,
            "Idempotency-Key": key,
            "If-Match": routes_module.record_etag("review-session", session),
        },
        json={},
    )


# ---- 1. 会话只认本人 ----


def test_colleague_on_same_node_cannot_read_or_write_another_users_session(runtime) -> None:
    session = create_session()
    data(ask(session["id"], "焊工证是否在有效期内？"))
    sid = session["id"]
    etag = routes_module.record_etag("review-session", current(sid))

    attempts = {
        "read messages": client.get(f"/api/review-sessions/{sid}/messages", headers=COLLEAGUE),
        "post message": client.post(
            f"/api/review-sessions/{sid}/messages",
            headers={**COLLEAGUE, "Idempotency-Key": "colleague-post", "If-Match": etag},
            json={"content": "依据"},
        ),
        "context action": client.post(
            f"/api/review-sessions/{sid}/actions/set_current_task",
            headers={**COLLEAGUE, "Idempotency-Key": "colleague-action", "If-Match": etag},
            json={"currentTask": "改别人的任务"},
        ),
        "events": client.get(f"/api/review-sessions/{sid}/events", headers=COLLEAGUE),
        "executions": client.get(f"/api/review-sessions/{sid}/agent-executions", headers=COLLEAGUE),
        "restart": client.post(
            f"/api/review-sessions/{sid}/restart",
            headers={**COLLEAGUE, "Idempotency-Key": "colleague-restart", "If-Match": etag},
            json={},
        ),
    }
    for name, response in attempts.items():
        body = response.json()
        # 按「不存在」回，不透露这本会话存在
        assert body["data"]["reason"] == "NOT_FOUND", (name, body)

    # 同事的话没有写进去，本人照常能读
    owner_messages = data(client.get(f"/api/review-sessions/{sid}/messages", headers=OWNER))["messages"]
    assert [item["role"] for item in owner_messages] == ["user", "assistant"]
    assert current(sid)["currentTask"] != "改别人的任务"
    # 同事在同一节点开的是自己的一本
    own = create_session(COLLEAGUE, key="colleague-session")
    assert own["id"] != sid and own["createdBy"] == "USER-INSPECTION-009"


# ---- 2. 历史限天数、旧证据下的回答标过期 ----


def test_answer_given_under_old_evidence_is_marked_stale_for_the_model(runtime) -> None:
    session = create_session()
    data(ask(session["id"], "焊工证是否在有效期内？"))
    first_context = runtime.contexts[-1]
    # 本次提问只在 question 里，不在历史里；占位的「正在核查中…」也不算历史
    assert first_context["recentConversation"] == []
    assert first_context["conversationHistoryDays"] == memory.HISTORY_DAYS

    data(ask(session["id"], "那检测报告呢？"))
    unchanged = runtime.contexts[-1]["recentConversation"]
    assert [item["role"] for item in unchanged] == ["user", "assistant"]
    assert unchanged[1]["staleContext"] is False

    # 施工方补交：节点证据变了
    binding = next(row for row in repo.state["bindings"] if row["id"] == "BIND-16-001")
    binding["revision"] = int(binding.get("revision") or 0) + 5
    data(ask(session["id"], "现在再看焊工证。"))
    history = runtime.contexts[-1]["recentConversation"]
    assistant_flags = [item["staleContext"] for item in history if item["role"] == "assistant"]
    assert assistant_flags == [True, True]
    assert all(item["text"] != "现在再看焊工证。" for item in history)
    assert "staleContext 为 true" in routes_module.REVIEW_CONVERSATION_SYSTEM_PROMPT


def test_history_older_than_window_is_not_given_to_the_model(runtime) -> None:
    session = create_session()
    data(ask(session["id"], "第一问：焊工证？"))
    old = (datetime.now(SERVER_TZ) - timedelta(days=memory.HISTORY_DAYS + 3)).strftime("%Y-%m-%d %H:%M:%S")
    for row in repo.state["review_messages"]:
        if row["sessionId"] == session["id"]:
            row["createdAt"] = old

    view = data(
        client.get(
            f"/api/projects/{PROJECT_ID}/inspection/nodes/{NODE_ID}/review-workspace", headers=OWNER
        )
    )["session"]
    assert view["memory"] == {
        "historyDays": memory.HISTORY_DAYS,
        "lastMessageAt": old,
        "historyExpired": True,
    }

    data(ask(session["id"], "第二问：检测报告？"))
    assert runtime.contexts[-1]["recentConversation"] == []
    fresh = data(client.get(f"/api/review-sessions/{session['id']}/messages", headers=OWNER))
    assert len(fresh["messages"]) == 4  # 记录照留，只是不再交给模型


# ---- 3. 新对话与上一本要点 ----


def test_new_conversation_archives_old_session_and_carries_a_deterministic_summary(runtime) -> None:
    runtime.answers = [ANSWER_NONCONFORM]
    session = create_session()
    data(ask(session["id"], "焊工证是否在有效期内？"))
    data(ask(session["id"], "/检索证据"))  # 斜杠命令不算问题

    result = data(restart(session["id"]))
    new = result["session"]
    assert result["archivedSessionId"] == session["id"]
    assert new["id"] != session["id"] and new["status"] == "active"
    assert new["previousSessionId"] == session["id"]
    carry = new["carryOver"]
    assert carry["fromSessionId"] == session["id"]
    assert carry["unanswered"] == []
    assert len(carry["items"]) == 1
    item = carry["items"][0]
    assert item["question"] == "焊工证是否在有效期内？"
    assert item["verdict"] == "不符合"
    assert item["answer"] == "焊工证已于 2026-10-01 过期，需施工方补交有效证书。"

    old = current(session["id"])
    assert old["status"] == "archived" and old["archivedBy"] == "USER-INSPECTION-001"
    workspace = data(
        client.get(
            f"/api/projects/{PROJECT_ID}/inspection/nodes/{NODE_ID}/review-workspace", headers=OWNER
        )
    )
    assert workspace["session"]["id"] == new["id"]

    # 旧会话只读：能翻看，不能再发问
    assert len(data(client.get(f"/api/review-sessions/{session['id']}/messages", headers=OWNER))["messages"]) == 4
    refused = ask(session["id"], "还能问吗？", key="ask-archived").json()
    assert refused["data"]["reason"] == "CONFLICT"
    assert "已结束" in refused["message"]

    # 新会话第一问：模型拿到上一本要点，近期对话是空的
    data(ask(new["id"], "补交的焊工证合格吗？"))
    context = runtime.contexts[-1]
    assert context["recentConversation"] == []
    assert context["previousSession"]["items"][0]["verdict"] == "不符合"
    assert "重新核实" in context["previousSession"]["notice"]


def test_new_conversation_requires_etag_and_lists_unanswered_questions(runtime) -> None:
    session = create_session()
    data(ask(session["id"], "焊工证？"))
    answer = next(
        row
        for row in repo.state["review_messages"]
        if row["sessionId"] == session["id"] and row["role"] == "assistant"
    )
    answer["status"] = "failed"

    no_etag = client.post(
        f"/api/review-sessions/{session['id']}/restart",
        headers={**OWNER, "Idempotency-Key": "restart-no-etag"},
        json={},
    )
    assert no_etag.status_code == 428

    carry = data(restart(session["id"]))["session"]["carryOver"]
    assert carry["items"] == []
    assert [row["question"] for row in carry["unanswered"]] == ["焊工证？"]


def test_restart_with_nothing_to_carry_and_dismissing_carry_over(runtime) -> None:
    empty = create_session()
    blank = data(restart(empty["id"], key="restart-empty"))["session"]
    assert "carryOver" not in blank

    runtime.answers = [ANSWER_NONCONFORM]
    data(ask(blank["id"], "焊工证是否在有效期内？"))
    carried = data(restart(blank["id"], key="restart-carried"))["session"]
    assert carried["carryOver"]["items"]

    dismissed = data(
        client.post(
            f"/api/review-sessions/{carried['id']}/carry-over/dismiss",
            headers={
                **OWNER,
                "Idempotency-Key": "dismiss-1",
                "If-Match": routes_module.record_etag("review-session", current(carried["id"])),
            },
        )
    )["session"]
    assert dismissed["carryOver"] is None
    data(ask(carried["id"], "补交了吗？"))
    assert "previousSession" not in runtime.contexts[-1]


def test_fallback_answer_counts_as_unanswered_and_stays_out_of_history(monkeypatch) -> None:
    # 模型关闭时回的是「本次未能回答你的问题…」：那不是答案，不能被摘成要点或当历史喂回去
    monkeypatch.setenv("AICHECK_REVIEW_CONVERSATION_LLM_EXECUTION", "deterministic")
    session = create_session()
    data(ask(session["id"], "焊工证？"))
    answer = next(
        row
        for row in repo.state["review_messages"]
        if row["sessionId"] == session["id"] and row["role"] == "assistant"
    )
    assert answer["execution"]["mode"] == "deterministic_fallback"
    history = memory.recent_conversation(current(session["id"]), user_text="下一问", review_run_id="")
    assert [(item["role"], item["text"]) for item in history] == [("user", "焊工证？")]

    carry = data(restart(session["id"]))["session"]["carryOver"]
    assert carry["items"] == []
    assert [row["question"] for row in carry["unanswered"]] == ["焊工证？"]


# ---- 4. 个人回答偏好 ----


def test_answer_preferences_are_per_user_and_reach_only_their_own_conversations(runtime) -> None:
    url = "/api/review-assistant/preferences"
    assert data(client.get(url, headers=OWNER))["preferences"] == {
        "text": "",
        "updatedAt": None,
        "maxLength": memory.PREFERENCE_MAX_CHARS,
    }
    saved = data(
        client.put(url, headers={**OWNER, "Idempotency-Key": "pref-1"}, json={"text": "先列不符合项，回答短一点。"})
    )["preferences"]
    assert saved["text"] == "先列不符合项，回答短一点。"
    assert data(client.get(url, headers=COLLEAGUE))["preferences"]["text"] == ""

    session = create_session()
    data(ask(session["id"], "焊工证？"))
    assert runtime.contexts[-1]["userPreferences"] == "先列不符合项，回答短一点。"
    colleague_session = create_session(COLLEAGUE, key="colleague-session")
    data(ask(colleague_session["id"], "焊工证？", headers=COLLEAGUE, key="colleague-ask"))
    assert "userPreferences" not in runtime.contexts[-1]

    too_long = client.put(
        url, headers={**OWNER, "Idempotency-Key": "pref-long"}, json={"text": "长" * (memory.PREFERENCE_MAX_CHARS + 1)}
    ).json()
    assert too_long["data"]["reason"] == "VALIDATION_ERROR"
    cleared = data(client.put(url, headers={**OWNER, "Idempotency-Key": "pref-clear"}, json={"text": ""}))
    assert cleared["preferences"]["text"] == ""
    data(ask(session["id"], "再问一次。"))
    assert "userPreferences" not in runtime.contexts[-1]
    assert len(repo.state[memory.PREFERENCES_COLLECTION]) == 1


def test_answer_preferences_are_inspection_only() -> None:
    response = client.get(
        "/api/review-assistant/preferences",
        headers={"X-Role": "contractor", "X-User-Id": "USER-CONTRACTOR-001"},
    )
    assert response.status_code == 403
    assert response.json()["data"]["reason"] == "FORBIDDEN"


# ---- 摘要规则（纯函数） ----


def test_verdict_is_read_only_from_the_conclusion_cell() -> None:
    assert memory.answer_verdict(ANSWER_NONCONFORM) == "不符合"
    assert memory.answer_verdict("| 结论 | 证据不足 |") == "证据不足"
    assert memory.answer_verdict("| 结论（符合/不符合/证据不足） | 符合 |") == "符合"
    # 散文里的「是否符合」不是结论
    assert memory.answer_verdict("需核对焊工证是否符合 TSG Z6002 的要求。") is None


def test_gist_skips_tables_and_strips_reference_links() -> None:
    text = "| 结论 | 符合 |\n\n## 说明\n见 [TSG D7006 第 D2.1 条](basis:LOC-1)，许可证在有效期内。"
    assert memory.answer_gist(text) == "见 TSG D7006 第 D2.1 条，许可证在有效期内。"
    assert memory.answer_gist("| a |\n- 见 [焊工证.pdf](evidence:EVL-9) 第 2 页") == "见 焊工证.pdf 第 2 页"
