"""异步派发的自动审查，finalize 必须能通过 ai_runs 判定完成。

自动审查 force_async 后，审查在 worker 里跑完只更新 ai_run，不一定回填
review_run（reviewRunId 为 None）→ childReviewRunIds 为空。finalize 若只看
review_runs，会让 project_review_run 永远 running、永不收口
（2026-08-29 生产实测：两个子 AI 运行都「完成」，PRR 却卡在 running）。
"""

from __future__ import annotations

from libs.auto_review import finalize_project_review_run


def _state(ai_runs):
    return {"review_runs": [], "ai_runs": ai_runs}


def test_finalize_completes_via_ai_runs_when_review_runs_absent() -> None:
    project_run = {
        "projectReviewRunId": "PRR-TEST-1",
        "expectedNodeIds": [3, 35],
        "childReviewRunIds": [],  # 异步派发未回填
        "childAiRunIds": ["AIRUN-3", "AIRUN-35"],
        "failedNodeIds": [],
    }
    state = _state([
        {"id": "AIRUN-3", "nodeId": 3, "status": "完成"},
        {"id": "AIRUN-35", "nodeId": 35, "status": "完成"},
    ])
    result = finalize_project_review_run(state, project_run)
    assert result["status"] == "completed", "两个子 AI 运行都完成，PRR 必须收口为 completed"
    assert result["pendingNodeIds"] == []
    assert result["finishedAt"]


def test_finalize_stays_running_while_ai_run_pending() -> None:
    project_run = {
        "projectReviewRunId": "PRR-TEST-2",
        "expectedNodeIds": [3, 35],
        "childReviewRunIds": [],
        "childAiRunIds": ["AIRUN-3", "AIRUN-35"],
        "failedNodeIds": [],
    }
    state = _state([
        {"id": "AIRUN-3", "nodeId": 3, "status": "完成"},
        {"id": "AIRUN-35", "nodeId": 35, "status": "运行中"},
    ])
    result = finalize_project_review_run(state, project_run)
    assert result["status"] == "running", "还有子运行没跑完，不能收口"
    assert 35 in result["pendingNodeIds"]


def test_finalize_marks_failed_via_ai_runs() -> None:
    project_run = {
        "projectReviewRunId": "PRR-TEST-3",
        "expectedNodeIds": [3],
        "childReviewRunIds": [],
        "childAiRunIds": ["AIRUN-3"],
        "failedNodeIds": [],
    }
    state = _state([{"id": "AIRUN-3", "nodeId": 3, "status": "失败"}])
    result = finalize_project_review_run(state, project_run)
    assert result["status"] == "failed"
