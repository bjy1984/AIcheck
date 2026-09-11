"""项目施工起止日期：证书有效期覆盖判定的唯一来源。

2026-09-11 全节点扫描：check_date_covers 在所有项目上都报 periodStart_and_periodEnd_missing——
生产里没有一个项目填了 constructionStart / plannedConstructionEnd，而项目创建与更新的 API
根本不接这两个字段，界面上也没有录入口。证书节点（1/2/3/24/38）的有效期覆盖因此从结构上
无法判定。

只收 ISO 日期（YYYY-MM-DD）或空。写坏的日期宁可拒绝也不落库：落一个「2028-1-17」进去，
后面比对时按字符串比就错了。
"""
from __future__ import annotations

from datetime import date
from typing import Any

CONSTRUCTION_DATE_FIELDS = ("constructionStart", "plannedConstructionEnd")


def normalize_construction_date(value: Any) -> str | None:
    """空 → None；合法 ISO → 原样；其余抛 ValueError。"""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError as exc:
        raise ValueError(f"construction_date_invalid:{text}") from exc


def apply_construction_dates(project: dict[str, Any], body: dict[str, Any]) -> list[dict[str, Any]]:
    """把 body 里出现的日期字段写进 project，返回变更记录（与 update_project 的 changed 同形）。

    起止都给了且起 > 止时拒绝：有效期覆盖比对的是 [start, end]，倒过来的区间没有意义。
    """
    changed: list[dict[str, Any]] = []
    staged = {field: project.get(field) for field in CONSTRUCTION_DATE_FIELDS}
    for field in CONSTRUCTION_DATE_FIELDS:
        if field in body:
            staged[field] = normalize_construction_date(body[field])
    start, end = staged["constructionStart"], staged["plannedConstructionEnd"]
    if start and end and start > end:
        raise ValueError("construction_period_inverted")
    for field in CONSTRUCTION_DATE_FIELDS:
        if field in body and project.get(field) != staged[field]:
            changed.append({"field": field, "before": project.get(field), "after": staged[field]})
            project[field] = staged[field]
    return changed


def construction_dates_from_body(body: dict[str, Any]) -> dict[str, str | None]:
    """创建项目时的两个日期字段；非法日期抛 ValueError，由路由转成校验错误。"""
    project: dict[str, Any] = {}
    apply_construction_dates(project, {field: body.get(field) for field in CONSTRUCTION_DATE_FIELDS if field in body})
    return {field: project.get(field) for field in CONSTRUCTION_DATE_FIELDS}
