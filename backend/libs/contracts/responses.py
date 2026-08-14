from __future__ import annotations

import os
from datetime import date, datetime
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import Request
from fastapi.responses import JSONResponse

from .errors import BusinessErrorCode


def resolve_server_tz() -> ZoneInfo:
    try:
        return ZoneInfo(os.getenv("AICHECK_SERVER_TZ", "Asia/Shanghai"))
    except Exception:
        return ZoneInfo("Asia/Shanghai")


SERVER_TZ = resolve_server_tz()


def server_time() -> str:
    return datetime.now(SERVER_TZ).strftime("%Y-%m-%d %H:%M:%S")


def business_today() -> date:
    """业务口径的「今天」。

    容器跑 UTC，业务在 Asia/Shanghai（实测 2026-08-14：宿主 CST +0800，
    容器 UTC +0000）。裸用 `date.today()` 拿到的是 UTC 日期，于是每天
    **00:00–08:00 这 8 小时里它比业务日期少一天**。

    落到业务上：一张 2026-08-14 到期的焊工证，在 08-15 凌晨那段时间会被判成
    仍然有效——有效期判定整整差一天。同类还有规则版本切换日
    （`review_date >= date(2026, 8, 1)`）和标准现行性核验。

    时区来源与 server_time 同一个 SERVER_TZ，别再各写各的。
    """
    return datetime.now(SERVER_TZ).date()


def operation_id(request: Request | None = None) -> str:
    if request is not None and hasattr(request.state, "operation_id"):
        return request.state.operation_id
    return f"OP-{uuid4().hex[:12].upper()}"


def ok(data: Any = None, request: Request | None = None, message: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "code": 0,
        "data": data,
        "operationId": operation_id(request),
        "serverTime": server_time(),
    }
    if message:
        payload["message"] = message
    return payload


def fail(
    error: BusinessErrorCode,
    request: Request | None = None,
    *,
    message: str | None = None,
    data: dict[str, Any] | None = None,
    http_status: int = 200,
) -> JSONResponse:
    body = {
        "code": error.code,
        "message": message or error.message,
        "data": {"reason": error.reason, **(data or {})},
        "operationId": operation_id(request),
        "serverTime": server_time(),
    }
    return JSONResponse(body, status_code=http_status)


def page(items: list[Any], page_no: int = 1, page_size: int = 20) -> dict[str, Any]:
    safe_page = max(page_no or 1, 1)
    safe_size = max(min(page_size or 20, 200), 1)
    start = (safe_page - 1) * safe_size
    end = start + safe_size
    return {
        "items": items[start:end],
        "page": safe_page,
        "pageSize": safe_size,
        "total": len(items),
    }
