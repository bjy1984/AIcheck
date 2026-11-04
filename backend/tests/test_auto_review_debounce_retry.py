"""2026-11-03 自动重审审计后的三处修复：防抖、失败重试、周期锁心跳。"""
from __future__ import annotations

import inspect

from libs import auto_review
from libs.auto_review import dispatch_pending_auto_review_candidates, upsert_auto_review_candidate


def _state(debounce: int = 300) -> dict:
    return {
        "auto_review_candidates": [],
        "auto_review_policies": [{"tenantId": "T", "projectId": "P", "enabled": True, "revision": 1,
                                  "triggerModes": ["ocr_mounted"], "debounceSeconds": debounce}],
        "project_review_runs": [],
    }


def _upsert(state: dict, hash_: str, debounce: int = 300, node: int = 9) -> dict:
    candidate, _ = upsert_auto_review_candidate(
        state, tenant_id="T", project_id="P", node_id=node, evidence_snapshot_hash=hash_,
        policy_revision=1, trigger_type="ocr_mounted", debounce_seconds=debounce)
    return candidate


def test_防抖期内不派发_一阵上传只审最后一个证据状态(monkeypatch):
    state = _state()
    first = _upsert(state, "H1")
    second = _upsert(state, "H2")
    assert first["status"] == "superseded" and second["status"] == "pending"
    started: list[int] = []
    result = dispatch_pending_auto_review_candidates(state, start_node_review=lambda p, n, m: started.append(n) or {"aiRunId": "A"})
    assert started == [] and result["projectReviewRunIds"] == [], "防抖期没到，不派"
    monkeypatch.setattr(auto_review, "server_time", lambda: "2999-01-01 00:00:00")
    dispatch_pending_auto_review_candidates(state, start_node_review=lambda p, n, m: started.append(n) or {"aiRunId": "A"})
    assert started == [9] and second["status"] == "dispatched" and first["status"] == "superseded"


def test_证据改回原状态时旧候选重新成为待派():
    state = _state(debounce=0)
    a = _upsert(state, "HA", debounce=0)
    b = _upsert(state, "HB", debounce=0)
    a_again = _upsert(state, "HA", debounce=0)
    assert a_again is a and a["status"] == "pending" and b["status"] == "superseded"


def test_别的节点的待派候选不受影响():
    state = _state(debounce=0)
    other = _upsert(state, "HX", debounce=0, node=4)
    _upsert(state, "HY", debounce=0, node=9)
    assert other["status"] == "pending"


def test_派发失败退回待派并延后_三次后才算失败(monkeypatch):
    state = _state(debounce=0)
    candidate = _upsert(state, "H1", debounce=0)

    def boom(project_id, node_id, metadata):
        raise RuntimeError("broker down")

    dispatch_pending_auto_review_candidates(state, start_node_review=boom)
    assert candidate["status"] == "pending" and candidate["attemptCount"] == 1
    assert candidate["lastErrorType"] == "RuntimeError"
    assert candidate["availableAt"] > auto_review.server_time(), "退避期内不立刻重派"
    for attempt in (2, 3):
        monkeypatch.setattr(auto_review, "server_time", lambda: "2999-01-01 00:00:00")
        dispatch_pending_auto_review_candidates(state, start_node_review=boom)
        assert candidate["attemptCount"] == attempt
    assert candidate["status"] == "failed"


def test_四个自动审查周期任务都开了锁心跳():
    from apps.worker import tasks

    source = inspect.getsource(tasks)
    for name in ("auto_review_consume_evidence_events", "auto_review_scan_due_projects",
                 "auto_review_start_pending_candidates", "auto_review_finalize_project_runs"):
        assert f'lambda _self: "{name}", keepalive=True)' in source, name
