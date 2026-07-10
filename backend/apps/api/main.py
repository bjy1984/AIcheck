from __future__ import annotations

import json
import os
import re
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse, Response

from apps.api.routes import binding_node_ids, document_node_ids, idempotency_fingerprint, member_node_scope_error, mock_router, report_node_ids, router
from libs.contracts import errors
from libs.contracts.responses import fail, ok
from libs.db.postgres import close_postgres, init_postgres_if_configured, run_transaction_probe
from libs.db.repository import flush_idempotency_records, flush_state, flush_state_records, load_state, repo
from libs.integrations.storage import ObjectStorageUnavailable, object_storage
from libs.runtime_readiness import production_runtime_status
from libs.security.actions import canonical_path, required_action_for_request
from libs.security.auth import (
    compatibility_mocks_enabled,
    decode_token,
    demo_users_enabled,
    public_user,
    strict_production,
    user_record_by_username,
)
from libs.security.runtime import (
    allowed_hosts,
    cors_allowed_origins,
    security_runtime_status,
    validate_security_runtime,
)
from libs.security.session import SecurityBackendUnavailable, security_sessions


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_postgres_if_configured(app)
    load_state()
    validate_security_runtime()
    if strict_production() and not await security_sessions.ready():
        raise RuntimeError("Redis security backend is unavailable")
    yield
    await close_postgres(app)


app = FastAPI(
    title="AIcheck Backend API",
    version="0.1.0",
    description="FastAPI backend for AIcheck with PostgreSQL-ready repository, OCR/worker integration, and LiteLLM gateway support.",
    lifespan=lifespan,
    docs_url=None if strict_production() else "/docs",
    redoc_url=None,
    openapi_url=None if strict_production() else "/openapi.json",
)

app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts())
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_allowed_origins(),
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "Idempotency-Key",
        "If-Match",
        "X-Action-Code",
        "X-Operation-Id",
        "X-Role",
        "X-User-Id",
    ],
)


@app.middleware("http")
async def attach_operation_id(request: Request, call_next):
    request.state.operation_id = request.headers.get("X-Operation-Id") or f"OP-{uuid4().hex[:12].upper()}"
    normalized_path = canonical_path(request.url.path)
    if normalized_path.startswith("/mock/") and not compatibility_mocks_enabled():
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    if auth_required(request) or request.headers.get("Authorization"):
        claims = decode_token(request.headers.get("Authorization", ""))
        if claims is None:
            return fail(errors.AUTH_REQUIRED, request)
        user_record = user_record_by_username(claims.get("sub"))
        if user_record is None:
            return fail(errors.AUTH_REQUIRED, request)
        if claims.get("role") != user_record.get("role") or int(claims.get("ver") or 0) != int(user_record.get("authVersion") or 0):
            return fail(errors.AUTH_REQUIRED, request, message="登录身份已变化，请重新登录。")
        try:
            if await security_sessions.is_revoked(claims.get("jti")):
                return fail(errors.AUTH_REQUIRED, request, message="登录已注销，请重新登录。")
        except SecurityBackendUnavailable:
            return fail(errors.SECURITY_BACKEND_UNAVAILABLE, request, http_status=503)
        user = public_user(user_record)
        canonical_claims = {**claims, "role": user.get("role"), "ver": int(user_record.get("authVersion") or 0)}
        request.state.auth = canonical_claims
        request.state.auth_user = user
        password_change_paths = {"/auth/me", "/auth/logout", "/auth/change-password"}
        if user.get("mustChangePassword") and normalized_path not in password_change_paths:
            return fail(errors.PASSWORD_CHANGE_REQUIRED, request, http_status=403)
    admin_read_error = inferred_admin_read_error(request)
    if admin_read_error is not None:
        return admin_read_error
    project_scope_error = inferred_project_scope_error(request)
    if project_scope_error is not None:
        return project_scope_error
    action_error = inferred_action_error(request)
    if action_error is not None:
        return action_error
    cached_idempotency = await idempotency_replay_response(request)
    if cached_idempotency is not None:
        return cached_idempotency
    response = await call_next(request)
    response = await finalize_mutation_response(request, response)
    if should_flush_state(request):
        scoped_records = getattr(request.state, "scoped_flush_records", None)
        if callable(scoped_records):
            records = scoped_records()
            operation_id = getattr(request.state, "operation_id", None)
            audit_records = [
                item
                for item in repo.state.get("audit_logs", [])
                if operation_id and item.get("operationId") == operation_id
            ]
            if audit_records:
                records.setdefault("audit_logs", []).extend(audit_records)
            flush_state_records(records)
            scope = getattr(request.state, "idempotency_scope", None)
            if scope:
                flush_idempotency_records([scope])
        else:
            flush_state()
    return response


