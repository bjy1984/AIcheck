"""节点的合并时间线：AI 回复和人工回复排在同一条线上（0817 第 3 条）。

    「资料 ai 识别。可以自动回复以及人工回复。」

## 为什么要合并

原先这两条信息分在两处：AI 运行在 aiRuns 里，人工结论在 reviewOpinions 里。
监检要判断「这个节点到底经历了什么」，得自己在两个列表之间按时间对一遍——
**而人一旦要自己对时间，就一定会对错**，尤其是 AI 跑了几轮、中间还夹着
人工改判的时候。

## 三条口径

1. **谁说的要写清楚。** actor 分 ai / human，界面上不能混成一句
   「结论：满足要求」——那样看不出是机器判的还是人判的。

2. **人工改判要能看出改了什么。** 单独列一条「人工结论」不够，
   还要带上它覆盖了哪个 AI 结论。不然翻时间线只能看到两条并列的结论，
   看不出后一条是在推翻前一条。

3. **时间缺失的排最后，不排最前。** 缺时间的记录用空字符串排序会跑到最前面，
   看起来像「最早发生的事」——而它其实只是没记时间。
"""

from __future__ import annotations

from typing import Any

# 时间未知的排到最后。用空串的话会排到最前，被当成「最早发生的」。
_UNKNOWN_TIME = "9999-99-99"


def _time_of(item: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = str(item.get(key) or "").strip()
        if value:
            return value
    return ""


def node_review_timeline(
    ai_runs: list[dict[str, Any]] | None,
    review_opinions: list[dict[str, Any]] | None,
    rectifications: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """把三类事件合成一条时间线，按时间正序。

    每条都带 actor（ai / human）和 summary——**只有结论没有来源的条目，
    在界面上和另一种来源的条目长得一模一样。**
    """
    events: list[dict[str, Any]] = []

    for run in ai_runs or []:
        if not isinstance(run, dict):
            continue
        conclusion = str(run.get("conclusion") or "")
        status = str(run.get("status") or "")
        events.append(
            {
                "type": "aiRun",
                "actor": "ai",
                "at": _time_of(run, "finishedAt", "updatedAt", "createdAt"),
                "title": "AI 审查",
                # 没有结论时说「未给出结论」，不要留空——留空会被读成「通过」
                "summary": conclusion or f"未给出结论（{status or '状态未知'}）",
                "conclusion": conclusion,
                "status": status,
                "refId": run.get("id") or run.get("aiRunId"),
            }
        )

    for opinion in review_opinions or []:
        if not isinstance(opinion, dict):
            continue
        conclusion = str(opinion.get("conclusion") or "")
        events.append(
            {
                "type": "humanOpinion",
                "actor": "human",
                "at": _time_of(opinion, "createdAt", "updatedAt"),
                "title": "监检人工结论",
                "summary": conclusion or "（未填写结论）",
                "conclusion": conclusion,
                "operator": opinion.get("operatorName") or opinion.get("createdBy") or "",
                # 覆盖了哪条 AI 结论。不带的话，翻时间线只看到两条并列的结论，
                # 看不出后一条是在推翻前一条。
                "overrides": opinion.get("aiRunId") or opinion.get("reviewRunId") or "",
                "refId": opinion.get("id"),
            }
        )

    for item in rectifications or []:
        if not isinstance(item, dict):
            continue
        events.append(
            {
                "type": "rectification",
                "actor": "human",
                "at": _time_of(item, "createdAt", "updatedAt"),
                "title": "补正",
                "summary": str(item.get("reason") or item.get("status") or "补正处理"),
                "refId": item.get("id"),
            }
        )

    return sorted(events, key=lambda event: event["at"] or _UNKNOWN_TIME)
