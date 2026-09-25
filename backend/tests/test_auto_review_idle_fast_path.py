"""自动审查周期任务没活就快速返回（2026-09-25）。

四个任务每分钟各跑一次，原来不论有没有活都先整库载入，线上每次 9–28 秒、结果全空，
常年占住一个核，把单进程 API 挤慢。没活时只载四个小集合就返回，也不落库；有活照旧。
"""
from __future__ import annotations

from typing import Any

import pytest

from apps.worker import tasks


@pytest.fixture()
def calls(monkeypatch):
    record: dict[str, list[Any]] = {"load": [], "flush": []}
    state: dict[str, list[dict[str, Any]]] = {key: [] for key in tasks.AUTO_REVIEW_PROBE_KEYS}

    def fake_load(keys=None):
        record["load"].append(set(keys) if keys else None)
        for key in keys or tasks.AUTO_REVIEW_PROBE_KEYS:
            tasks.repo.state[key] = [dict(row) for row in state.get(key, [])]

    monkeypatch.setattr(tasks, "load_state", fake_load)
    monkeypatch.setattr(tasks, "flush_state", lambda *a, **k: record["flush"].append((a, k)))
    record["state"] = state  # type: ignore[assignment]
    return record


@pytest.mark.parametrize(("task", "empty"), [
    (tasks.auto_review_consume_evidence_events, {"completedEventIds": [], "skippedEventIds": [], "createdCandidateIds": []}),
    (tasks.auto_review_scan_due_projects, {"dueProjectIds": [], "createdCandidateIds": []}),
    (tasks.auto_review_start_pending_candidates, {"projectReviewRunIds": [], "skippedCandidateIds": []}),
    (tasks.auto_review_finalize_project_runs, {"finalizedProjectReviewRunIds": [], "runningProjectReviewRunIds": []}),
])
def test_an_idle_task_loads_only_the_small_collections_and_writes_nothing(calls, task, empty) -> None:
    assert task.run() == empty
    assert calls["load"] == [tasks.AUTO_REVIEW_PROBE_KEYS], "没活不许整库或大集合载入"
    assert calls["flush"] == [], "没活不落库"


def test_finished_or_non_pending_rows_count_as_idle(calls) -> None:
    calls["state"]["auto_review_outbox"].append({"id": "E1", "status": "completed"})
    calls["state"]["auto_review_candidates"].append({"id": "C1", "status": "started"})
    calls["state"]["project_review_runs"].append({"id": "R1", "status": "running", "finishedAt": "2026-09-25"})
    assert tasks.auto_review_consume_evidence_events.run()["completedEventIds"] == []
    assert tasks.auto_review_start_pending_candidates.run()["projectReviewRunIds"] == []
    assert tasks.auto_review_finalize_project_runs.run()["runningProjectReviewRunIds"] == []
    assert all(keys == tasks.AUTO_REVIEW_PROBE_KEYS for keys in calls["load"])


def test_a_pending_candidate_still_gets_the_full_load(calls, monkeypatch) -> None:
    calls["state"]["auto_review_candidates"].append({"id": "C1", "status": "pending"})
    monkeypatch.setattr(tasks, "dispatch_pending_auto_review_candidates",
                        lambda state, start_node_review: {"projectReviewRunIds": ["PRR-1"], "skippedCandidateIds": []})
    assert tasks.auto_review_start_pending_candidates.run() == {"projectReviewRunIds": ["PRR-1"], "skippedCandidateIds": []}
    assert calls["load"] == [tasks.AUTO_REVIEW_PROBE_KEYS, None], "有活照旧整库载入"
    assert len(calls["flush"]) == 1


def test_pending_events_and_running_runs_are_not_idle(calls, monkeypatch) -> None:
    calls["state"]["auto_review_outbox"].append({"id": "E1", "status": "retry_pending"})
    calls["state"]["project_review_runs"].append({"id": "R1", "status": "partial"})
    monkeypatch.setattr(tasks, "consume_auto_review_events", lambda state, now: {"completedEventIds": ["E1"]})
    monkeypatch.setattr(tasks, "finalize_running_project_review_runs", lambda state: {"runningProjectReviewRunIds": ["R1"]})
    assert tasks.auto_review_consume_evidence_events.run() == {"completedEventIds": ["E1"]}
    assert tasks.auto_review_finalize_project_runs.run() == {"runningProjectReviewRunIds": ["R1"]}
    assert tasks.AUTO_REVIEW_STATE_KEYS in calls["load"]
