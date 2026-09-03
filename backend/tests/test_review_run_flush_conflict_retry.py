"""异步编排的收尾落库撞上并发修改时要能自愈，不能让跑完的审查停在 queued。

2026-09-03 实测：worker 起任务时加载了 ai_run，API 进程在派发返回后回填了同一行，
worker 跑完收尾整批 flush → ai_runs baseline 不符 → 事务回滚 → review_run 永远 queued。
"""

from __future__ import annotations

from libs.db.repository import ConcurrentPersistenceError
from libs.review_orchestrator import persistence_retry as execution


def test_conflict_retry_reloads_and_merges_then_flushes(monkeypatch) -> None:
    stale_ai_run = {"id": "AIRUN-1", "status": "完成", "findingDrafts": [{"id": "F1"}], "reviewRunId": "RRUN-1", "workflowId": ""}
    inflight_run = {"reviewRunId": "RRUN-1", "id": "RRUN-1", "status": "waiting_human_review", "aiRunId": "AIRUN-1"}
    monkeypatch.setattr(execution.repo, "state", {"ai_runs": [stale_ai_run], "review_runs": [inflight_run]}, raising=False)
    monkeypatch.setattr(execution, "postgres_persistence_configured", lambda: True)
    monkeypatch.setattr(execution.repo, "persistence_object_id", lambda collection, row, index: str(row.get("id") or row.get("reviewRunId")))
    unpinned: list[tuple[str, str]] = []
    monkeypatch.setattr(execution.repo, "unpin_object", lambda c, i: unpinned.append((c, i)))

    def fake_refresh(keys):
        # 库里的新副本：API 进程回填过 workflowId，并且状态仍是推理中
        execution.repo.state["ai_runs"] = [{"id": "AIRUN-1", "status": "推理中", "workflowId": "WF-1", "reviewRunId": "RRUN-1"}]
        execution.repo.state["review_runs"] = [{"reviewRunId": "RRUN-1", "id": "RRUN-1", "status": "queued", "aiRunId": "AIRUN-1"}]

    monkeypatch.setattr(execution.repo, "refresh_collections_incrementally", fake_refresh)
    calls: list[dict] = []

    def fake_flush(records):
        calls.append({k: [dict(r) for r in v] for k, v in records.items()})
        if len(calls) == 1:
            raise ConcurrentPersistenceError("Concurrent persistence update detected for ai_runs/AIRUN-1")

    monkeypatch.setattr(execution, "flush_state_records", fake_flush)
    records = {"ai_runs": [stale_ai_run], "review_runs": [inflight_run], "review_events": [{"id": "EV-1", "reviewRunId": "RRUN-1"}]}

    execution.flush_review_run_records_with_conflict_retry("RRUN-1", records, inflight_runs={})

    assert len(calls) == 2, "第一次冲突后必须重试一次"
    retried_ai_run = calls[1]["ai_runs"][0]
    assert retried_ai_run["status"] == "完成", "执行结果必须覆盖回新载入的行"
    assert retried_ai_run["findingDrafts"] == [{"id": "F1"}]
    assert retried_ai_run["workflowId"] == "WF-1", "并发方写的 workflowId 本次没写，要保留库里的值"
    assert calls[1]["review_runs"][0]["status"] == "waiting_human_review"
    assert calls[1]["review_events"] == [{"id": "EV-1", "reviewRunId": "RRUN-1"}]
    assert ("ai_runs", "AIRUN-1") in unpinned and ("review_runs", "RRUN-1") in unpinned
    # 重试后 records 里指向的是 state 里的新对象
    assert records["ai_runs"][0] is execution.repo.state["ai_runs"][0]


def test_conflict_retry_gives_up_after_attempts(monkeypatch) -> None:
    monkeypatch.setattr(execution, "postgres_persistence_configured", lambda: True)
    monkeypatch.setattr(execution.repo, "state", {"ai_runs": [], "review_runs": []}, raising=False)
    monkeypatch.setattr(execution.repo, "refresh_collections_incrementally", lambda keys: None)
    monkeypatch.setattr(execution.repo, "persistence_object_id", lambda c, r, i: str(r.get("id")))
    monkeypatch.setattr(execution.repo, "unpin_object", lambda c, i: None)

    def always_conflict(records):
        raise ConcurrentPersistenceError("Concurrent persistence update detected for ai_runs/X")

    monkeypatch.setattr(execution, "flush_state_records", always_conflict)
    try:
        execution.flush_review_run_records_with_conflict_retry("RRUN-X", {"ai_runs": [{"id": "X"}]}, attempts=2)
    except ConcurrentPersistenceError:
        pass
    else:
        raise AssertionError("重试用尽后必须把冲突抛给调用方")
