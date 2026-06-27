from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import Request
from fastapi.responses import JSONResponse

from .errors import BusinessErrorCode

SERVER_TZ = ZoneInfo("America/Los_Angeles")


def server_time() -> str:
    return datetime.now(SERVER_TZ).strftime("%Y-%m-%d %H:%M:%S")


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
