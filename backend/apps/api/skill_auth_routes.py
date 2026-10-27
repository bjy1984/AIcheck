"""skill 网页授权（授权码 + PKCE，回调本机）。流程见 libs/security/skill_auth.py。

- POST /auth/skill/authorize：要登录。浏览器里的授权页调用，只有监检和管理员能授权；
  返回一次性授权码，页面再把浏览器带回 skill 在本机开的回调地址。
- POST /auth/skill/token：公开（凭授权码换，和 /auth/login 一样不带令牌）。
  skill 出示授权码、PKCE 校验码和同一个回调地址，换回与该账号登录时一样的令牌。

两个接口都不写 repo.state，只记一条审计（和登录一样只落盘本次请求的审计记录）。
"""
from __future__ import annotations

import os
import secrets
import time
from typing import Any

from fastapi import APIRouter, Body, Request

from apps.api.routes import effective_role_for_request, request_tenant_id
from libs.audit_context import (
    current_request_audit_context,
    reset_request_audit_context,
    set_request_audit_context,
)
from libs.contracts import errors
from libs.contracts.responses import fail, ok
from libs.db.repository import load_state, postgres_persistence_configured, repo
from libs.security.auth import issue_token, public_user, user_record_by_username
from libs.security.session import SecurityBackendUnavailable
from libs.security.skill_auth import (
    ALLOWED_ROLES,
    CLIENT_NAME,
    CODE_TTL_SECONDS,
    loopback_redirect_uri,
    pkce_matches,
    skill_auth_codes,
    valid_challenge,
    valid_code,
    valid_verifier,
)
from libs.security.tenant import (
    current_tenant_id,
    reset_request_tenant_id,
    set_request_tenant_id,
    tenant_is_allowed,
)

skill_auth_router = APIRouter(prefix="/auth/skill")


@skill_auth_router.post("/authorize")
async def authorize_skill(request: Request, body: dict[str, Any] = Body(default_factory=dict)):
    claims = getattr(request.state, "auth", None) or {}
    username = str(claims.get("sub") or "")
    if not username:
        return fail(errors.AUTH_REQUIRED, request, message="请先在平台上登录，再给 skill 授权。", http_status=401)
    role, error = effective_role_for_request(request, request.headers.get("X-Role"))
    if error is not None:
        return error
    if role not in ALLOWED_ROLES:
        return fail(errors.FORBIDDEN, request, message="当前账号不能给 skill 授权：请用监检或管理员账号登录。", http_status=403)
    redirect_uri = loopback_redirect_uri(body.get("redirectUri"))
    if not redirect_uri:
        return fail(errors.VALIDATION_ERROR, request, message="回调地址只能是本机的 http://127.0.0.1:<端口>/callback。", http_status=400)
    if body.get("codeChallengeMethod") != "S256" or not valid_challenge(body.get("codeChallenge")):
        return fail(errors.VALIDATION_ERROR, request, message="缺少有效的 PKCE 校验（S256）。", http_status=400)
    code = secrets.token_urlsafe(32)
    record = {
        "username": username,
        "tenantId": request_tenant_id(request),
        "redirectUri": redirect_uri,
        "codeChallenge": body["codeChallenge"],
        "issuedAt": int(time.time()),
    }
    try:
        await skill_auth_codes.put(code, record)
    except SecurityBackendUnavailable:
        return fail(errors.SECURITY_BACKEND_UNAVAILABLE, request, http_status=503)
    repo.add_audit("授权 skill 访问", "Authentication", username)
    request.state.scoped_flush_records = dict
    return ok({"code": code, "expiresIn": CODE_TTL_SECONDS, "client": CLIENT_NAME}, request)


@skill_auth_router.post("/token")
async def exchange_skill_code(request: Request, body: dict[str, Any] = Body(default_factory=dict)):
    code, verifier = body.get("code"), body.get("codeVerifier")
    redirect_uri = loopback_redirect_uri(body.get("redirectUri"))
    if not (valid_code(code) and valid_verifier(verifier) and redirect_uri):
        return fail(errors.VALIDATION_ERROR, request, message="请求缺少授权码、校验码或回调地址。", http_status=400)
    invalid = fail(errors.VALIDATION_ERROR, request, message="授权码无效、已用过或已过期：重新运行 login --web。", http_status=400)
    try:
        record = await skill_auth_codes.take(code)  # 先取出作废再校验：校验失败的码也不能再试
    except SecurityBackendUnavailable:
        return fail(errors.SECURITY_BACKEND_UNAVAILABLE, request, http_status=503)
    if not record or record.get("redirectUri") != redirect_uri or not pkce_matches(verifier, str(record.get("codeChallenge") or "")):
        return invalid
    tenant_id = str(record.get("tenantId") or current_tenant_id())
    if not tenant_is_allowed(tenant_id):
        return invalid
    # 和 /auth/login 一样按授权时的租户加载、记审计；这里没有令牌，租户只能从授权码记录里来。
    request.state.persistence_tenant_id = tenant_id
    tenant_token = set_request_tenant_id(tenant_id)
    audit_token = set_request_audit_context({**current_request_audit_context(), "tenantId": tenant_id})
    try:
        persistent = bool(
            postgres_persistence_configured() or repo.sqlite_enabled or repo.sqlite_path or os.getenv("AICHECK_SQLITE_PATH")
        )
        if not repo.tenant_is_loaded(tenant_id):
            if persistent:
                load_state(tenant_id=tenant_id or None)
            repo.mark_tenant_loaded(tenant_id)
        request.state.mutation_state_snapshot = repo.snapshot_current_tenant_runtime(include_state=not persistent)
        stored = user_record_by_username(record.get("username"), tenant_id=tenant_id)
        if not stored:
            return fail(errors.FORBIDDEN, request, message="授权的账号已停用或不存在。", http_status=403)
        user = public_user(stored)
        if user.get("role") not in ALLOWED_ROLES:
            return fail(errors.FORBIDDEN, request, message="授权的账号已不是监检或管理员，不能给 skill 用。", http_status=403)
        identity_token = set_request_audit_context(
            {
                **current_request_audit_context(),
                "actorId": user.get("id") or user["username"],
                "actorName": user.get("displayName") or user["username"],
                "actorRole": user.get("role"),
            }
        )
        try:
            try:
                token = issue_token(user)
            except Exception:  # noqa: BLE001 — 同 /auth/login：签发失败（缺 PyJWT、密钥配置）一律报 503，不外泄细节
                return fail(errors.SECURITY_BACKEND_UNAVAILABLE, request, message="令牌签发服务暂不可用。", http_status=503)
            repo.add_audit("skill 网页授权换取令牌", "Authentication", user["username"])
            request.state.scoped_flush_records = dict
            return ok({"token": token, "user": user}, request)
        finally:
            reset_request_audit_context(identity_token)
    finally:
        reset_request_audit_context(audit_token)
        reset_request_tenant_id(tenant_token)
