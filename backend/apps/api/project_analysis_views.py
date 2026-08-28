"""一键分析结果在监检两处界面的只读视图。

从 routes.py 挪出来的两个函数（单体棘轮不允许 routes 再长）：

- node_project_analysis_view：监检工作台节点包里的「全工程一键分析」摘要；
- project_analysis_results_for_review_workspace：AI 审查页工作台载荷里的
  节点级结果列表——前端把它们**合成为对话消息**插入会话流
  （见 frontend/src/views/AIReviewB/projectAnalysisConversation.ts）。
  合成发生在前端、不落库，所以天然不污染 review_sessions、
  也不碰任何对话绑定；这里只负责按节点取数。

review_run_view 由调用方注入：它住在 routes.py，直接 import 会成环。
"""

from __future__ import annotations

from typing import Any, Callable

from libs.db.repository import repo
from libs.project_analysis.domain import project_analysis_status_view
from libs.security.tenant import tenant_id_for_record


def _record_time(record: dict[str, Any] | None) -> str:
    if not record:
        return ""
    for key in ("updatedAt", "finishedAt", "completedAt", "createdAt"):
        value = record.get(key)
        if value:
            return str(value)
    return ""


def _latest(records: list[dict[str, Any]]) -> dict[str, Any] | None:
    return max(records, key=_record_time) if records else None


def node_project_analysis_view(
    project_id: str,
    node_id: int,
    *,
    tenant_id: str,
    review_run_view: Callable[[dict[str, Any]], dict[str, Any]],
) -> dict[str, Any] | None:
    snapshot_ids = {
        str(item.get("projectAnalysisSnapshotId") or item.get("id") or "")
        for item in repo.state.get("project_analysis_snapshots", [])
        if str(item.get("projectId") or "") == project_id
        and int(node_id) in {int(value) for value in item.get("nodeIds") or []}
    }
    runs = [
        item
        for item in repo.state.get("project_analysis_runs", [])
        if str(item.get("projectId") or "") == project_id
        and str(item.get("projectAnalysisSnapshotId") or "") in snapshot_ids
        and tenant_id_for_record(item) == tenant_id
    ]
    latest_run = _latest(runs)
    if not latest_run:
        return None
    project_analysis_run_id = str(latest_run.get("projectAnalysisRunId") or "")
    node_review = _latest(
        [
            item
            for item in repo.state.get("review_runs", [])
            if str(item.get("projectAnalysisRunId") or "") == project_analysis_run_id
            and int(item.get("nodeId") or 0) == int(node_id)
            and tenant_id_for_record(item) == tenant_id
        ]
    )
    return {
        "run": project_analysis_status_view(latest_run),
        "nodeReview": review_run_view(node_review) if node_review else None,
    }


def project_analysis_results_for_review_workspace(
    project_id: str,
    node_id: int,
    *,
    tenant_id: str,
) -> list[dict[str, Any]]:
    rows = [
        item
        for item in repo.state.get("review_runs", [])
        if str(item.get("triggerType") or "") == "manual_full_project_analysis"
        and str(item.get("projectId") or "") == project_id
        and int(item.get("nodeId") or 0) == int(node_id)
        and tenant_id_for_record(item) == tenant_id
    ]
    rows.sort(
        key=lambda item: str(
            item.get("finishedAt") or item.get("updatedAt") or item.get("createdAt") or ""
        ),
        reverse=True,
    )
    return [
        {
            "reviewRunId": item.get("reviewRunId") or item.get("id"),
            "projectAnalysisRunId": item.get("projectAnalysisRunId"),
            "status": item.get("status"),
            "reviewResult": item.get("reviewResult"),
            "findingDrafts": repo.clone(item.get("findingDrafts") or []),
            "createdAt": item.get("createdAt"),
            "finishedAt": item.get("finishedAt"),
        }
        for item in rows[:20]
    ]
