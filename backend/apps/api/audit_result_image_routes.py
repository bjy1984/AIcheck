"""POST /inspection-services/audit-result-image：把节点审计结果的摘要画成图（HTML 模板 → PNG，内容长就分多页）。

和 certificate-validity 等同属 inspection-services，但**不是公开接口**（不在 public_review_request 的白名单里）：
渲染吃 CPU 和内存，而 API 所在的机器本来就内存紧，所以要登录、要 `ai:recheck` 权限（监检角色有）、
有体积上限、同时最多渲染两张，画图放在子进程里。不存储输入，也不存储结果。
"""
from __future__ import annotations

import base64
import json
import logging
import threading

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from libs.audit_result_image import (
    MAX_BODY_BYTES,
    AuditImageError,
    normalize_summary,
    render_in_subprocess,
)
from libs.contracts import errors
from libs.contracts.responses import fail, ok

audit_result_image_router = APIRouter(prefix="/inspection-services")
logger = logging.getLogger("aicheck.api")
RENDER_SLOTS = threading.BoundedSemaphore(2)
RETRY_AFTER_SECONDS = "5"


def too_large(request: Request) -> JSONResponse:
    return fail(errors.FILE_TOO_LARGE, request, message=f"摘要超过 {MAX_BODY_BYTES // 1024}KB。", http_status=413)


@audit_result_image_router.post("/audit-result-image")
async def audit_result_image(request: Request):
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        return too_large(request)
    raw = await request.body()
    if len(raw) > MAX_BODY_BYTES:
        return too_large(request)
    try:
        summary = normalize_summary(json.loads(raw))
    except (ValueError, UnicodeDecodeError) as exc:
        message = str(exc) if isinstance(exc, AuditImageError) else "请求体不是合法的 JSON。"
        return fail(errors.VALIDATION_ERROR, request, message=message, http_status=400)
    if not RENDER_SLOTS.acquire(blocking=False):
        busy = fail(errors.RATE_LIMITED, request, message="正在渲染其他结果图，请几秒后重试。", http_status=429)
        busy.headers["Retry-After"] = RETRY_AFTER_SECONDS
        return busy
    try:
        pages = await run_in_threadpool(render_in_subprocess, summary)
    except AuditImageError as exc:
        if exc.client:  # 内容过长之类：调用方自己能处理，不是服务器的问题
            return fail(errors.VALIDATION_ERROR, request, message=str(exc), http_status=400)
        logger.warning("audit result image render failed: %s", exc)  # 摘要内容不进日志
        return fail(errors.EXTERNAL_TOOL_FAILED, request, message="结果图渲染失败，请稍后重试。", http_status=503 if exc.retryable else 500)
    finally:
        RENDER_SLOTS.release()
    return ok({"pageCount": len(pages), "contentType": "image/png",
               "pages": [{"pageNo": number, "imageBase64": base64.b64encode(png).decode("ascii")}
                         for number, png in enumerate(pages, start=1)]}, request)
