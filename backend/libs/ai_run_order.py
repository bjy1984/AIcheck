"""AI 运行按活动时间排序——「最新一次复核」不能靠列表顺序碰运气。

2026-09-04 审计：测试项目3 节点 2 先后两次 AI 复核（00:48、01:40），节点页和 live-status
都把 00:48 那次当最新。ai_run 记录没有 createdAt，只有 startedAt/finishedAt；内存里
新建时 insert(0) 在前，但 API 进程按库重载后顺序就是库的顺序，谁在前不确定。
"""

from __future__ import annotations

from typing import Any


def ai_run_activity_at(run: dict[str, Any]) -> str:
    """finishedAt / updatedAt / startedAt / createdAt 里最晚的那个，字符串可比（同格式）。"""
    return max(
        str(run.get(key) or "")
        for key in ("finishedAt", "updatedAt", "startedAt", "createdAt")
    )


def sort_ai_runs_latest_first(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(runs, key=ai_run_activity_at, reverse=True)
