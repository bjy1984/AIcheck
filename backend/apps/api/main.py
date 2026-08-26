from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse, Response

from apps.api.batch_review_routes import batch_review_router
from apps.api.document_category_routes import document_category_router
from apps.api.org_delegation_routes import org_delegation_router
from apps.api.project_registration_routes import project_registration_router
from apps.api.cnse_routes import router as cnse_router
from apps.api.mineru_ocr_routes import router as mineru_ocr_router
from apps.api.idempotency_scope import authorization_membership_snapshot
from apps.api.routes import (
    binding_node_ids,
    document_node_ids,
    idempotency_fingerprint,
    member_node_scope_error,
    mock_router,
    report_node_ids,
    router,
    scope_error_for_record,
)
from apps.api.std_samr_routes import router as std_samr_router
from apps.api.auto_review_routes import auto_review_router
from apps.api.project_analysis_routes import project_analysis_router
from libs.audit_context import (
    current_request_audit_context,
    reset_request_audit_context,
    set_request_audit_context,
)
from libs.contracts import errors
from libs.contracts.responses import fail, ok
from libs.db.postgres import (
    bootstrap_local_roles_if_configured,
    close_postgres,
    init_postgres_if_configured,
    run_transaction_probe,
)
from libs.db.repository import (
    SINGLETON_COLLECTIONS,
    STATE_COLLECTIONS,
    ConcurrentPersistenceError,
    IllegalNodeStatusTransition,
    flush_mutation_records,
    flush_state,
    load_state,
    postgres_persistence_configured,
    repo,
)
from libs.integrations.storage import ObjectStorageUnavailable, object_storage
from libs.integrations.task_dispatcher import mineru_execution_mode
from libs.review_orchestrator.dispatcher import review_orchestration_mode
from libs.runtime_database_scope import refresh_runtime_database_scope
from libs.runtime_readiness import production_runtime_status
from libs.security.actions import canonical_path, required_action_for_request
from libs.security.auth import (
    authentication_enforced,
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
from libs.security.tenant import (
    configured_tenant_id,
    current_tenant_id,
    reset_request_tenant_id,
    set_request_tenant_id,
    tenant_id_for_record,
    tenant_is_allowed,
)

logger = logging.getLogger("aicheck.api")
_tenant_mutation_locks: dict[tuple[int, str], asyncio.Lock] = {}
PUBLIC_REGISTRATION_LINK_PATTERN = re.compile(
    r"^(?:/api)?/registration-links/[^/]+(?:/apply)?$"
)
PUBLIC_REGISTRATION_LINK_INSPECT_PATTERN = re.compile(
    r"^(?:/api)?/registration-links/[^/]+$"
)
PUBLIC_REGISTRATION_LINK_APPLY_PATTERN = re.compile(
    r"^(?:/api)?/registration-links/[^/]+/apply$"
)


def tenant_mutation_lock(tenant_id: str) -> asyncio.Lock:
    loop_id = id(asyncio.get_running_loop())
    return _tenant_mutation_locks.setdefault((loop_id, tenant_id), asyncio.Lock())


def _runtime_database_scope_refresh_interval_seconds() -> float:
    try:
        configured = float(
            os.getenv("AICHECK_RUNTIME_DATABASE_SCOPE_REFRESH_SECONDS", "2")
        )
    except ValueError:
        configured = 2.0
    return min(30.0, max(0.5, configured))


def _runtime_database_scope_refresh_configured() -> bool:
    dsn = os.getenv("AICHECK_DATABASE_URL") or os.getenv("DATABASE_URL")
    return bool(dsn and os.getenv("AICHECK_E2E_RUN_MARKER"))


async def _refresh_runtime_database_scope_once() -> None:
    refresh_task = asyncio.create_task(asyncio.to_thread(refresh_runtime_database_scope))
    try:
        await asyncio.shield(refresh_task)
    except asyncio.CancelledError:
        # Cancelling an asyncio.to_thread await does not stop its thread. Keep PostgreSQL open
        # until the bounded refresh has actually returned, then let lifespan close the pool.
        await refresh_task
        raise


async def runtime_database_scope_refresh_loop() -> None:
    """Refresh the public cache off-loop until lifespan cancellation."""
    if not _runtime_database_scope_refresh_configured():
        return
    while True:
        try:
            await _refresh_runtime_database_scope_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            # The core refresh is fail-closed. Avoid exception text here because a driver error
            # may contain connection identity; the next bounded interval retries.
            logger.warning("Runtime database-scope refresh failed")
        await asyncio.sleep(_runtime_database_scope_refresh_interval_seconds())


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_postgres_if_configured(app)
    load_state()
    bootstrap_local_roles_if_configured()
    validate_security_runtime()
    if not authentication_enforced():
        # 关闭认证会连带使项目隔离、节点范围、角色校验全部失效（authorized_node_scope
        # 与 member_node_scope_error 在无登录身份时直接放行）。禁止以此状态对外提供服务。
        logger.warning(
            "SECURITY WARNING: AICHECK_REQUIRE_AUTH is not 'true'. "
            "Authentication AND all project/node/role authorization checks are DISABLED. "
            "Any client can claim any identity via X-Role/X-User-Id headers. "
            "Never expose this deployment beyond local development."
        )
    if strict_production() and not await security_sessions.ready():
        raise RuntimeError("Redis security backend is unavailable")
    database_scope_task = (
        asyncio.create_task(
            runtime_database_scope_refresh_loop(),
            name="runtime-database-scope-refresh",
        )
        if _runtime_database_scope_refresh_configured()
        else None
    )
    try:
        yield
    finally:
        if database_scope_task is not None:
            database_scope_task.cancel()
            try:
                await database_scope_task
            except asyncio.CancelledError:
                pass
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
        "X-AICheck-Ocr-Metadata-B64",
        "X-Operation-Id",
        "X-Role",
        "X-User-Id",
    ],
    expose_headers=[
        "ETag",
        "Idempotency-Replayed",
        "Retry-After",
        "X-Operation-Id",
        "X-Raw-Payload-SHA256",
    ],
)