def auth_required(request: Request) -> bool:
    if os.getenv("AICHECK_REQUIRE_AUTH", "false").lower() != "true":
        return False
    public_prefixes = (
        "/healthz",
        "/api/healthz",
        "/auth/login",
        "/api/auth/login",
    )
    if compatibility_mocks_enabled():
        public_prefixes += ("/mock/", "/api/mock/")
    return not request.url.path.startswith(public_prefixes)


def idempotency_scope(request: Request) -> str | None:
    key = request.headers.get("Idempotency-Key")
    if not key or request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return None
    normalized_path = canonical_path(request.url.path)
    if normalized_path.startswith(("/auth/", "/mock/")):
        return None
    return f"{request.method}:{request.url.path}:{key}"


def should_flush_state(request: Request) -> bool:
    if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return False
    return audit_scope(request) is not None


async def request_fingerprint(request: Request) -> str:
    body = await request.body()
    parsed_body: Any
    if not body:
        parsed_body = None
    else:
        try:
            parsed_body = json.loads(body.decode("utf-8"))
        except Exception:
            parsed_body = body.decode("utf-8", errors="replace")
    return idempotency_fingerprint(
        {
            "query": sorted((key, value) for key, value in request.query_params.multi_items()),
            "body": parsed_body,
        }
    )


async def idempotency_replay_response(request: Request) -> JSONResponse | None:
    scope = idempotency_scope(request)
    if not scope:
        return None
    fingerprint = await request_fingerprint(request)
    request.state.idempotency_scope = scope
    request.state.idempotency_fingerprint = fingerprint
    cached = repo.state["idempotency"].get(scope)
    if not isinstance(cached, dict) or "response" not in cached:
        return None
    if cached.get("requestHash") and cached["requestHash"] != fingerprint:
        return fail(errors.IDEMPOTENCY_KEY_CONFLICT, request)
    return JSONResponse(repo.clone(cached["response"]), status_code=int(cached.get("httpStatus") or 200))


async def finalize_mutation_response(request: Request, response: Response) -> Response:
    scope = getattr(request.state, "idempotency_scope", None)
    if not scope and not audit_scope(request):
        return response
    body = b""
    async for chunk in response.body_iterator:
        body += chunk
    replay_response = Response(
        content=body,
        status_code=response.status_code,
        headers=dict(response.headers),
        media_type=response.media_type,
    )
    try:
        payload = json.loads(body.decode("utf-8")) if body else None
    except Exception:
        return replay_response
    if response.status_code == 200 and isinstance(payload, dict) and payload.get("code") == 0:
        if scope:
            repo.state["idempotency"][scope] = {
                "requestHash": getattr(request.state, "idempotency_fingerprint", None),
                "response": repo.clone(payload),
                "httpStatus": response.status_code,
            }
        audit_successful_mutation(request, payload)
    return replay_response


def audit_scope(request: Request) -> str | None:
    if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return None
    normalized_path = canonical_path(request.url.path)
    if normalized_path.startswith(("/auth/", "/mock/")):
        return None
    return normalized_path


