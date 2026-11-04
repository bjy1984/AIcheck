"""监检总览按工位分组时，每个节点落到哪一组：通过 / 未通过 / 待补资料 / 需人工确认 / 未开始审核。

原来的项目总览只给流程状态（未开始、处理中、需关注、已完成），说的是「流程走到哪了」，
不是「这个节点合不合格」——监检要逐个点进节点才看得到结论。2026-11-03 用户要求按工位
分组、先看通过与否，这里把节点级结论算出来，口径（用户同日确认「单独分组」）：

- 人工结论优先：最新监检意见「满足要求」→ 通过（已确认）；「需补正」等 → 未通过（已确认）。
- 没有人工结论时看最近一次已出结果的 AI 复核的原子项：
  任一不符合 → 未通过；否则任一证据不足 → 待补资料；否则任一需人工 → 需人工确认；
  其余全部符合或不适用 → 通过（AI 判定·待确认），全部不适用时标「不适用」。
- 没跑过复核、或复核还在跑 / 失败 → 未开始审核（running / failed 单独标出来，不冒充结论）。
"""
from __future__ import annotations

from typing import Any

from libs.review_workstations import load_registry

GROUPS = ("failed", "needs_materials", "needs_human", "passed", "not_started")
_HUMAN_PASS = {"满足要求", "符合", "通过"}
_HUMAN_FAIL = {"需补正", "不满足要求", "不符合", "不合格"}
_FINISHED_RUN = {"waiting_human_review", "completed", "succeeded", "passed", "finished"}
_RUNNING_RUN = {"queued", "running", "retrying", "dispatched"}
_GROUP_BY_RESULT = (("failed", "failed"), ("evidence_insufficient", "needs_materials"),
                    ("human_review_required", "needs_human"))


def _reason(outcome: dict[str, Any]) -> dict[str, Any]:
    failed_codes = [str(item.get("code")) for item in outcome.get("checks") or []
                    if isinstance(item, dict) and item.get("passed") is False and item.get("code")]
    return {"atomicCheckId": outcome.get("atomicCheckId"), "result": outcome.get("result"),
            "reasonCode": outcome.get("reason") or None, "checkCodes": failed_codes[:8]}


def node_conclusion(review_run: dict[str, Any] | None, opinion: dict[str, Any] | None) -> dict[str, Any]:
    run = review_run or {}
    outcomes = [item for item in run.get("atomicCheckOutcomes") or [] if isinstance(item, dict)]
    counts: dict[str, int] = {}
    for item in outcomes:
        counts[str(item.get("result") or "unknown")] = counts.get(str(item.get("result") or "unknown"), 0) + 1
    base = {"reviewRunId": run.get("reviewRunId") or run.get("id"), "atomicCounts": counts,
            "humanResult": (opinion or {}).get("result") or None}
    human = str((opinion or {}).get("result") or "").strip()
    if human in _HUMAN_PASS:
        return {**base, "group": "passed", "confirmed": True, "reason": None}
    if human in _HUMAN_FAIL:
        return {**base, "group": "failed", "confirmed": True,
                "reason": {"humanOpinion": str((opinion or {}).get("opinion") or "")[:120] or None}}
    status = str(run.get("status") or "").lower()
    if not outcomes or status not in _FINISHED_RUN:
        run_state = "running" if status in _RUNNING_RUN else "failed" if status.startswith("failed") else None
        return {**base, "group": "not_started", "confirmed": False, "reason": None, "runState": run_state}
    for result, group in _GROUP_BY_RESULT:
        hit = next((item for item in outcomes if item.get("result") == result), None)
        if hit is not None:
            return {**base, "group": group, "confirmed": False, "reason": _reason(hit)}
    not_applicable = all(item.get("result") == "not_applicable" for item in outcomes)
    return {**base, "group": "passed", "confirmed": False, "reason": None, "notApplicable": not_applicable}


def station_groups() -> list[dict[str, Any]]:
    """工位清单（固定 A～I 顺序）：编号、名称、包含的节点。"""
    registry = load_registry()
    stations = registry.get("stations") if isinstance(registry, dict) else registry
    rows = stations.values() if isinstance(stations, dict) else stations or []
    return [{"stationId": item.get("id"), "stationName": item.get("name"),
             "nodeIds": [int(value) for value in item.get("nodeIds") or []]} for item in rows if isinstance(item, dict)]
