"""P12 F4 盲审骨架：每周随机抽 10% 已完成节点，另一名审查人在看不到 AI 结论的情况下独立判；
盲审差异率 − 常规差异率 = 橡皮图章指数（§17.3）。

只做抽样、落盘、指数计算；不改任何业务状态（节点状态、审查意见都不动）。
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from libs.feedback.metrics import AI_RESULT_TO_OPINION

DEFAULT_SAMPLE_RATIO = 0.10
BLIND_TASK_STATUS_OPEN = "open"
BLIND_TASK_STATUS_DONE = "done"


def _parse_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[: len(fmt) + 2], fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _ai_result_of_run(run: dict[str, Any]) -> str | None:
    suggestion = run.get("suggestion") if isinstance(run.get("suggestion"), dict) else {}
    value = suggestion.get("result") or run.get("suggestedResult")
    return str(value) if value else None


def completed_node_candidates(state: dict[str, Any], *, window_days: int | None, now: datetime | None = None) -> list[dict[str, Any]]:
    """有 AI 结论且已有常规人工意见的节点——只有这类节点的盲审结果才能和常规差异率比。"""
    now = now or datetime.now(UTC)
    since = now - timedelta(days=window_days) if window_days else None
    latest_run: dict[tuple[str, int], dict[str, Any]] = {}
    for run in state.get("ai_runs") or []:
        if not isinstance(run, dict) or not run.get("projectId") or not _ai_result_of_run(run):
            continue
        key = (str(run["projectId"]), int(run.get("nodeId") or 0))
        finished = _parse_time(run.get("finishedAt") or run.get("startedAt"))
        current = latest_run.get(key)
        if current is None or (finished and (_parse_time(current.get("finishedAt") or current.get("startedAt")) or datetime.min.replace(tzinfo=UTC)) < finished):
            latest_run[key] = run
    candidates: list[dict[str, Any]] = []
    for opinion in state.get("review_opinions") or []:
        if not isinstance(opinion, dict) or not opinion.get("projectId"):
            continue
        key = (str(opinion["projectId"]), int(opinion.get("nodeId") or 0))
        run = latest_run.get(key)
        if run is None:
            continue
        created = _parse_time(opinion.get("createdAt"))
        if since and created and created < since:
            continue
        candidates.append(
            {
                "projectId": key[0],
                "nodeId": key[1],
                "aiRunId": run.get("id"),
                "aiResult": _ai_result_of_run(run),
                "regularOpinionId": opinion.get("id"),
                "regularResult": opinion.get("result"),
                "regularReviewerName": opinion.get("reviewerName"),
            }
        )
    return candidates


def sample_blind_review_tasks(
    state: dict[str, Any],
    *,
    ratio: float = DEFAULT_SAMPLE_RATIO,
    seed: str | None = None,
    window_days: int | None = 7,
    now: datetime | None = None,
    created_by: str | None = None,
) -> list[dict[str, Any]]:
    """抽样并写入 state['blind_review_tasks']；同一 (project, node, aiRunId) 已有未完成任务就跳过。"""
    now = now or datetime.now(UTC)
    existing = {
        (str(item.get("projectId")), int(item.get("nodeId") or 0), str(item.get("aiRunId")))
        for item in state.get("blind_review_tasks") or []
        if isinstance(item, dict) and item.get("status") != BLIND_TASK_STATUS_DONE
    }
    candidates = [c for c in completed_node_candidates(state, window_days=window_days, now=now) if (c["projectId"], c["nodeId"], str(c["aiRunId"])) not in existing]
    if not candidates:
        return []
    count = max(1, round(len(candidates) * max(0.0, min(1.0, ratio))))
    rng = random.Random(seed or now.strftime("%G-W%V"))  # 默认按 ISO 周种子：同一周重复抽样结果稳定
    picked = rng.sample(candidates, min(count, len(candidates)))
    batch_id = f"BRB-{now.strftime('%G%V')}-{uuid4().hex[:4].upper()}"
    tasks = []
    for candidate in picked:
        tasks.append(
            {
                "id": f"BRT-{uuid4().hex[:8].upper()}",
                "batchId": batch_id,
                "status": BLIND_TASK_STATUS_OPEN,
                "createdAt": now.isoformat(),
                "createdBy": created_by,
                "sampleRatio": ratio,
                "windowDays": window_days,
                "excludedReviewerName": candidate["regularReviewerName"],
                **candidate,
            }
        )
    state.setdefault("blind_review_tasks", [])
    state["blind_review_tasks"][0:0] = tasks
    return tasks


def blind_task_view(task: dict[str, Any], *, reveal: bool = False) -> dict[str, Any]:
    """给盲审人看的视图必须遮掉 AI 结论与常规结论；reveal 只给指数计算与 FDE 复盘。"""
    item = dict(task)
    if not reveal:
        for key in ("aiResult", "regularResult", "regularOpinionId", "regularReviewerName"):
            item.pop(key, None)
    return item


def record_blind_decision(task: dict[str, Any], *, result: str, reviewer_name: str | None, comment: str | None, now: datetime | None = None) -> dict[str, Any] | str:
    """返回更新后的任务，或错误信息（字符串）。常规审查人不能给自己盲审。"""
    if task.get("status") == BLIND_TASK_STATUS_DONE:
        return "该盲审任务已完成。"
    if reviewer_name and task.get("excludedReviewerName") and reviewer_name == task["excludedReviewerName"]:
        return "盲审人不能是该节点的常规审查人。"
    if not result:
        return "盲审结论不能为空。"
    now = now or datetime.now(UTC)
    task.update(
        {
            "status": BLIND_TASK_STATUS_DONE,
            "blindResult": result,
            "blindReviewerName": reviewer_name,
            "blindComment": comment,
            "decidedAt": now.isoformat(),
            "divergesFromAi": AI_RESULT_TO_OPINION.get(str(task.get("aiResult") or ""), task.get("aiResult")) != result,
            "divergesFromRegular": (task.get("regularResult") or None) != result,
        }
    )
    return task


def rubber_stamp_index(state: dict[str, Any]) -> dict[str, Any]:
    """盲审差异率 − 常规差异率。常规差异率取同一批盲审节点上常规意见与 AI 的不一致比例（同口径对比）。"""
    done = [item for item in state.get("blind_review_tasks") or [] if isinstance(item, dict) and item.get("status") == BLIND_TASK_STATUS_DONE]
    if not done:
        return {"value": None, "blindDivergence": None, "regularDivergence": None, "sampleSize": 0}
    blind_div = sum(1 for item in done if item.get("divergesFromAi")) / len(done)
    regular_div = sum(1 for item in done if AI_RESULT_TO_OPINION.get(str(item.get("aiResult") or ""), item.get("aiResult")) != item.get("regularResult")) / len(done)
    return {
        "value": round(blind_div - regular_div, 4),
        "blindDivergence": round(blind_div, 4),
        "regularDivergence": round(regular_div, 4),
        "sampleSize": len(done),
    }