def audit_successful_mutation(request: Request, payload: dict[str, Any]) -> None:
    normalized_path = audit_scope(request)
    if not normalized_path or payload_contains_key(payload, "auditLogId"):
        return
    actor = getattr(request.state, "auth_user", None) or {}
    audit_id = repo.add_audit(
        f"{request.method} {normalized_path}",
        "ApiMutation",
        normalized_path,
    )
    audit = repo.find_one("audit_logs", audit_id)
    if audit:
        audit["actorId"] = actor.get("id") or audit.get("actorId")
        audit["actorName"] = actor.get("name") or actor.get("username") or audit.get("actorName")
        audit["actorOrgName"] = actor.get("orgName") or audit.get("actorOrgName")
        audit["operationId"] = getattr(request.state, "operation_id", None)


def payload_contains_key(value: Any, key: str) -> bool:
    if isinstance(value, dict):
        return key in value or any(payload_contains_key(item, key) for item in value.values())
    if isinstance(value, list):
        return any(payload_contains_key(item, key) for item in value)
    return False


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
    if token_role and header_role and header_role != token_role:
        return fail(errors.FORBIDDEN, request, message="请求角色与登录身份不一致。")
    role = token_role or (header_role if not auth_required(request) else None)
    if not role:
        return None
    allowed_actions = set(repo.role_actions(role))
    for action_code in [inferred_action, explicit_action]:
        if role == "fde" and action_code and not action_code.startswith("fde:"):
            return fail(errors.FORBIDDEN, request, message="FDE 只能管理 AI 能力和治理流程，不能执行正式业务写操作。")
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


@app.exception_handler(ObjectStorageUnavailable)
async def object_storage_error_handler(request: Request, exc: ObjectStorageUnavailable):
    return fail(
        errors.OBJECT_STORAGE_REQUIRED,
        request,
        message=str(exc) or errors.OBJECT_STORAGE_REQUIRED.message,
    )


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
    return await health_response(request)


@app.get("/api/healthz", tags=["system"])
async def api_healthz(request: Request):
    return await health_response(request)


async def health_response(request: Request):
    payload = await health_payload()
    if strict_production() and (not payload["securityReady"] or not payload["runtimeReady"]):
        return fail(
            errors.SECURITY_BACKEND_UNAVAILABLE,
            request,
            data={**payload, "reason": errors.SECURITY_BACKEND_UNAVAILABLE.reason},
            http_status=503,
        )
    return ok(payload, request)


@app.get("/system/postgres-transaction-probe", tags=["system"])
@app.get("/api/system/postgres-transaction-probe", tags=["system"])
async def postgres_transaction_probe(request: Request):
    claims = getattr(request.state, "auth", None)
    if os.getenv("AICHECK_REQUIRE_AUTH", "false").lower() == "true" and (not claims or claims.get("role") != "admin"):
        return fail(errors.FORBIDDEN, request, message="仅管理员可执行 PostgreSQL transaction 探针。")
    return ok(await run_transaction_probe(getattr(request.app.state, "postgres", None)), request)


async def health_payload() -> dict[str, object]:
    database_backend = "postgres" if repo.postgres_enabled else "sqlite" if repo.sqlite_enabled else "memory"
    rate_limiter_ready = await security_sessions.ready()
    return {
        "status": "ok",
        "service": "api-service",
        "databaseBackend": database_backend,
        "databaseConnected": database_backend != "memory",
        "postgresEnabled": repo.postgres_enabled,
        "postgresTransactions": bool(repo.postgres_enabled),
        "sqliteEnabled": repo.sqlite_enabled,
        "sqlitePath": repo.sqlite_path,
        "authRequired": os.getenv("AICHECK_REQUIRE_AUTH", "false").lower() == "true",
        "demoUsersEnabled": demo_users_enabled(),
        "objectStorageEnabled": object_storage.enabled,
        **production_runtime_status(),
        **security_runtime_status(rate_limiter_ready=rate_limiter_ready),
    }


if compatibility_mocks_enabled():
    app.include_router(mock_router)
    app.include_router(mock_router, prefix="/api")
app.include_router(router)
app.include_router(router, prefix="/api")
