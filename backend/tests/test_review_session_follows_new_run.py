"""从按钮发起节点复核后，工作区要跟到新运行（2026-09-24 灰度）。

会话只在发消息/动作时换运行；按钮走 ai-recheck，不经会话。节点 68 的新运行已记下
两个候选对象，页面却一直显示 7 月那次，挑审查对象的入口出不来。
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from apps.api.main import app
from libs.db.repository import repo
from libs.integrations import task_dispatcher
from tests.test_contract import allow_test_ai_dispatch, seed_reviewed_node_24

client = TestClient(app)
PROJECT_ID = "P-2026-HDCP-001"
HEADERS = {"X-Role": "inspection", "X-User-Id": "USER-INSPECTION-001"}


def setup_function() -> None:
    repo.reset()
    repo.postgres_enabled = False
    repo.sync_postgres = None
    repo.postgres_dsn = None
    repo.sqlite_enabled = False
    repo.sqlite_path = None


def _data(response):
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["code"] == 0, payload
    return payload["data"]


def _workspace():
    return _data(client.get(f"/api/projects/{PROJECT_ID}/inspection/nodes/24/review-workspace", headers=HEADERS))


def test_starting_a_review_moves_the_open_workspace_to_the_new_run(monkeypatch) -> None:
    seed_reviewed_node_24(PROJECT_ID)
    allow_test_ai_dispatch(monkeypatch)
    repo.state["review_runs"].insert(0, {"id": "RRUN-OLD", "reviewRunId": "RRUN-OLD", "projectId": PROJECT_ID,
                                         "nodeId": 24, "status": "waiting_human_review",
                                         "tenantId": "TENANT-DEFAULT", "createdAt": "2026-07-07 01:27:36"})
    session = _data(client.post(f"/api/projects/{PROJECT_ID}/inspection/nodes/24/review-sessions",
                                headers={**HEADERS, "Idempotency-Key": "follow-new-run-session"},
                                json={"currentTask": "焊工资格", "reviewRunId": "RRUN-OLD"}))["session"]
    assert _workspace()["activeReviewRun"]["reviewRunId"] == "RRUN-OLD"

    def dispatch(project_id, node_id, run_id, **_kwargs):
        repo.state["review_runs"].insert(0, {"id": "RRUN-NEW", "reviewRunId": "RRUN-NEW", "projectId": project_id,
                                             "nodeId": node_id, "status": "queued", "tenantId": "TENANT-DEFAULT",
                                             "objectCandidates": [{"objectId": "PL8303-100"}, {"objectId": "PL8306-100"}]})
        return {"mode": "test", "taskId": f"TEST-{run_id}", "reviewRunId": "RRUN-NEW"}

    monkeypatch.setattr(task_dispatcher, "dispatch_ai_recheck", dispatch)
    _data(client.post(f"/api/projects/{PROJECT_ID}/inspection/nodes/24/ai-recheck",
                      headers={**HEADERS, "Idempotency-Key": "follow-new-run-recheck"}, json={}))

    after = _workspace()
    assert after["session"]["id"] == session["id"]
    assert after["activeReviewRun"]["reviewRunId"] == "RRUN-NEW"
    assert [item["objectId"] for item in after["activeReviewRun"]["objectCandidates"]] == ["PL8303-100", "PL8306-100"]


def test_a_review_started_without_an_open_session_creates_nothing(monkeypatch) -> None:
    seed_reviewed_node_24(PROJECT_ID)
    allow_test_ai_dispatch(monkeypatch)
    monkeypatch.setattr(task_dispatcher, "dispatch_ai_recheck",
                        lambda project_id, node_id, run_id, **_kwargs: {"mode": "test", "taskId": "T", "reviewRunId": "RRUN-X"})
    before = len(repo.state.get("review_sessions", []))
    _data(client.post(f"/api/projects/{PROJECT_ID}/inspection/nodes/24/ai-recheck",
                      headers={**HEADERS, "Idempotency-Key": "no-session-recheck"}, json={}))
    assert len(repo.state.get("review_sessions", [])) == before
