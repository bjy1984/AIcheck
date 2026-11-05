"""节点审计任务队列：每个节点最近一次 AI 复核走到哪了。

2026-11-05 用户：「现在没法知道节点审计的任务状态」。复核是排队跑的——生产上
llm.remote 一个槽位依次执行，每个节点 5–13 分钟，一次排 8 个节点队尾要等近一小时
（2026-10-29 实测）。发起之后，监检只能逐个点进节点看转圈，不知道哪个在跑、
哪个还在排、哪个已经出结果等人确认、哪个失败了要重来。

这里按节点取最近一次复核（ai_run 为准，带上它关联的 review_run），算出一个
对外的任务状态：

- queued       排队中（能问到 broker 时带「前面还有几个」）
- running      审查中
- needs_input  审查停下来等人补信息（R12 公示平台核验、R19 语义证据确认）
- failed       失败（含排队后长时间没进展、执行进程已不在的——和 review_run_view 同一口径）
- cancelled    已取消
- done         已出结果；带结论分组，以及监检是否已经在它之后给了人工结论

只读，不改库。卡死判定只改展示，与 review_run_view 一致：库里那份是执行留痕。
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime
from typing import Any

from libs.ai_run_order import sort_ai_runs_latest_first
from libs.inspection_node_conclusion import node_conclusion

STATES = ("running", "queued", "needs_input", "failed", "done", "cancelled")

_QUEUED = {"queued", "dispatched", "排队中"}
_RUNNING = {"running", "retrying", "resuming", "推理中", "运行中", "执行中"}
_NEEDS_INPUT = {"waiting_human_input", "waiting_human_input_required"}
_FAILED = {"failed", "failed_to_start", "失败", "已失败"}
_CANCELLED = {"cancelled", "cancel_requested", "cancelling", "已取消"}
_DONE = {
    "waiting_human_review",
    "pending_human_review",
    "completed",
    "succeeded",
    "passed",
    "finished",
    "accepted_by_human",
    "edited_by_human",
    "成功",
    "完成",
    "已完成",
}
_SUGGESTION_GROUP = {"满足要求": "passed", "符合": "passed", "需补正": "failed", "不符合": "failed"}


def _parse_time(value: Any) -> datetime | None:
    text = str(value or "").strip().replace("T", " ")[:19]
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d %H:%M:%S")  # noqa: DTZ007 -- 与 server_time 同为服务器本地时间口径
    except ValueError:
        return None


def _seconds(start: Any, end: datetime | Any) -> int | None:
    begin = _parse_time(start)
    finish = end if isinstance(end, datetime) else _parse_time(end)
    if begin is None or finish is None:
        return None
    return max(0, int((finish - begin).total_seconds()))


def _record_time(item: dict[str, Any] | None) -> str:
    item = item or {}
    return str(item.get("updatedAt") or item.get("createdAt") or "")


def _status_key(value: Any) -> str:
    text = str(value or "").strip()
    return text.lower() if text.isascii() else text


def _state_of(
    review: dict[str, Any] | None,
    ai_run: dict[str, Any] | None,
    looks_abandoned: Callable[[dict[str, Any]], bool],
    queue_status: Callable[[dict[str, Any]], dict[str, Any]],
) -> tuple[str, int | None, bool]:
    """(state, queueAhead, stale)。review_run 的英文状态优先，没有才看 ai_run。"""
    status = _status_key((review or {}).get("status") or (ai_run or {}).get("status"))
    if review and status in _QUEUED:
        queue = queue_status(review) or {}
        if queue.get("pending"):
            return "queued", queue.get("ahead"), False
        # 不在 broker 队列里、又很久没动：执行进程已经不在了
        if looks_abandoned(review):
            return "failed", None, True
        return "queued", None, False
    if status in _QUEUED:
        return "queued", None, False
    if status in _RUNNING:
        if review and looks_abandoned(review):
            return "failed", None, True
        return "running", None, False
    if status in _NEEDS_INPUT:
        return "needs_input", None, False
    if status in _FAILED:
        return "failed", None, False
    if status in _CANCELLED:
        return "cancelled", None, False
    if status in _DONE:
        return "done", None, False
    # 认不出的状态：跑完了（有结束时间）就当已出结果，否则当还在跑——不冒充失败
    finished = (review or {}).get("finishedAt") or (ai_run or {}).get("finishedAt")
    return ("done" if finished else "running"), None, False


def _result_of(
    review: dict[str, Any] | None, ai_run: dict[str, Any] | None
) -> dict[str, Any] | None:
    if review and review.get("atomicCheckOutcomes"):
        conclusion = node_conclusion(review, None)
        if conclusion.get("group") != "not_started":
            return {
                "group": conclusion["group"],
                "notApplicable": bool(conclusion.get("notApplicable")),
            }
    suggestion = str(((ai_run or {}).get("suggestion") or {}).get("result") or "").strip()
    if suggestion:
        return {"group": _SUGGESTION_GROUP.get(suggestion, "needs_human"), "notApplicable": False}
    return None


def _error_of(
    review: dict[str, Any] | None, ai_run: dict[str, Any] | None, stale: bool
) -> str | None:
    if stale:
        return "任务排队后长时间没有进展，可能是执行进程已重启；请进入节点重新发起复核。"
    for record in (review, ai_run):
        for key in ("errorMessage", "failureReason", "dispatchErrorMessage"):
            text = str((record or {}).get(key) or "").strip()
            if text:
                return text[:300]
    return None


def build_node_audit_tasks(
    *,
    ai_runs: Iterable[dict[str, Any]],
    review_runs: Iterable[dict[str, Any]],
    opinions: Iterable[dict[str, Any]],
    nodes: Iterable[dict[str, Any]],
    now: datetime,
    looks_abandoned: Callable[[dict[str, Any]], bool],
    queue_status: Callable[[dict[str, Any]], dict[str, Any]],
    finished_limit: int = 50,
) -> dict[str, Any]:
    """入参已按项目、租户、节点范围筛过。每个节点至多一行：它最近一次复核。"""
    node_by_id = {
        int(node.get("nodeId") or 0): node for node in nodes if node.get("nodeId") is not None
    }
    ai_by_node: dict[int, list[dict[str, Any]]] = {}
    for item in ai_runs:
        node_id = int(item.get("nodeId") or 0)
        if node_id in node_by_id:
            ai_by_node.setdefault(node_id, []).append(item)
    reviews_by_node: dict[int, list[dict[str, Any]]] = {}
    review_by_id: dict[str, dict[str, Any]] = {}
    review_by_ai_run: dict[str, dict[str, Any]] = {}
    for item in review_runs:
        node_id = int(item.get("nodeId") or 0)
        if node_id not in node_by_id:
            continue
        reviews_by_node.setdefault(node_id, []).append(item)
        run_id = str(item.get("reviewRunId") or item.get("id") or "")
        if run_id:
            review_by_id[run_id] = item
        if item.get("aiRunId"):
            review_by_ai_run[str(item["aiRunId"])] = item
    latest_opinion: dict[int, dict[str, Any]] = {}
    for item in opinions:
        node_id = int(item.get("nodeId") or 0)
        if node_id in node_by_id and _record_time(item) >= _record_time(
            latest_opinion.get(node_id)
        ):
            latest_opinion[node_id] = item

    rows: list[dict[str, Any]] = []
    for node_id in sorted(set(ai_by_node) | set(reviews_by_node)):
        ai_run = (
            (sort_ai_runs_latest_first(ai_by_node[node_id]) or [None])[0]
            if node_id in ai_by_node
            else None
        )
        review = None
        if ai_run is not None:
            review = review_by_id.get(str(ai_run.get("reviewRunId") or "")) or review_by_ai_run.get(
                str(ai_run.get("id") or "")
            )
        elif reviews_by_node.get(node_id):
            review = max(
                reviews_by_node[node_id], key=lambda item: str(item.get("createdAt") or "")
            )
        state, queue_ahead, stale = _state_of(review, ai_run, looks_abandoned, queue_status)
        created_at = (
            (review or {}).get("createdAt")
            or (ai_run or {}).get("createdAt")
            or (ai_run or {}).get("startedAt")
        )
        # ai_run 建出来就带 startedAt，排队中的那一刻其实还没开始跑
        started_at = (
            None
            if state == "queued"
            else (review or {}).get("startedAt") or (ai_run or {}).get("startedAt")
        )
        finished_at = (review or {}).get("finishedAt") or (ai_run or {}).get("finishedAt")
        if state in {"running", "needs_input"}:
            elapsed = _seconds(started_at or created_at, now)
        elif state == "queued":
            elapsed = None
        else:
            elapsed = _seconds(started_at or created_at, finished_at) if finished_at else None
        opinion = latest_opinion.get(node_id)
        settled_at = str(finished_at or created_at or "")
        confirmed = bool(opinion) and state == "done" and _record_time(opinion) >= settled_at
        review_mode = str(
            (review or {}).get("reviewMode") or (ai_run or {}).get("reviewMode") or "formal"
        )
        node = node_by_id[node_id]
        rows.append(
            {
                "nodeId": node_id,
                "nodeName": node.get("name") or f"节点 {node_id}",
                "groupName": node.get("groupName") or node.get("group") or None,
                "aiRunId": (ai_run or {}).get("id"),
                "reviewRunId": (review or {}).get("reviewRunId") or (review or {}).get("id"),
                "state": state,
                "rawStatus": (review or {}).get("status") or (ai_run or {}).get("status"),
                "stale": stale,
                "reviewMode": review_mode,
                "advisoryOnly": bool(
                    (review or {}).get("advisoryOnly") or (ai_run or {}).get("advisoryOnly")
                )
                or review_mode == "gap_precheck",
                "queueAhead": queue_ahead,
                "currentStep": (review or {}).get("currentStep"),
                "createdAt": created_at,
                "startedAt": started_at,
                "finishedAt": finished_at if state in {"done", "failed", "cancelled"} else None,
                "waitSeconds": _seconds(created_at, now) if state == "queued" else None,
                "elapsedSeconds": elapsed,
                "errorMessage": _error_of(review, ai_run, stale) if state == "failed" else None,
                "result": _result_of(review, ai_run) if state == "done" else None,
                "confirmed": confirmed,
                "humanResult": (opinion or {}).get("result") if confirmed else None,
            }
        )

    def sort_key(row: dict[str, Any]) -> tuple[Any, ...]:
        order = STATES.index(row["state"])
        if row["state"] == "queued":
            ahead = row["queueAhead"]
            return (order, 0 if ahead is not None else 1, ahead or 0, str(row["createdAt"] or ""))
        if row["state"] == "done":
            # 已出结果的：还没确认的排前面，各自按完成时间倒序
            return (order, 1 if row["confirmed"] else 0, _desc(row["finishedAt"]))
        return (order, 0, _desc(row["finishedAt"] or row["startedAt"] or row["createdAt"]))

    rows.sort(key=sort_key)
    settled = [row for row in rows if row["state"] in {"done", "cancelled"}]
    kept_settled = {id(row) for row in settled[:finished_limit]}
    visible = [
        row for row in rows if row["state"] not in {"done", "cancelled"} or id(row) in kept_settled
    ]
    counts = {state: sum(1 for row in rows if row["state"] == state) for state in STATES}
    counts["awaitingConfirmation"] = sum(
        1
        for row in rows
        if row["state"] == "done" and not row["confirmed"] and not row["advisoryOnly"]
    )
    return {
        "items": visible,
        "counts": counts,
        "active": counts["running"] + counts["queued"],
        "settledTotal": len(settled),
        "settledShown": min(len(settled), finished_limit),
    }


def _desc(value: Any) -> float:
    """时间倒序用的键：新的在前，没有时间的排最后。"""
    moment = _parse_time(value)
    return -moment.timestamp() if moment else 0.0
