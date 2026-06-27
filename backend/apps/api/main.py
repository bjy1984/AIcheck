from __future__ import annotations

import os
import re
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from apps.api.routes import binding_node_ids, document_node_ids, member_node_scope_error, mock_router, report_node_ids, router
from libs.contracts import errors
from libs.contracts.responses import fail, ok
from libs.db.mongo import close_mongo, init_mongo_if_configured
from libs.db.repository import mongo_transactions_enabled, repo
from libs.integrations.storage import object_storage
from libs.security.actions import canonical_path, required_action_for_request
from libs.security.auth import decode_token, demo_users_enabled, user_by_username


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_mongo_if_configured(app)
    yield
    await close_mongo(app)


app = FastAPI(
    title="AIcheck Backend API",
    version="0.1.0",
    description="FastAPI backend for AIcheck with MongoDB-ready repository, OCR/worker integration, and LiteLLM gateway support.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def attach_operation_id(request: Request, call_next):
    request.state.operation_id = request.headers.get("X-Operation-Id") or f"OP-{uuid4().hex[:12].upper()}"
    if auth_required(request):
        claims = decode_token(request.headers.get("Authorization", ""))
        if claims is None:
            return fail(errors.AUTH_REQUIRED, request)
        user = user_by_username(claims.get("sub"))
        if user is None:
            return fail(errors.AUTH_REQUIRED, request)
        request.state.auth = claims
        request.state.auth_user = user
    admin_read_error = inferred_admin_read_error(request)
    if admin_read_error is not None:
        return admin_read_error
    project_scope_error = inferred_project_scope_error(request)
    if project_scope_error is not None:
        return project_scope_error
    action_error = inferred_action_error(request)
    if action_error is not None:
        return action_error
    response = await call_next(request)
    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and repo.mongo is not None:
        await repo.flush_to_mongo()
    return response


def auth_required(request: Request) -> bool:
    if os.getenv("AICHECK_REQUIRE_AUTH", "false").lower() != "true":
        return False
    public_prefixes = (
        "/healthz",
        "/api/healthz",
        "/auth/login",
        "/api/auth/login",
        "/mock/",
        "/api/mock/",
        "/docs",
        "/openapi.json",
    )
    return not request.url.path.startswith(public_prefixes)


def inferred_project_scope_error(request: Request) -> JSONResponse | None:
    claims = getattr(request.state, "auth", None)
    if not claims:
        return None
    normalized_path = canonical_path(request.url.path)
    match = re.match(r"^/projects/([^/]+)(?:/|$)", normalized_path)
    if not match:
        return None
    project_id = match.group(1)
    role = claims.get("role")
    node_ids = scoped_node_ids_from_request(project_id, normalized_path, request)
    return member_node_scope_error(request, project_id, role, node_ids=node_ids)


def scoped_node_ids_from_request(project_id: str, normalized_path: str, request: Request) -> list[int]:
    node_ids: set[int] = set()
    for query_key in ("nodeId", "nodeIds"):
        for value in request.query_params.getlist(query_key):
            for part in str(value).split(","):
                if part.strip().isdigit():
                    node_ids.add(int(part))
    binding_match = re.search(r"/documents/bindings/([^/]+)", normalized_path)
    if binding_match:
        node_ids.update(binding_node_ids(project_id, binding_match.group(1)))
    else:
        document_match = re.search(r"/documents/([^/]+)", normalized_path)
        if document_match:
            node_ids.update(document_node_ids(project_id, document_match.group(1)))
    report_match = re.search(r"/reports/([^/]+)", normalized_path)
    if report_match:
        node_ids.update(report_node_ids(project_id, report_match.group(1)))
    return sorted(node_ids)


def inferred_action_error(request: Request) -> JSONResponse | None:
    inferred_action = required_action_for_request(request.method, request.url.path)
    explicit_action = request.headers.get("X-Action-Code")
    if not inferred_action and not explicit_action:
        return None
    claims = getattr(request.state, "auth", None)
    token_role = claims.get("role") if claims else None
    header_role = request.headers.get("X-Role")
    if token_role and header_role and header_role != token_role and token_role != "admin":
        return fail(errors.FORBIDDEN, request, message="请求角色与登录身份不一致。")
    role = header_role or token_role
    if not role:
        return None
    allowed_actions = set(repo.role_actions(role))
    for action_code in [inferred_action, explicit_action]:
        if action_code and action_code not in allowed_actions:
            return fail(errors.FORBIDDEN, request, message=f"角色 {role} 无权执行 {action_code}。")
    return None


def inferred_admin_read_error(request: Request) -> JSONResponse | None:
    claims = getattr(request.state, "auth", None)
    if not claims:
        return None
    normalized_path = canonical_path(request.url.path)
    admin_prefixes = (
        "/admin",
        "/knowledge/overview",
        "/knowledge/sources",
        "/knowledge/config",
        "/knowledge/audit-logs",
        "/rules",
    )
    if not normalized_path.startswith(admin_prefixes):
        return None
    if claims.get("role") == "admin":
        return None
    return fail(errors.FORBIDDEN, request, message="仅管理员可访问该管理接口。")


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    return fail(errors.VALIDATION_ERROR, request, data={"errors": exc.errors()})


@app.exception_handler(Exception)
async def generic_error_handler(request: Request, exc: Exception):
    return JSONResponse(
        {
            "code": errors.EXTERNAL_TOOL_FAILED.code,
            "message": "服务内部错误，请稍后重试。",
            "data": {"reason": errors.EXTERNAL_TOOL_FAILED.reason},
            "operationId": getattr(request.state, "operation_id", None),
            "serverTime": ok(None, request)["serverTime"],
        },
        status_code=500,
    )


@app.get("/healthz", tags=["system"])
async def healthz(request: Request):
    return ok(health_payload(), request)


@app.get("/api/healthz", tags=["system"])
async def api_healthz(request: Request):
    return ok(health_payload(), request)


def health_payload() -> dict[str, object]:
    return {
        "status": "ok",
        "service": "api-service",
        "mongoEnabled": repo.mongo_enabled,
        "mongoTransactions": mongo_transactions_enabled(),
        "authRequired": os.getenv("AICHECK_REQUIRE_AUTH", "false").lower() == "true",
        "demoUsersEnabled": demo_users_enabled(),
        "objectStorageEnabled": object_storage.enabled,
    }


app.include_router(mock_router)
app.include_router(mock_router, prefix="/api")
app.include_router(router)
app.include_router(router, prefix="/api")
