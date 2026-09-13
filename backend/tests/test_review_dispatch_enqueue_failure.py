"""入队失败不许留下假「处理中」。

2026-09-13 线上事故：磁盘写满那阵子发起 30 个节点复核，27 个 review_run 已经以 queued
落库、但 celery 入队没成功，界面上一直转圈，两小时后手工跑 reconcile_orphan_ai_runs
才落终态。运行已落库之后再抛异常，就必须当场把它标成 failed_to_start。
"""
from __future__ import annotations

import pytest

from libs.integrations import task_dispatcher


def test_入队抛异常时运行落failed_to_start(monkeypatch):
    review_run = {"reviewRunId": "RRUN-TEST-1", "status": "queued", "revision": 1}
    monkeypatch.setattr(task_dispatcher, "dispatch_mode", lambda: "celery")
    monkeypatch.setenv("AICHECK_REVIEW_ORCHESTRATION", "inline")
    monkeypatch.setattr(
        "libs.review_orchestrator.dispatcher.prepare_review_run_for_async_dispatch",
        lambda run_id: review_run,
    )

    class _Boom:
        @staticmethod
        def delay(_run_id):
            raise RuntimeError("broker unreachable")

    monkeypatch.setattr("apps.worker.tasks.review_run_execute", _Boom)
    events: list[dict] = []
    monkeypatch.setattr("libs.review_orchestrator.dispatcher.append_review_event",
                        lambda run_id, **kw: events.append({"runId": run_id, **kw}))
    monkeypatch.setattr("libs.review_orchestrator.dispatcher.flush_state_records", lambda records: None)
    monkeypatch.setattr("libs.review_orchestrator.dispatcher.review_run_state_records", lambda run_id: [])

    result = task_dispatcher.dispatch_ai_recheck("P-1", 24, "AIRUN-1", force_async=True)

    assert result["status"] == "failed_to_start"
    assert result["errorCode"] == "CELERY_ENQUEUE_FAILED"
    assert review_run["status"] == "failed_to_start", "运行必须当场落终态，不能停在 queued"
    assert events and events[0]["event_type"] == "review_run.dispatch_failed"


def test_落终态本身失败时不吞掉原始语义(monkeypatch):
    """标失败的过程再出错，也不能把 dispatch 变成看起来成功。"""
    review_run = {"reviewRunId": "RRUN-TEST-2", "status": "queued"}
    monkeypatch.setattr("libs.review_orchestrator.dispatcher.bump_review_run_revision",
                        lambda run: (_ for _ in ()).throw(RuntimeError("db down")))
    task_dispatcher._mark_review_run_enqueue_failed(review_run, RuntimeError("broker unreachable"))
    assert review_run["status"] == "failed_to_start"
    assert review_run["dispatchErrorCode"] == "CELERY_ENQUEUE_FAILED"


@pytest.mark.parametrize("mode", ["inline"])
def test_入队成功时照常返回taskId(monkeypatch, mode):
    review_run = {"reviewRunId": "RRUN-TEST-3", "status": "queued"}
    monkeypatch.setattr(task_dispatcher, "dispatch_mode", lambda: "celery")
    monkeypatch.setenv("AICHECK_REVIEW_ORCHESTRATION", mode)
    monkeypatch.setattr(
        "libs.review_orchestrator.dispatcher.prepare_review_run_for_async_dispatch",
        lambda run_id: review_run,
    )

    class _Ok:
        @staticmethod
        def delay(_run_id):
            return type("R", (), {"id": "TASK-9"})()

    monkeypatch.setattr("apps.worker.tasks.review_run_execute", _Ok)
    result = task_dispatcher.dispatch_ai_recheck("P-1", 24, "AIRUN-3", force_async=True)
    assert result["taskId"] == "TASK-9" and result["status"] == "queued"
