"""助手面板 live read 的节流、运行事件投影缓存，以及消息接口带回会话（2026-11-10）。

生产上问一句话 1 分 44 秒，模型只占约 47 秒：面板自己的轮询每次都重读整个节点的运行
和运行事件、再逐条量大小算哈希，把 Agent 所在的 API 进程压满。见 apps/api/review_session_live.py。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apps.api import review_session_live as live
from apps.api import routes as routes_module
from apps.api.main import app
from libs.db.repository import repo

client = TestClient(app)
PROJECT_ID = "P-2026-HDCP-001"
NODE_ID = 16
OWNER = {"X-Role": "inspection", "X-User-Id": "USER-INSPECTION-001"}


@pytest.fixture(autouse=True)
def _fresh_live_state():
    live.reset_for_tests()
    yield
    live.reset_for_tests()


# ---- 节流 ----


def test_session_rows_refresh_every_call_window_but_runs_only_every_few_seconds() -> None:
    plan = lambda now, **kw: live.plan_refresh(
        "S1", now, min_interval_seconds=0.4, include_runs=True, **kw
    )
    assert plan(100.0) == (True, True), "第一次连运行一起读"
    assert plan(100.2) == (False, False), "0.4 秒内谁都不读"
    assert plan(100.6) == (True, False), "会话的行照旧刷新，运行还不到 3 秒"
    assert plan(102.9) == (True, False)
    assert plan(103.4) == (True, True), "满 3 秒再读运行"


def test_message_only_reads_never_touch_runs_and_do_not_use_up_the_run_window() -> None:
    assert live.plan_refresh("S1", 10.0, min_interval_seconds=0.4, include_runs=False) == (
        True,
        False,
    )
    # 只看消息的那一下没读运行，所以接下来要运行的读取立刻就能读
    assert live.plan_refresh("S1", 10.5, min_interval_seconds=0.4, include_runs=True) == (
        True,
        True,
    )


def test_sessions_are_throttled_independently() -> None:
    assert live.plan_refresh("S1", 5.0, min_interval_seconds=0.4, include_runs=True) == (True, True)
    assert live.plan_refresh("S2", 5.1, min_interval_seconds=0.4, include_runs=True) == (True, True)


# ---- 运行事件投影缓存 ----


def test_projection_is_computed_once_per_event_id() -> None:
    calls: list[str] = []

    def compute(item):
        calls.append(str(item.get("id") or ""))
        return {"n": len(item["details"])}, f"hash-{item.get('id')}"

    event = {"id": "REVT-1", "details": {"a": 1}}
    first = live.run_event_projection(event, compute)
    # 重载后是新的 dict，id 相同：不再重算
    again = live.run_event_projection({"id": "REVT-1", "details": {"a": 1}}, compute)
    assert first == again == ({"n": 1}, "hash-REVT-1")
    assert calls == ["REVT-1"]
    # 没有 id 的不缓存
    live.run_event_projection({"details": {}}, compute)
    live.run_event_projection({"details": {}}, compute)
    assert calls == ["REVT-1", "", ""]


def test_projection_cache_is_cleared_when_full(monkeypatch) -> None:
    monkeypatch.setattr(live, "_PROJECTION_CACHE_LIMIT", 2)
    compute = lambda item: ({}, item["id"])
    for event_id in ("A", "B", "C"):
        live.run_event_projection({"id": event_id}, compute)
    assert set(live._PROJECTION_CACHE) == {"C"}


def test_event_snapshot_hashes_and_folds_each_run_event_only_once(monkeypatch) -> None:
    repo.reset()
    big = {"blob": "x" * 5000}
    small = {"note": "ok"}
    session = {"id": "S-LIVE", "projectId": "P-LIVE", "nodeId": 3}
    monkeypatch.setitem(
        repo.state,
        "review_runs",
        [{"id": "R1", "reviewRunId": "R1", "projectId": "P-LIVE", "nodeId": 3}],
    )
    monkeypatch.setitem(
        repo.state,
        "review_events",
        [
            {
                "id": "REVT-BIG",
                "reviewRunId": "R1",
                "eventType": "graph_node.succeeded",
                "details": big,
                "createdAt": "2026-11-10 00:00:01",
            },
            {
                "id": "REVT-SMALL",
                "reviewRunId": "R1",
                "eventType": "graph_node.started",
                "details": small,
                "createdAt": "2026-11-10 00:00:02",
            },
        ],
    )
    monkeypatch.setitem(repo.state, "review_session_events", [])
    hashed: list[object] = []
    real_hash = routes_module.stable_hash_payload
    monkeypatch.setattr(
        routes_module, "stable_hash_payload", lambda value: hashed.append(value) or real_hash(value)
    )

    first = routes_module.review_session_event_snapshot("S-LIVE", session)
    second = routes_module.review_session_event_snapshot("S-LIVE", session)

    assert len(hashed) == 2, "第二次快照不再逐条算哈希"
    assert [item["payloadHash"] for item in first] == [real_hash(big), real_hash(small)], (
        "哈希照原文算"
    )
    assert first[0]["payload"]["payloadTruncated"] is True, "大事件照旧折叠"
    assert first == second
    # 交出去的是副本：调用方改了，缓存和 state 都不受影响
    second[1]["payload"]["note"] = "changed"
    third = routes_module.review_session_event_snapshot("S-LIVE", session)
    assert third[1]["payload"] == {"note": "ok"}
    assert small == {"note": "ok"}


# ---- 消息接口带回会话 ----


class _Runtime:
    def chat_sync(self, messages, model, **kwargs):
        return {
            "provider": "test",
            "model": "test-model",
            "choices": [{"message": {"content": "需要人工确认。"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }


def _data(response):
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["code"] == 0, payload
    return payload["data"]


def test_messages_carry_the_session_etag_so_the_next_question_is_accepted(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_REVIEW_CONVERSATION_EXECUTION_MODE", "inline")
    monkeypatch.setenv("AICHECK_REVIEW_CONVERSATION_LLM_EXECUTION", "litellm")
    monkeypatch.setattr(routes_module, "qwen_runtime_client", lambda: _Runtime())
    repo.reset()
    repo.postgres_enabled = False
    repo.sync_postgres = None
    repo.postgres_dsn = None
    repo.sqlite_enabled = False
    repo.sqlite_path = None

    session = _data(
        client.post(
            f"/api/projects/{PROJECT_ID}/inspection/nodes/{NODE_ID}/review-sessions",
            headers={**OWNER, "Idempotency-Key": "live-session"},
            json={"currentTask": "核对焊工资格"},
        )
    )["session"]
    sid = session["id"]

    def ask(text: str, etag: str, key: str):
        return client.post(
            f"/api/review-sessions/{sid}/messages",
            headers={**OWNER, "Idempotency-Key": key, "If-Match": etag},
            json={"content": text},
        )

    _data(ask("焊工证是否在有效期内？", session["etag"], "live-ask-1"))
    listed = _data(client.get(f"/api/review-sessions/{sid}/messages", headers=OWNER))
    stored = repo.find_one("review_sessions", sid)
    # 回答落定把 revision 加了一；接口带回的 etag 必须是最新的那个
    assert listed["session"]["etag"] == routes_module.record_etag("review-session", stored)
    assert listed["session"]["etag"] != session["etag"]
    # 拿它直接问下一句，不用先刷新整个工作台
    _data(ask("那证书编号能查到吗？", listed["session"]["etag"], "live-ask-2"))
