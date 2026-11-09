"""「AI审查」对话的保留期限（apps/api/review_session_retention.py、scripts/review_session_retention.py）。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from apps.api import review_session_retention as retention
from apps.api import routes as routes_module
from apps.api.main import app
from libs.contracts.responses import SERVER_TZ
from libs.db.repository import repo
from scripts import review_session_retention as script

client = TestClient(app)
PROJECT_ID = "P-2026-HDCP-001"
NODE_ID = 16
OWNER = {"X-Role": "inspection", "X-User-Id": "USER-INSPECTION-001"}


@pytest.fixture(autouse=True)
def _isolated_state(monkeypatch):
    monkeypatch.setenv("AICHECK_REVIEW_CONVERSATION_EXECUTION_MODE", "inline")
    monkeypatch.setattr(retention, "ARCHIVE_AFTER_MONTHS", 3.0)
    repo.reset()
    repo.postgres_enabled = False
    repo.sync_postgres = None
    repo.postgres_dsn = None
    repo.sqlite_enabled = False
    repo.sqlite_path = None


class FakeRuntime:
    """不串流：每轮一条推理增量、一条正文增量（与线上非串流兜底同一路径）。"""

    def __init__(self, content: str = "| 核查项 | 结论 |\n|---|---|\n| 焊工证 | 符合 |\n\n### 简要说明\n证书有效。", reasoning: str = "先看证书有效期，再看合格项目。"):
        self.content = content
        self.reasoning = reasoning

    def chat_sync(self, messages, model, **kwargs):
        return {
            "provider": "test",
            "model": "test-model",
            "choices": [{"message": {"content": self.content, "reasoning_content": self.reasoning}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }


def use_runtime(monkeypatch, runtime: FakeRuntime) -> None:
    monkeypatch.setenv("AICHECK_REVIEW_CONVERSATION_LLM_EXECUTION", "litellm")
    monkeypatch.setattr(routes_module, "qwen_runtime_client", lambda: runtime)


def data(response):
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["code"] == 0, payload
    return payload["data"]


def create_session(key="retention-session", generation: str = "") -> dict:
    suffix = f"-after-{generation}" if generation else ""
    return data(
        client.post(
            f"/api/projects/{PROJECT_ID}/inspection/nodes/{NODE_ID}/review-sessions",
            headers={**OWNER, "Idempotency-Key": key + suffix},
            json={"currentTask": "核对焊工资格"},
        )
    )["session"]


def ask(session_id: str, text: str, key: str):
    session = repo.find_one("review_sessions", session_id)
    return client.post(
        f"/api/review-sessions/{session_id}/messages",
        headers={**OWNER, "Idempotency-Key": key, "If-Match": routes_module.record_etag("review-session", session)},
        json={"content": text},
    )


def deltas(session_id: str) -> list[dict]:
    return [
        event
        for event in repo.state["review_session_events"]
        if event["sessionId"] == session_id and event["eventType"] in retention.STREAM_DELTA_EVENTS
    ]


def workspace() -> dict:
    return data(client.get(f"/api/projects/{PROJECT_ID}/inspection/nodes/{NODE_ID}/review-workspace", headers=OWNER))


# ---- 压缩流式增量 ----


def test_completed_answer_compacts_its_stream_deltas_but_keeps_the_rows(monkeypatch) -> None:
    use_runtime(monkeypatch, FakeRuntime())
    session = create_session()
    answer = data(ask(session["id"], "焊工证有效吗？", "ask-1"))["assistantMessage"]
    assert answer["status"] == "completed"

    rows = deltas(session["id"])
    assert {row["eventType"] for row in rows} == {"agent.message.delta", "agent.reasoning.delta"}
    for row in rows:
        payload = row["payload"]
        assert "content" not in payload
        assert payload["compacted"] is True and payload["chars"] > 0
        assert payload["archivedInMessageId"] == answer["id"]
        assert payload["executionId"] == answer["execution"]["executionId"]
        assert row["payloadHash"]  # 原文指纹不动
    # 正文、推理都在最终消息里
    block_types = {block["type"] for block in answer["contentBlocks"]}
    assert {"text", "reasoning"} <= block_types
    # 行和编号都还在：事件列表照常给出这些增量
    listed = data(client.get(f"/api/review-sessions/{session['id']}/events", headers=OWNER))["events"]
    assert sum(1 for event in listed if event["eventType"] in retention.STREAM_DELTA_EVENTS) == len(rows)


class TwoTurnRuntime:
    """第一轮边说话边调工具，第二轮给结论：只有第二轮的正文进最终消息。"""

    def __init__(self):
        self.calls = 0

    def chat_sync(self, messages, model, **kwargs):
        self.calls += 1
        if self.calls == 1:
            message = {
                "content": "初步说明：我先核对当前上下文。",
                "reasoning_content": "需要先读取节点上下文再判断。",
                "tool_calls": [{"id": "call-1", "function": {"name": "get_review_context", "arguments": "{}"}}],
            }
        else:
            message = {"content": "最终结论：证据不足，需人工确认。", "reasoning_content": "上下文读完了，证据不够。"}
        return {"provider": "test", "model": "test-model", "choices": [{"message": message}]}


def test_earlier_turn_text_is_kept_because_the_final_message_does_not_have_it(monkeypatch) -> None:
    use_runtime(monkeypatch, TwoTurnRuntime())
    session = create_session()
    answer = data(ask(session["id"], "核查证据", "ask-two-turns"))["assistantMessage"]
    assert answer["execution"]["turnCount"] == 2
    by_kind = {(row["eventType"], row["payload"]["turn"]): row["payload"] for row in deltas(session["id"])}
    # 第一轮的正文不在最终消息里：留着
    assert by_kind[("agent.message.delta", 1)]["content"] == "初步说明：我先核对当前上下文。"
    # 最后一轮的正文、两轮的推理都已存档：压掉
    assert by_kind[("agent.message.delta", 2)]["compacted"] is True
    assert all(by_kind[("agent.reasoning.delta", turn)]["compacted"] is True for turn in (1, 2))


def test_deltas_stay_when_the_answer_text_was_truncated(monkeypatch) -> None:
    use_runtime(monkeypatch, FakeRuntime(content="长" * 5000))
    session = create_session()
    data(ask(session["id"], "写个长的", "ask-long"))
    rows = deltas(session["id"])
    assert rows and all("content" in row["payload"] for row in rows)


def test_deltas_stay_when_the_reasoning_archive_was_truncated(monkeypatch) -> None:
    use_runtime(monkeypatch, FakeRuntime(reasoning="想" * 30000))
    session = create_session()
    answer = data(ask(session["id"], "想很久", "ask-reasoning"))["assistantMessage"]
    reasoning = next(block["text"] for block in answer["contentBlocks"] if block["type"] == "reasoning")
    assert "已截去" in reasoning
    assert all("content" in row["payload"] for row in deltas(session["id"]))


# ---- 闲置会话归档 ----


def age_session(session_id: str, days: int) -> None:
    old = (datetime.now(SERVER_TZ) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    repo.find_one("review_sessions", session_id)["createdAt"] = old
    for row in repo.state["review_messages"]:
        if row["sessionId"] == session_id:
            row["createdAt"] = old


def test_idle_session_is_archived_on_next_open_and_the_new_one_carries_over(monkeypatch) -> None:
    use_runtime(monkeypatch, FakeRuntime())
    first = create_session()
    data(ask(first["id"], "焊工证有效吗？", "ask-idle"))
    age_session(first["id"], 100)

    view = workspace()
    assert view["session"] is None
    assert view["sessionGeneration"] == first["id"]
    assert data(
        client.get(f"/api/projects/{PROJECT_ID}/inspection/nodes/{NODE_ID}/review-sessions/active", headers=OWNER)
    )["session"] is None

    # 老的固定键会被中间件重放成那本旧会话——这正是要拼代次的原因
    replayed = create_session()
    assert replayed["id"] == first["id"]

    second = create_session(generation=view["sessionGeneration"])
    assert second["id"] != first["id"] and second["status"] == "active"
    assert second["previousSessionId"] == first["id"]
    assert second["carryOver"]["items"][0]["question"] == "焊工证有效吗？"
    old = repo.find_one("review_sessions", first["id"])
    assert old["status"] == "archived" and old["archivedReason"] == "idle" and old["archivedBy"] == "system:idle"
    assert any(
        event["eventType"] == "session.archived" and event["sessionId"] == first["id"]
        for event in repo.state["review_session_events"]
    )
    refused = ask(first["id"], "还能问吗？", "ask-archived").json()
    assert refused["data"]["reason"] == "CONFLICT"
    # 同一代内重试还是去重
    assert create_session(generation=first["id"])["id"] == second["id"]
    assert workspace()["session"]["id"] == second["id"]
    assert workspace()["sessionGeneration"] == ""


def test_recent_sessions_and_disabled_setting_are_left_alone(monkeypatch) -> None:
    session = create_session()
    age_session(session["id"], 60)
    assert workspace()["session"]["id"] == session["id"]
    age_session(session["id"], 100)
    monkeypatch.setattr(retention, "ARCHIVE_AFTER_MONTHS", 0.0)
    assert workspace()["session"]["id"] == session["id"]


def test_new_conversation_records_its_archive_reason() -> None:
    session = create_session()
    stored = repo.find_one("review_sessions", session["id"])
    restarted = data(
        client.post(
            f"/api/review-sessions/{session['id']}/restart",
            headers={**OWNER, "Idempotency-Key": "restart-reason", "If-Match": routes_module.record_etag("review-session", stored)},
            json={},
        )
    )
    old = repo.find_one("review_sessions", session["id"])
    assert old["archivedReason"] == "new_conversation"
    assert workspace()["session"]["id"] == restarted["session"]["id"]


# ---- 存量脚本 ----


def test_script_dry_run_reports_and_apply_backs_up_then_changes_only_those_rows(monkeypatch, tmp_path) -> None:
    use_runtime(monkeypatch, FakeRuntime())
    # 一本有回答的会话（模拟上线前：增量还带着正文）、一本闲置超期的会话
    active = create_session("script-active")
    data(ask(active["id"], "焊工证有效吗？", "ask-script"))
    for row in deltas(active["id"]):
        row["payload"]["content"] = "旧数据里的正文"
        row["payload"].pop("compacted", None)
    idle = repo.find_one("review_sessions", active["id"])
    age_session(idle["id"], 120)

    plan = script.plan_for_current_tenant("TENANT-DEFAULT")
    summary = script.summarize(plan)
    assert summary["answersToCompact"] == 1
    assert summary["deltaEventsToCompact"] == len(deltas(active["id"]))
    assert summary["charsRemoved"] == len("旧数据里的正文") * summary["deltaEventsToCompact"]
    assert [item["sessionId"] for item in summary["idleSessionsToArchive"]] == [active["id"]]
    # 只预览不改
    assert all("content" in row["payload"] for row in deltas(active["id"]))
    assert repo.find_one("review_sessions", active["id"])["status"] == "active"

    flushed: list[dict] = []
    monkeypatch.setattr("libs.db.repository.flush_state_records", lambda records: flushed.append(records))
    backup = script.write_backup(tmp_path, plan)
    result = script.apply_plan(plan)
    assert result == {"eventsCompacted": summary["deltaEventsToCompact"], "sessionsArchived": 1}
    lines = [json.loads(line) for line in backup.read_text(encoding="utf-8").splitlines()]
    assert {line["collection"] for line in lines} == {"review_session_events", "review_sessions"}
    assert all("content" in line["row"]["payload"] for line in lines if line["collection"] == "review_session_events")
    assert oct(backup.stat().st_mode & 0o777) == "0o600"
    assert set(flushed[0]) == {"review_session_events", "review_sessions"}
    assert all(row["tenantId"] == "TENANT-DEFAULT" for rows in flushed[0].values() for row in rows)
    assert repo.find_one("review_sessions", active["id"])["archivedReason"] == "idle"
    assert all("content" not in row["payload"] for row in deltas(active["id"]))


def test_script_refuses_the_cron_windows() -> None:
    at = datetime(2026, 11, 9, 22, 0, tzinfo=SERVER_TZ)
    assert script.in_cron_window(at.replace(minute=0))
    assert script.in_cron_window(at.replace(minute=31))
    assert not script.in_cron_window(at.replace(minute=15))
    assert not script.in_cron_window(at.replace(minute=45))