@app.middleware("http")
async def attach_operation_id(request: Request, call_next):
    authorization = request.headers.get("Authorization", "")
    predecoded_claims = decode_token(authorization) if authorization else None
    claimed_tenant_id = str((predecoded_claims or {}).get("tid") or configured_tenant_id())
    if predecoded_claims is None and request.method == "POST" and canonical_path(request.url.path) == "/auth/login":
        try:
            login_payload = json.loads((await request.body()).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            login_payload = None
        requested_tenant_id = str((login_payload or {}).get("tenantId") or "").strip()
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", requested_tenant_id):
            claimed_tenant_id = requested_tenant_id
    tenant_id = claimed_tenant_id if tenant_is_allowed(claimed_tenant_id) else configured_tenant_id()
    tenant_context_token = set_request_tenant_id(tenant_id)
    mutation_lock = None
    mutation_lock_acquired = False
    try:
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            mutation_lock = tenant_mutation_lock(tenant_id)
            await mutation_lock.acquire()
            mutation_lock_acquired = True
        return await handle_request(
            request, call_next, predecoded_claims=predecoded_claims, tenant_id=tenant_id
        )
    finally:
        try:
            lock_connection = getattr(request.state, "idempotency_lock_connection", None)
            if lock_connection is not None:
                await asyncio.to_thread(release_idempotency_lock, lock_connection, request)
        finally:
            if mutation_lock is not None and mutation_lock_acquired:
                mutation_lock.release()
            reset_request_tenant_id(tenant_context_token)


def refresh_state_if_stale(tenant_id: str | None) -> None:
    """请求前把过期集合拉回内存。

    失败一律吞掉：探针不是数据源，它挂了让整个 API 跟着挂是本末倒置。
    仓库层已经记了日志，这里不重复。
    """
    repo.refresh_stale_state_from_postgres(tenant_id=tenant_id or None)


async def handle_request(
    request: Request,
    call_next,
    *,
    predecoded_claims: dict[str, Any] | None,
    tenant_id: str | None = None,
):
    request.state.operation_id = request.headers.get("X-Operation-Id") or f"OP-{uuid4().hex[:12].upper()}"
    if predecoded_claims and not tenant_is_allowed(str(predecoded_claims.get("tid") or "")):
        return audit_rejected_request(
            request,
            fail(errors.FORBIDDEN, request, message="当前部署不允许访问该租户。", http_status=403),
            "TENANT_NOT_ALLOWED",
        )
    normalized_path = canonical_path(request.url.path)
    if normalized_path.startswith("/mock/") and not compatibility_mocks_enabled():
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    # 把进程外写入的集合拉回内存（issue #9）。放在鉴权之前，因为口令校验读的
    # 就是内存里的 users——运维改完口令，本进程不刷新就一直用旧的，线上踩过。
    #
    # 两级探针 + 1 秒节流，绝大多数请求只多一次 max(updated_at) 的 1 行查询。
    # 放在线程池里跑：这是同步的 psycopg 调用，直接在事件循环里做会卡住整个进程。
    # 先判有没有 postgres 再决定是否切线程。丢进线程池本身有开销，
    # 无持久化时（本地开发、单测）函数立刻返回，白付一次线程调度——
    # 实测整套单测因此从 100 秒涨到 350 秒。
    if postgres_persistence_configured():
        await asyncio.to_thread(refresh_state_if_stale, tenant_id)
    if auth_required_for_path(request) or request.headers.get("Authorization"):
        claims = predecoded_claims
        if claims is None:
            return audit_rejected_request(request, fail(errors.AUTH_REQUIRED, request), errors.AUTH_REQUIRED.reason)
        claimed_tenant = str(claims.get("tid") or "")
        if not repo.tenant_is_loaded(claimed_tenant):
            if postgres_persistence_configured() or repo.sqlite_enabled or repo.sqlite_path or os.getenv("AICHECK_SQLITE_PATH"):
                # N-5：这里原先无参调用 load_state()，即一律按 configured_tenant_id()
                # 加载，随后却把 claims.tid 标记为已加载。多租户部署重启后，
                # 非 configured 租户的数据在库里存在却永不加载——对使用方等同于数据丢失。
                load_state(tenant_id=claimed_tenant or None)
            repo.mark_tenant_loaded(claimed_tenant)
        user_record = user_record_by_username(claims.get("sub"), tenant_id=str(claims.get("tid") or ""))
        if user_record is None:
            return audit_rejected_request(request, fail(errors.AUTH_REQUIRED, request), "AUTH_USER_NOT_FOUND")
        if claims.get("role") != user_record.get("role") or int(claims.get("ver") or 0) != int(user_record.get("authVersion") or 0):
            return audit_rejected_request(
                request,
                fail(errors.AUTH_REQUIRED, request, message="登录身份已变化，请重新登录。"),
                "AUTH_IDENTITY_CHANGED",
            )
        if str(claims.get("tid") or "") != tenant_id_for_record(user_record):
            return audit_rejected_request(
                request,
                fail(errors.AUTH_REQUIRED, request, message="登录租户已变化，请重新登录。"),
                "AUTH_TENANT_CHANGED",
            )
        try:
            if await security_sessions.is_revoked(claims.get("jti")):
                return audit_rejected_request(
                    request,
                    fail(errors.AUTH_REQUIRED, request, message="登录已注销，请重新登录。"),
                    "AUTH_TOKEN_REVOKED",
                )
        except SecurityBackendUnavailable:
            return audit_rejected_request(
                request,
                fail(errors.SECURITY_BACKEND_UNAVAILABLE, request, http_status=503),
                errors.SECURITY_BACKEND_UNAVAILABLE.reason,
            )
        user = public_user(user_record)
        canonical_claims = {
            **claims,
            "role": user.get("role"),
            "ver": int(user_record.get("authVersion") or 0),
            "tid": tenant_id_for_record(user_record),
        }
        request.state.auth = canonical_claims
        request.state.auth_user = user
        password_change_paths = {"/auth/me", "/auth/logout", "/auth/change-password"}
        if user.get("mustChangePassword") and normalized_path not in password_change_paths:
            return audit_rejected_request(
                request,
                fail(errors.PASSWORD_CHANGE_REQUIRED, request, http_status=403),
                errors.PASSWORD_CHANGE_REQUIRED.reason,
            )
    admin_read_error = inferred_admin_read_error(request)
    if admin_read_error is not None:
        return audit_rejected_request(request, admin_read_error, errors.FORBIDDEN.reason)
    project_scope_error = inferred_project_scope_error(request)
    if project_scope_error is not None:
        return audit_rejected_request(request, project_scope_error, "PROJECT_SCOPE_DENIED")
    resource_scope_error = inferred_resource_scope_error(request)
    if resource_scope_error is not None:
        return audit_rejected_request(request, resource_scope_error, "RESOURCE_SCOPE_DENIED")
    action_error = inferred_action_error(request)
    if action_error is not None:
        return audit_rejected_request(request, action_error, "ACTION_DENIED")
    cached_idempotency = await idempotency_replay_response(request)
    if cached_idempotency is not None:
        return cached_idempotency
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        request.state.persistence_tenant_id = current_tenant_id()
        persistent = bool(
            postgres_persistence_configured()
            or repo.sqlite_enabled
            or repo.sqlite_path
            or os.getenv("AICHECK_SQLITE_PATH")
        )
        request.state.mutation_state_snapshot = repo.snapshot_current_tenant_runtime(
            include_state=not persistent
        )
    actor = getattr(request.state, "auth_user", None) or {}
    audit_context_token = set_request_audit_context(
        {
            "actorId": actor.get("id") or client_declared_identity(request) or "system",
            "actorName": (
                actor.get("displayName")
                or actor.get("name")
                or actor.get("username")
                or client_declared_identity(request)
                or "系统"
            ),
            "actorOrgName": actor.get("orgUnitName") or actor.get("orgName"),
            "actorOrgId": actor.get("orgId"),
            "actorRole": actor.get("role"),
            "tenantId": tenant_id_for_record(actor),
            "operationId": request.state.operation_id,
            "requestPath": canonical_path(request.url.path),
            "httpMethod": request.method,
            "clientIp": request.client.host if request.client else None,
            "userAgent": request.headers.get("User-Agent"),
        }
    )
    try:
        try:
            response = await call_next(request)
        except ConcurrentPersistenceError as exc:
            restore_failed_request_state(request)
            logger.warning("concurrent_persistence_conflict: %s", exc)
            return fail(
                errors.RESOURCE_STATE_CHANGED,
                request,
                message=str(
                    getattr(
                        request.state,
                        "persistence_conflict_message",
                        errors.RESOURCE_STATE_CHANGED.message,
                    )
                ),
                http_status=409,
            )
        except IllegalNodeStatusTransition as exc:
            # 非法的节点状态跳变是业务冲突，不是服务端故障——要给调用方看得懂的原因。
            restore_failed_request_state(request)
            logger.warning("illegal_node_status_transition: %s", exc)
            return fail(errors.CONFLICT, request, message=str(exc), http_status=409)
        except BaseException:
            restore_failed_request_state(request)
            raise
        persistence_tenant_id = str(
            getattr(request.state, "persistence_tenant_id", None) or current_tenant_id()
        )
        persistence_tenant_token = None
        persistence_audit_token = None
        if persistence_tenant_id != current_tenant_id():
            persistence_tenant_token = set_request_tenant_id(persistence_tenant_id)
            persistence_audit_token = set_request_audit_context(
                {**current_request_audit_context(), "tenantId": persistence_tenant_id}
            )
        try:
            response = await finalize_mutation_response(request, response)
            if should_flush_state(request):
                scoped_records = getattr(request.state, "scoped_flush_records", None)
                if callable(scoped_records):
                    records = scoped_records() or {}
                    operation_id = getattr(request.state, "operation_id", None)
                    audit_records = [
                        item
                        for item in repo.state.get("audit_logs", [])
                        if operation_id and item.get("operationId") == operation_id
                    ]
                    if audit_records:
                        records.setdefault("audit_logs", []).extend(audit_records)
                    scope = getattr(request.state, "idempotency_scope", None)
                    scoped_singleton_keys = {
                        key for key in records if key in SINGLETON_COLLECTIONS
                    }
                    if scoped_singleton_keys:
                        flush_state(
                            selected_state_keys={key for key in records if key in STATE_COLLECTIONS},
                            selected_singleton_keys=scoped_singleton_keys,
                        )
                    else:
                        flush_mutation_records(records, [scope] if scope else [])
                else:
                    state_keys = getattr(request.state, "flush_state_keys", None)
                    singleton_keys = getattr(request.state, "flush_singleton_keys", None)
                    flush_state(
                        selected_state_keys=(
                            set(state_keys) if state_keys is not None else API_FLUSH_STATE_KEYS
                        ),
                        selected_singleton_keys=set(singleton_keys) if singleton_keys is not None else None,
                    )
            return response
        except ConcurrentPersistenceError as exc:
            restore_failed_request_state(request)
            logger.warning("concurrent_persistence_conflict: %s", exc)
            return fail(
                errors.RESOURCE_STATE_CHANGED,
                request,
                message=str(
                    getattr(
                        request.state,
                        "persistence_conflict_message",
                        errors.RESOURCE_STATE_CHANGED.message,
                    )
                ),
                http_status=409,
            )
        except BaseException:
            restore_failed_request_state(request)
            raise
        finally:
            if persistence_audit_token is not None:
                reset_request_audit_context(persistence_audit_token)
            if persistence_tenant_token is not None:
                reset_request_tenant_id(persistence_tenant_token)
    finally:
        reset_request_audit_context(audit_context_token)


def restore_failed_request_state(request: Request) -> None:
    snapshot = getattr(request.state, "mutation_state_snapshot", None)
    if not isinstance(snapshot, dict):
        return
    tenant_id = str(snapshot.get("tenantId") or current_tenant_id())
    token = None
    if tenant_id != current_tenant_id():
        token = set_request_tenant_id(tenant_id)
    try:
        persistent = bool(
            postgres_persistence_configured()
            or repo.sqlite_enabled
            or repo.sqlite_path
            or os.getenv("AICHECK_SQLITE_PATH")
        )
        repo.restore_tenant_runtime(snapshot, invalidate=persistent)
    finally:
        if token is not None:
            reset_request_tenant_id(token)


def is_public_registration_request(request: Request) -> bool:
    path = request.url.path
    if not PUBLIC_REGISTRATION_LINK_PATTERN.fullmatch(path):
        return False
    if request.method == "GET":
        return bool(PUBLIC_REGISTRATION_LINK_INSPECT_PATTERN.fullmatch(path))
    if request.method == "POST":
        return bool(PUBLIC_REGISTRATION_LINK_APPLY_PATTERN.fullmatch(path))
    return False


def auth_required_for_path(request: Request) -> bool:
    if not authentication_enforced():
        return False
    if is_public_registration_request(request):
        return False
    public_prefixes = (
        "/healthz",
        "/api/healthz",
        "/readyz",
        "/api/readyz",
        "/auth/login",
        "/api/auth/login",
        "/runtime/ui-context",
        "/api/runtime/ui-context",
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
    actor = getattr(request.state, "auth_user", None) or {}
    claims = getattr(request.state, "auth", None) or {}
    tenant_id = str(claims.get("tid") or tenant_id_for_record(actor) or configured_tenant_id())
    actor_id = str(actor.get("id") or client_declared_identity(request) or "anonymous")
    role = str(claims.get("role") or request.headers.get("X-Role") or "anonymous")
    key_hash = idempotency_fingerprint(key)
    return f"{tenant_id}:{actor_id}:{role}:{request.method}:{canonical_path(request.url.path)}:{key_hash}"


#: 只有 worker 会写的大表：向量本体 61 MB、向量化断点批次 21 MB。
#:
#: 请求处理器从不写它们，但没声明范围的 flush 会把它们一并序列化去比对基线——
#: 实测全量 flush 17.4 秒，其中这两张表占 10.7 秒。而这段时间持有的锁，
#: 读路径也要拿：0819 实测一次写入期间 /api/healthz 连续 36s、53s、28s，
#: **不是写慢，是全站都慢**。
#:
#: 所以由 API 显式声明「我负责这些」，而不是在仓库层猜进程角色。
#: worker 侧的 flush 会显式带上这两张表（见 embed_knowledge 的收尾）。
API_OWNED_BULK_EXCLUSIONS = frozenset({"knowledge_vectors", "knowledge_embedding_batches"})
API_FLUSH_STATE_KEYS = frozenset(STATE_COLLECTIONS) - API_OWNED_BULK_EXCLUSIONS


def should_flush_state(request: Request) -> bool:
    if callable(getattr(request.state, "scoped_flush_records", None)):
        return True
    if bool(getattr(request.state, "force_flush_state", False)):
        return True
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
        except (ValueError, UnicodeDecodeError):
            parsed_body = {
                "kind": "binary",
                "contentType": request.headers.get("Content-Type"),
                "contentLength": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
            }
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
    if postgres_persistence_configured():
        try:
            lock_connection, persisted = await asyncio.to_thread(
                acquire_idempotency_lock,
                scope,
                str((getattr(request.state, "auth", None) or {}).get("tid") or configured_tenant_id()),
            )
        except Exception as exc:
            logger.exception("idempotency_lock_failed", extra={"scope": scope})
            return fail(
                errors.SECURITY_BACKEND_UNAVAILABLE,
                request,
                message="幂等协调服务暂不可用。",
                data={"errorType": type(exc).__name__},
                http_status=503,
            )
        request.state.idempotency_lock_connection = lock_connection
        if isinstance(persisted, dict):
            repo.state["idempotency"][scope] = persisted
    cached = repo.state["idempotency"].get(scope)
    if not isinstance(cached, dict) or "response" not in cached:
        return None
    if cached.get("requestHash") and cached["requestHash"] != fingerprint:
        return fail(errors.IDEMPOTENCY_KEY_CONFLICT, request)
    if cached.get("authorizationDigest") != request_authorization_digest(request):
        # 旧格式（全局成员快照）就地升级：旧口径仍吻合说明授权没有实质变化
        if cached.get("authorizationDigest") != request_authorization_digest(request, all_projects=True):
            return fail(errors.FORBIDDEN, request, message="当前授权上下文已变化，不能重放历史响应。", http_status=403)
        cached["authorizationDigest"] = request_authorization_digest(request)
    return JSONResponse(
        repo.clone(cached["response"]),
        status_code=int(cached.get("httpStatus") or 200),
        headers={"Idempotency-Replayed": "true"},
    )


def acquire_idempotency_lock(scope: str, tenant_id: str, dsn_override: str | None = None):
    """Hold a PostgreSQL session lock until the request's mutation transaction completes."""

    import psycopg

    dsn = dsn_override or repo.postgres_dsn or os.getenv("AICHECK_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not dsn:
        raise RuntimeError("PostgreSQL DSN is required for distributed idempotency")
    connection = psycopg.connect(dsn, autocommit=True)
    try:
        timeout_ms = max(100, min(int(os.getenv("AICHECK_IDEMPOTENCY_LOCK_TIMEOUT_MS", "5000")), 60_000))
        connection.execute(f"SET lock_timeout = '{timeout_ms}ms'")
        connection.execute("SELECT pg_advisory_lock(hashtextextended(%s, 0))", (scope,))
        row = connection.execute(
            "SELECT payload FROM idempotency_records WHERE tenant_id = %s AND scope = %s",
            (tenant_id, scope),
        ).fetchone()
        return connection, (dict(row[0]) if row else None)
    except Exception:
        connection.close()
        raise


def release_idempotency_lock(connection, request: Request) -> None:
    scope = getattr(request.state, "idempotency_scope", None)
    try:
        if scope:
            connection.execute("SELECT pg_advisory_unlock(hashtextextended(%s, 0))", (scope,))
    finally:
        connection.close()


def client_declared_identity(request: Request) -> str | None:
    """X-User-Id 是客户端自称的身份——任何人都能填任何值。

    审计留痕、幂等作用域、授权摘要三处都以它为键，采信等于让调用方自选身份：
    可以把操作记到别人名下，也可以挤进别人的幂等作用域。所以认证开启时一律不采信，
    没有 auth_user 就是没有身份，如实记成 system/anonymous。

    认证关闭时（本地开发 / demo）才回退——那个姿态本身在启动时已有显式告警（S-1），
    不需要在这里再兜一层。
    """
    if authentication_enforced():
        return None
    value = str(request.headers.get("X-User-Id") or "").strip()
    return value or None


def request_authorization_digest(request: Request, *, all_projects: bool = False) -> str:
    """幂等重放的授权摘要。成员关系**只取请求所涉项目**——
    粒度与 mutation_guard 的授权判定一致；全局口径的事故见
    authorization_membership_snapshot 的说明（0819：加入新项目击穿
    该用户在所有项目的缓存重放）。all_projects=True 仅用于旧格式兼容。"""
    actor = getattr(request.state, "auth_user", None) or {}
    claims = getattr(request.state, "auth", None) or {}
    user_id = str(actor.get("id") or client_declared_identity(request) or "anonymous")
    tenant_id = str(claims.get("tid") or tenant_id_for_record(actor) or configured_tenant_id())
    role = str(claims.get("role") or request.headers.get("X-Role") or "anonymous")
    memberships = authorization_membership_snapshot(
        request, user_id, tenant_id, all_projects=all_projects
    )
    return idempotency_fingerprint(
        {"tenantId": tenant_id, "actorId": user_id, "role": role, "memberships": memberships}
    )


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
    except (ValueError, UnicodeDecodeError):
        return replay_response
    if response.status_code == 200 and isinstance(payload, dict) and payload.get("code") == 0:
        if scope:
            actor = getattr(request.state, "auth_user", None) or {}
            claims = getattr(request.state, "auth", None) or {}
            repo.state["idempotency"][scope] = {
                "requestHash": getattr(request.state, "idempotency_fingerprint", None),
                "authorizationDigest": request_authorization_digest(request),
                "tenantId": claims.get("tid") or tenant_id_for_record(actor) or configured_tenant_id(),
                "actorId": actor.get("id") or request.headers.get("X-User-Id") or "anonymous",
                "actorRole": claims.get("role") or request.headers.get("X-Role") or "anonymous",
                "response": repo.clone(payload),
                "httpStatus": response.status_code,
            }
        audit_successful_mutation(request, payload)
    elif isinstance(payload, dict) and payload.get("code") not in {None, 0}:
        audit_failed_mutation(request, payload, response.status_code)
    return replay_response


def request_audit_context(request: Request) -> dict[str, Any]:
    actor = getattr(request.state, "auth_user", None) or {}
    claims = getattr(request.state, "auth", None) or {}
    return {
        "actorId": actor.get("id") or request.headers.get("X-User-Id") or "anonymous",
        "actorName": actor.get("displayName") or actor.get("name") or actor.get("username") or "匿名请求",
        "actorOrgName": actor.get("orgUnitName") or actor.get("orgName"),
        "actorOrgId": actor.get("orgId"),
        "actorRole": claims.get("role") or actor.get("role"),
        "tenantId": claims.get("tid") or tenant_id_for_record(actor) or configured_tenant_id(),
        "operationId": getattr(request.state, "operation_id", None),
        "requestPath": canonical_path(request.url.path),
        "httpMethod": request.method,
        "clientIp": request.client.host if request.client else None,
        "userAgent": request.headers.get("User-Agent"),
    }


def audit_rejected_request(request: Request, response: JSONResponse, reason_code: str) -> JSONResponse:
    token = set_request_audit_context(request_audit_context(request))
    try:
        audit_id = repo.add_audit(
            f"拒绝 {request.method} {canonical_path(request.url.path)}",
            "SecurityEvent",
            canonical_path(request.url.path),
            result="失败",
            error_code=reason_code,
            outcome="denied",
        )
        audit = repo.find_one("audit_logs", audit_id)
        if audit:
            flush_mutation_records({"audit_logs": [audit]}, [])
    except Exception:
        logger.exception(
            "security_audit_write_failed",
            extra={"operation_id": getattr(request.state, "operation_id", None), "reason_code": reason_code},
        )
    finally:
        reset_request_audit_context(token)
    return response


def audit_failed_mutation(request: Request, payload: dict[str, Any], http_status: int) -> None:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    reason = str(data.get("reason") or "MUTATION_FAILED")
    repo.add_audit(
        f"失败 {request.method} {canonical_path(request.url.path)}",
        "ApiMutation",
        canonical_path(request.url.path),
        result="失败",
        error_code=reason,
        outcome="denied" if http_status in {401, 403, 404} else "failed",
    )


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
    repo.add_audit(
        f"{request.method} {normalized_path}",
        "ApiMutation",
        normalized_path,
    )


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


def inferred_resource_scope_error(request: Request) -> JSONResponse | None:
    """Authorize id-based resources before any idempotency replay can occur."""

    normalized_path = canonical_path(request.url.path)
    review_match = re.match(r"^/review-runs/([^/]+)(?:/|$)", normalized_path)
    if review_match:
        review_run_id = review_match.group(1)
        run = repo.find_one("review_runs", review_run_id, id_field="reviewRunId") or repo.find_one(
            "review_runs", review_run_id
        )
        if run:
            return scope_error_for_record(request, run)
    return None


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
    role = token_role or (header_role if not auth_required_for_path(request) else None)
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
    logger.exception(
        "unhandled_api_exception",
        extra={
            "operation_id": getattr(request.state, "operation_id", None),
            "method": request.method,
            "path": canonical_path(request.url.path),
            "exception_type": type(exc).__name__,
        },
    )
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


@app.get("/readyz", tags=["system"])
async def readyz():
    return await readiness_response()


@app.get("/api/readyz", tags=["system"])
async def api_readyz():
    return await readiness_response()


async def readiness_response():
    health = await health_payload()
    checks = {
        "database": bool(health.get("databaseConnected")),
        "security": bool(health.get("securityReady")),
        "runtime": bool(health.get("runtimeReady")),
        "workflow": bool(health.get("workflowReady")),
        **database_schema_readiness(),
    }
    if strict_production():
        checks["rawVault"] = bool((health.get("rawVault") or {}).get("ready"))
    ready = all(checks.values())
    return JSONResponse(
        {
            "status": "ready" if ready else "not_ready",
            "ready": ready,
            "checks": checks,
            "authRequired": authentication_enforced(),
        },
        status_code=200 if ready else 503,
    )


def database_schema_readiness() -> dict[str, bool]:
    if not repo.postgres_enabled:
        return {"schema": False, "auditAnchor": False}
    try:
        from scripts.migrate_backend import validate_migration_manifest

        declared = validate_migration_manifest()
        with repo.postgres_connection() as connection:
            table_exists = connection.execute(
                "SELECT to_regclass('schema_migrations') IS NOT NULL"
            ).fetchone()[0]
            applied = (
                {
                    str(version): str(checksum)
                    for version, checksum in connection.execute(
                        "SELECT version, checksum FROM schema_migrations"
                    ).fetchall()
                }
                if table_exists
                else {}
            )
            head = connection.execute(
                "SELECT max(sequence) FROM audit_events WHERE tenant_id=%s",
                (configured_tenant_id(),),
            ).fetchone()[0]
            anchor = connection.execute(
                "SELECT max(head_sequence) FROM audit_chain_anchors WHERE tenant_id=%s",
                (configured_tenant_id(),),
            ).fetchone()[0]
            connection.rollback()
        schema_ready = applied == declared
        anchor_required = os.getenv("AICHECK_REQUIRE_AUDIT_ANCHOR", "false").lower() == "true"
        anchor_ready = (
            not anchor_required
            or head is None
            or (anchor is not None and int(anchor) >= int(head))
        )
        return {"schema": schema_ready, "auditAnchor": anchor_ready}
    except Exception:
        return {"schema": False, "auditAnchor": False}


async def health_response(request: Request):
    payload = await health_payload()
    if strict_production() and (
        not payload["databaseConnected"]
        or not payload["securityReady"]
        or not payload["runtimeReady"]
        or not payload["workflowReady"]
        or not (payload.get("rawVault") or {}).get("ready")
        or not (payload.get("mineruWorker") or {}).get("ready")
    ):
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
    if authentication_enforced() and (not claims or claims.get("role") != "admin"):
        return fail(errors.FORBIDDEN, request, message="仅管理员可执行 PostgreSQL transaction 探针。")
    return ok(await run_transaction_probe(getattr(request.app.state, "postgres", None)), request)


async def health_payload() -> dict[str, object]:
    database_backend = "postgres" if repo.postgres_enabled else "sqlite" if repo.sqlite_enabled else "memory"
    database_connected = database_backend != "memory"
    if repo.postgres_enabled and (
        repo.sync_postgres is not None
        or repo.postgres_dsn
        or os.getenv("AICHECK_DATABASE_URL")
        or os.getenv("DATABASE_URL")
    ):
        database_connected = await asyncio.to_thread(repo.ensure_sync_postgres_connection)
    rate_limiter_ready = await security_sessions.ready()
    model_attempts = [
        item
        for item in repo.state.get("model_call_attempts", [])
        if item.get("provider") in {"aliyun_model_studio", "Model Studio / DashScope"}
    ]
    successful_attempts = [item for item in model_attempts if item.get("status") == "success"]
    latest_success = max(
        successful_attempts,
        key=lambda item: str(item.get("finishedAt") or item.get("updatedAt") or ""),
        default=None,
    )
    runtime_readiness = await asyncio.to_thread(
        production_runtime_status,
        refresh_review_readiness=True,
    )
    temporal = dict(runtime_readiness.get("temporalReadiness") or {})
    workflow_metrics = await asyncio.to_thread(review_workflow_metrics)
    shared_worker_heartbeat = (
        (runtime_readiness.get("reviewDispatchReadiness") or {})
        .get("dependencyDetails", {})
        .get("workerHeartbeat")
    )
    if isinstance(shared_worker_heartbeat, dict):
        workflow_metrics["reviewWorkerHeartbeat"] = shared_worker_heartbeat
    workflow_ready = bool(runtime_readiness.get("workflowReady"))
    raw_vault = await asyncio.to_thread(raw_vault_health_status)
    mineru_worker = await asyncio.to_thread(mineru_worker_health_status)
    return {
        "status": "ok",
        "service": "api-service",
        "databaseBackend": database_backend,
        "databaseConnected": database_connected,
        "postgresEnabled": repo.postgres_enabled,
        "postgresTransactions": bool(repo.postgres_enabled),
        "sqliteEnabled": repo.sqlite_enabled,
        "sqlitePath": repo.sqlite_path,
        "authRequired": authentication_enforced(),
        "demoUsersEnabled": demo_users_enabled(),
        "workflowReady": workflow_ready,
        "temporal": temporal,
        "workflowMetrics": workflow_metrics,
        "rawVault": raw_vault,
        "mineruWorker": mineru_worker,
        "objectStorageEnabled": object_storage.enabled,
        "officialOcrTelemetry": {
            "lastSuccessfulInferenceAt": (latest_success or {}).get("finishedAt")
            or (latest_success or {}).get("updatedAt"),
            "model": (latest_success or {}).get("model"),
            "attemptCount": len(model_attempts),
            "successCount": len(successful_attempts),
        },
        **runtime_readiness,
        **security_runtime_status(rate_limiter_ready=rate_limiter_ready),
    }


def mineru_worker_health_status() -> dict[str, object]:
    required = mineru_execution_mode() == "postgres"
    status: dict[str, object] = {
        "required": required,
        "ready": not required,
        "instanceId": None,
        "activeCount": 0,
        "lastSeenAt": None,
        "lastError": None,
    }
    dsn = os.getenv("AICHECK_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not dsn:
        if required:
            status["lastError"] = "DATABASE_NOT_CONFIGURED"
        return status
    try:
        import psycopg

        with psycopg.connect(dsn) as connection:
            row = connection.execute(
                """
                SELECT instance_id,
                       payload,
                       last_seen_at,
                       last_seen_at >= now() - interval '30 seconds'
                FROM service_heartbeats
                WHERE service_role = 'mineru-worker'
                ORDER BY last_seen_at DESC
                LIMIT 1
                """
            ).fetchone()
            connection.rollback()
        if not row:
            return status
        payload = dict(row[1] or {})
        fresh = bool(row[3])
        status.update(
            {
                "ready": fresh or not required,
                "instanceId": str(row[0]),
                "activeCount": int(payload.get("activeCount") or 0),
                "lastSeenAt": row[2].isoformat() if row[2] else None,
                "lastError": payload.get("lastError"),
            }
        )
    except Exception as exc:
        status["ready"] = not required
        status["lastError"] = type(exc).__name__
    return status


def raw_vault_health_status() -> dict[str, object]:
    dsn = os.getenv("AICHECK_DATABASE_URL") or os.getenv("DATABASE_URL")
    configured = bool(dsn and object_storage.enabled)
    status: dict[str, object] = {
        "configured": configured,
        "ready": False,
        "schemaReady": False,
        "relayReady": False,
        "bucketLocked": False,
        "legalHoldCapable": False,
        "pendingCount": 0,
        "pendingBytes": 0,
        "oldestPendingAgeSeconds": None,
        "integrityFailureCount": 0,
    }
    if not configured:
        return status
    try:
        client = object_storage.client()
        bucket = object_storage.bucket_name("agent-raw-vault")
        if client is not None and client.bucket_exists(bucket):
            lock_config = client.get_object_lock_config(bucket)
            lock_status = str(getattr(lock_config, "status", "") or "").upper()
            status["bucketLocked"] = lock_status == "ENABLED"
            status["legalHoldCapable"] = status["bucketLocked"]
    except Exception:
        pass
    try:
        import psycopg

        with psycopg.connect(str(dsn)) as connection:
            schema_row = connection.execute(
                """
                SELECT to_regclass('raw_vault_events') IS NOT NULL,
                       to_regclass('raw_vault_outbox') IS NOT NULL
                """
            ).fetchone()
            status["schemaReady"] = bool(schema_row and schema_row[0] and schema_row[1])
            backlog = connection.execute(
                """
                SELECT count(*), COALESCE(sum(octet_length(payload)), 0),
                       EXTRACT(EPOCH FROM now() - min(created_at)),
                       count(*) FILTER (WHERE status = 'hash_mismatch')
                FROM raw_vault_outbox
                """
            ).fetchone()
            if backlog:
                status["pendingCount"] = int(backlog[0] or 0)
                status["pendingBytes"] = int(backlog[1] or 0)
                status["oldestPendingAgeSeconds"] = (
                    float(backlog[2]) if backlog[2] is not None else None
                )
                status["integrityFailureCount"] = int(backlog[3] or 0)
            heartbeat = connection.execute(
                """
                SELECT 1
                FROM service_heartbeats
                WHERE service_role = 'review-worker'
                  AND last_seen_at >= now() - interval '60 seconds'
                  AND COALESCE((payload ->> 'rawVaultRelay')::boolean, false)
                LIMIT 1
                """
            ).fetchone()
            status["relayReady"] = bool(heartbeat)
    except Exception as exc:
        status["reason"] = f"{type(exc).__name__}: raw vault readiness probe failed"
    status["ready"] = bool(
        status["configured"]
        and status["schemaReady"]
        and status["relayReady"]
        and status["bucketLocked"]
        and status["legalHoldCapable"]
        and int(status["integrityFailureCount"] or 0) == 0
    )
    return status


def review_workflow_metrics() -> dict[str, object]:
    runs = repo.state.get("review_runs", [])
    pending_outbox = [
        item
        for item in repo.state.get("workflow_outbox", [])
        if item.get("status") in {"pending", "retry_pending"}
    ]
    cutoff = datetime.now() - timedelta(minutes=30)
    stuck_runs = 0
    for run in runs:
        if run.get("status") not in {"queued", "running", "retry_pending"}:
            continue
        raw_updated = str(run.get("updatedAt") or run.get("createdAt") or "")
        parsed = None
        for candidate in (raw_updated, raw_updated.replace("Z", "+00:00")):
            try:
                parsed = datetime.fromisoformat(candidate)
                break
            except ValueError:
                continue
        if parsed is not None and parsed.replace(tzinfo=None) < cutoff:
            stuck_runs += 1
    worker_heartbeat: dict[str, object] = {"ready": False, "activeCount": 0, "lastSeenAt": None}
    outbox_pending_count = len(pending_outbox)
    outbox_max_attempts = max((int(item.get("attempts") or 0) for item in pending_outbox), default=0)
    outbox_oldest_age_seconds: float | None = None
    if repo.postgres_dsn or os.getenv("AICHECK_DATABASE_URL") or os.getenv("DATABASE_URL"):
        try:
            with repo.postgres_connection() as connection:
                heartbeat_row = connection.execute(
                    """
                    SELECT count(*) FILTER (WHERE last_seen_at >= now() - interval '30 seconds'),
                           max(last_seen_at)
                    FROM service_heartbeats
                    WHERE service_role = 'review-worker'
                    """
                ).fetchone()
                outbox_row = connection.execute(
                    """
                    SELECT count(*),
                           max(COALESCE((payload ->> 'attempts')::integer, 0)),
                           extract(epoch FROM (now() - min(updated_at)))
                    FROM aicheck_state
                    WHERE collection = 'workflow_outbox'
                      AND payload ->> 'status' IN ('pending', 'retry_pending', 'delivering')
                    """
                ).fetchone()
                connection.rollback()
            active_count = int((heartbeat_row or [0])[0] or 0)
            worker_heartbeat = {
                "ready": active_count > 0,
                "activeCount": active_count,
                "lastSeenAt": heartbeat_row[1].isoformat() if heartbeat_row and heartbeat_row[1] else None,
            }
            if outbox_row:
                outbox_pending_count = int(outbox_row[0] or 0)
                outbox_max_attempts = int(outbox_row[1] or 0)
                outbox_oldest_age_seconds = float(outbox_row[2]) if outbox_row[2] is not None else None
        except Exception as exc:
            worker_heartbeat = {
                "ready": False,
                "activeCount": 0,
                "lastSeenAt": None,
                "error": str(exc)[:200],
            }
    return {
        "queuedRuns": sum(1 for item in runs if item.get("status") == "queued"),
        "runningRuns": sum(1 for item in runs if item.get("status") == "running"),
        "retryPendingRuns": sum(1 for item in runs if item.get("status") == "retry_pending"),
        "failedRuns": sum(1 for item in runs if item.get("status") in {"failed", "failed_to_start"}),
        "stuckRunCount": stuck_runs,
        "outboxPendingCount": outbox_pending_count,
        "outboxMaxAttempts": outbox_max_attempts,
        "outboxOldestAgeSeconds": outbox_oldest_age_seconds,
        "reviewWorkerHeartbeat": worker_heartbeat,
    }


async def temporal_health_status() -> dict[str, object]:
    mode = review_orchestration_mode()
    if mode != "temporal":
        return {
            "mode": mode,
            "configured": False,
            "ready": not strict_production(),
            "reason": "Temporal orchestration is not selected.",
        }
    address = os.getenv("TEMPORAL_ADDRESS", "localhost:7233")
    namespace = os.getenv("TEMPORAL_NAMESPACE", "default")
    try:
        from temporalio.client import Client

        await asyncio.wait_for(Client.connect(address, namespace=namespace), timeout=2.0)
    except Exception as exc:
        return {
            "mode": mode,
            "configured": True,
            "ready": False,
            "address": address,
            "namespace": namespace,
            "errorType": type(exc).__name__,
        }
    return {
        "mode": mode,
        "configured": True,
        "ready": True,
        "address": address,
        "namespace": namespace,
    }


if compatibility_mocks_enabled():
    app.include_router(mock_router)
    app.include_router(mock_router, prefix="/api")
app.include_router(router)
app.include_router(router, prefix="/api")
# 一键审查拆在独立模块：routes.py 的行数棘轮卡在上限，往里加会触发棘轮，
# 抬高上限则等于把这条约束取消掉。新端点一律挂在这里。
app.include_router(batch_review_router)
app.include_router(batch_review_router, prefix="/api")
app.include_router(auto_review_router)
app.include_router(auto_review_router, prefix="/api")
app.include_router(project_analysis_router)
app.include_router(project_analysis_router, prefix="/api")
app.include_router(org_delegation_router)
app.include_router(org_delegation_router, prefix="/api")
app.include_router(document_category_router)
app.include_router(document_category_router, prefix="/api")
app.include_router(project_registration_router)
app.include_router(project_registration_router, prefix="/api")
app.include_router(cnse_router)
app.include_router(cnse_router, prefix="/api")
app.include_router(std_samr_router)
app.include_router(std_samr_router, prefix="/api")
app.include_router(mineru_ocr_router)
app.include_router(mineru_ocr_router, prefix="/api")
