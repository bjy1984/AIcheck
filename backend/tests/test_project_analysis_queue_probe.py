"""排队不是僵尸：一键分析在 llm.remote 里等 worker 时，不能被状态视图和收敛器判死。

2026-09-03 审计：单槽位 llm worker 前面排着 OCR 抽取/节点复核，运行 queued 超过
30 分钟就被收敛成 failed，用户看到的就是「一键分析不起作用」。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from libs.contracts.responses import SERVER_TZ
from libs.project_analysis.domain import (
    project_analysis_status_view,
    reap_stalled_project_analysis_runs,
)
from libs.project_analysis.queue_probe import pending_task_ids, queue_status_for_task


class _FakeRedis:
    """LPUSH 入队的列表：index 0 最新，尾部最早。"""

    def __init__(self, lists: dict[str, list[str]]):
        self.lists = lists

    def lrange(self, name, start, end):
        return [json.dumps({"headers": {"id": item}}).encode() for item in self.lists.get(name, [])]


def _stale(minutes: int) -> str:
    return (datetime.now(SERVER_TZ) - timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M:%S")


def test_按消费顺序列出队列任务_高优先级子队列在前_同队列先进先出():
    client = _FakeRedis({"llm.remote": ["new-0", "old-0"], "llm.remote:1": ["new-1", "old-1"]})
    assert pending_task_ids("llm.remote", client=client) == ["old-0", "new-0", "old-1", "new-1"]
    assert queue_status_for_task("old-1", client=client) == {"pending": True, "ahead": 2}
    assert queue_status_for_task("gone", client=client) == {"pending": False, "ahead": None}
    assert queue_status_for_task(None, client=client) == {"pending": None, "ahead": None}


def test_redis问不到时fail_open():
    class Broken:
        def lrange(self, *_args):
            raise ConnectionError("redis down")

    assert pending_task_ids("llm.remote", client=Broken()) is None
    assert queue_status_for_task("x", client=Broken()) == {"pending": None, "ahead": None}


def test_还在队列里的运行_状态视图不判僵尸并报排队位置():
    run = {
        "projectAnalysisRunId": "PARUN-Q",
        "phase": "queued",
        "status": "queued",
        "queueTaskId": "task-q",
        "lastHeartbeatAt": _stale(45),
        "updatedAt": _stale(45),
        "createdAt": _stale(46),
    }
    view = project_analysis_status_view(run, queue_probe=lambda _tid: {"pending": True, "ahead": 3})
    assert view["phase"] == "queued" and view["queueAhead"] == 3
    # 队列里已经没有它、又超时：仍按僵尸显示
    view = project_analysis_status_view(run, queue_probe=lambda _tid: {"pending": False, "ahead": None})
    assert view["phase"] == "failed" and view["errorCode"] == "PROJECT_ANALYSIS_RUN_STALLED"
    # 探针挂了：退回时间阈值
    view = project_analysis_status_view(run, queue_probe=lambda _tid: (_ for _ in ()).throw(RuntimeError()))
    assert view["phase"] == "failed"


def test_收敛器跳过仍在排队的运行():
    queued_alive = {
        "projectAnalysisRunId": "PARUN-ALIVE",
        "phase": "queued",
        "status": "queued",
        "queueTaskId": "task-alive",
        "lastHeartbeatAt": "2026-08-28 11:00:00",
        "updatedAt": "2026-08-28 11:00:00",
        "revision": 1,
    }
    queued_gone = {
        "projectAnalysisRunId": "PARUN-GONE",
        "phase": "queued",
        "status": "queued",
        "queueTaskId": "task-gone",
        "lastHeartbeatAt": "2026-08-28 11:00:00",
        "updatedAt": "2026-08-28 11:00:00",
        "revision": 1,
    }
    state = {"project_analysis_runs": [queued_alive, queued_gone], "project_analysis_events": []}
    reaped = reap_stalled_project_analysis_runs(
        state,
        now=datetime(2026, 8, 28, 12, 0, tzinfo=SERVER_TZ),
        stall_timeout=timedelta(minutes=30),
        queue_alive=lambda tid: tid == "task-alive",
    )
    assert [r["projectAnalysisRunId"] for r in reaped] == ["PARUN-GONE"]
    assert queued_alive["phase"] == "queued"
    assert queued_gone["phase"] == "failed"
