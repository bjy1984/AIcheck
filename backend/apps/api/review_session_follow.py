"""从按钮发起节点复核后，让工作区跟到新运行。

会话只在发消息/动作时换运行；按钮走 ai-recheck，不经会话，页面就一直停在旧运行上。
2026-09-24 灰度：节点 68 新运行已记下两个候选对象，页面却还显示 7 月那次，挑审查
对象的入口出不来。
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from libs.contracts.responses import server_time
from libs.node_document_identity import record_revision
from libs.review_orchestrator import review_run_state_records


def follow_new_review_run(
    session: dict[str, Any] | None, review_run_id: str
) -> Callable[[], dict[str, list[dict[str, Any]]]]:
    """把发起人当前打开的会话指到新运行，返回这次请求要落库的记录（运行 + 会话）。"""
    moved = session if session and session.get("activeReviewRunId") != review_run_id else None
    if moved:
        moved["activeReviewRunId"] = review_run_id
        moved["revision"] = record_revision(moved) + 1
        moved["updatedAt"] = server_time()

    def records() -> dict[str, list[dict[str, Any]]]:
        state = review_run_state_records(review_run_id)
        if moved:
            state.setdefault("review_sessions", []).append(moved)
        return state

    return records
