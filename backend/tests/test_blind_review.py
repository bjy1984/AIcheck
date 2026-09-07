"""P12 F4 盲审骨架：抽样稳定、盲审视图遮结论、常规审查人不能自审、橡皮图章指数落到指标。"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from apps.api.main import app
from libs.db.repository import repo
from libs.feedback.blind_review import (
    blind_task_view,
    record_blind_decision,
    rubber_stamp_index,
    sample_blind_review_tasks,
)
from libs.feedback.metrics import compute_feedback_metrics, render_markdown

client = TestClient(app)
NOW = datetime(2026, 9, 7, 9, 0, tzinfo=UTC)


def setup_function() -> None:
    repo.reset()


def _state(node_count: int = 20) -> dict:
    ai_runs = [
        {"id": f"RUN-{n}", "projectId": "P1", "nodeId": n, "finishedAt": "2026-09-05 10:00:00", "suggestion": {"result": "建议满足要求" if n % 4 else "建议不符合"}}
        for n in range(1, node_count + 1)
    ]
    opinions = [
        {"id": f"OPN-{n}", "projectId": "P1", "nodeId": n, "result": "满足要求", "reviewerName": "张工", "createdAt": "2026-09-06 09:00:00"}
        for n in range(1, node_count + 1)
    ]
    return {"ai_runs": ai_runs, "review_opinions": opinions, "blind_review_tasks": []}


def assert_ok(response):
    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] == 0, payload
    return payload["data"]


def test_sampling_is_ten_percent_and_stable_per_week_seed() -> None:
    state = _state()
    first = sample_blind_review_tasks(state, now=NOW)
    assert len(first) == 2  # 20 × 10%
    assert all(task["status"] == "open" and task["excludedReviewerName"] == "张工" for task in first)
    again = sample_blind_review_tasks(_state(), now=NOW)
    assert [t["nodeId"] for t in again] == [t["nodeId"] for t in first]
    # 同一节点未完成就不重复抽
    assert sample_blind_review_tasks(state, ratio=1.0, now=NOW) and len(state["blind_review_tasks"]) == 20


def test_blind_view_hides_ai_and_regular_conclusions() -> None:
    state = _state(5)
    task = sample_blind_review_tasks(state, ratio=0.2, now=NOW)[0]
    hidden = blind_task_view(task)
    assert "aiResult" not in hidden and "regularResult" not in hidden and "regularReviewerName" not in hidden
    assert blind_task_view(task, reveal=True)["aiResult"]


def test_decision_rules_and_rubber_stamp_index() -> None:
    state = _state(10)
    tasks = sample_blind_review_tasks(state, ratio=1.0, now=NOW)
    assert record_blind_decision(tasks[0], result="需补正", reviewer_name="张工", comment=None) == "盲审人不能是该节点的常规审查人。"
    for task in tasks:
        ai_agrees = "需补正" if task["aiResult"] == "建议不符合" else "满足要求"
        blind = "需补正" if task["nodeId"] % 2 else ai_agrees  # 一半盲审人跟 AI 不一致
        assert isinstance(record_blind_decision(task, result=blind, reviewer_name="李工", comment="独立判", now=NOW), dict)
    assert record_blind_decision(tasks[0], result="满足要求", reviewer_name="李工", comment=None) == "该盲审任务已完成。"
    index = rubber_stamp_index(state)
    assert index["sampleSize"] == 10
    # 常规意见全是"满足要求"，AI 有 2 个"建议不符合" → 常规差异率 0.2；盲审差异率按上面构造算出来
    assert index["regularDivergence"] == 0.2
    assert index["value"] == round(index["blindDivergence"] - 0.2, 4)
    metrics = compute_feedback_metrics(state)
    assert metrics["rubberStampIndex"] == index["value"]
    assert "橡皮图章指数" in render_markdown(metrics) and "待 F4 盲审" not in render_markdown(metrics)


def test_blind_review_endpoints_roundtrip() -> None:
    repo.state["ai_runs"].insert(0, {"id": "RUN-X", "projectId": repo.state["review_opinions"][0]["projectId"], "nodeId": 24, "finishedAt": "2026-09-05 10:00:00", "suggestion": {"result": "建议满足要求"}})
    sampled = assert_ok(client.post("/api/fde/blind-review/sample", json={"ratio": 1.0, "windowDays": None}, headers={"X-Role": "fde"}))
    assert sampled["sampled"] >= 1 and "aiResult" not in sampled["tasks"][0]
    task_id = sampled["tasks"][0]["id"]
    listed = assert_ok(client.get("/api/fde/blind-review/tasks", params={"status": "open"}, headers={"X-Role": "fde"}))
    assert any(t["id"] == task_id for t in listed["tasks"]) and listed["rubberStampIndex"]["sampleSize"] == 0
    decided = assert_ok(client.post(f"/api/fde/blind-review/tasks/{task_id}/decision", json={"result": "需补正", "reviewerName": "李工"}, headers={"X-Role": "fde"}))
    assert decided["task"]["status"] == "done" and decided["task"]["divergesFromAi"] is True
    assert decided["rubberStampIndex"]["sampleSize"] == 1
    forbidden = client.post("/api/fde/blind-review/sample", json={}, headers={"X-Role": "contractor"}).json()
    assert forbidden["code"] != 0
