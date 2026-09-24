"""Authenticated review capabilities without project uploads or persisted results."""
from __future__ import annotations

import json

from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool

from apps.api import routes as api
from libs.contracts import errors
from libs.contracts.responses import fail, ok
from libs.important_node_review import NODE_IDS, skill_catalog
from libs.inspection_services import (
    InspectionServiceError,
    certificate_registry,
    certificate_validity,
    service_capabilities,
)

inspection_service_router = APIRouter(prefix="/inspection-services")


def _guard(request: Request):
    role, error = api.effective_role_for_request(request)
    if error is not None:
        return error
    if role != "inspection" or not api.request_user_id(request):
        return fail(errors.FORBIDDEN, request, message="仅授权监检人员可调用审查服务。", http_status=403)
    return None


def _invoke(request: Request, handler, *args):
    response = _guard(request)
    if response is None:
        try:
            response = ok(handler(*args), request)
        except InspectionServiceError as exc:
            response = fail(errors.EXTERNAL_TOOL_FAILED if exc.status == 503 else errors.VALIDATION_ERROR,
                            request, message=str(exc), data={"serviceReason": exc.reason}, http_status=exc.status)
    return response


async def _body_invoke(request: Request, handler, *, limit: int = 1024 * 1024):
    if (denied := _guard(request)) is not None:
        return denied
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > limit:
            return fail(errors.VALIDATION_ERROR, request, message="请求内容超过服务限制。", http_status=413)
        content.extend(chunk)
    try:
        payload = json.loads(content)
    except (ValueError, UnicodeDecodeError):
        return fail(errors.VALIDATION_ERROR, request, message="请求须为 JSON 对象。", http_status=400)
    if not isinstance(payload, dict):
        return fail(errors.VALIDATION_ERROR, request, message="请求须为 JSON 对象。", http_status=400)
    return await run_in_threadpool(_invoke, request, handler, payload)


@inspection_service_router.get("/capabilities")
def capabilities(request: Request):
    return _invoke(request, service_capabilities)


@inspection_service_router.get("/rules")
def rules(request: Request, nodeId: int | None = None):
    def selected_rules():
        if nodeId is not None and nodeId not in NODE_IDS:
            raise InspectionServiceError("当前 v3 审查规则不包含此节点。")
        return {"nodes": [node for node in skill_catalog() if nodeId is None or node["nodeId"] == nodeId]}
    return _invoke(request, selected_rules)


@inspection_service_router.post("/certificate-validity")
async def validity(request: Request):
    return await _body_invoke(request, certificate_validity)


@inspection_service_router.post("/certificate-registry")
async def registry(request: Request):
    return await _body_invoke(request, certificate_registry, limit=4096)
