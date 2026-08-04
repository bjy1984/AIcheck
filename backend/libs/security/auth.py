from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from libs.security.tenant import current_tenant_id, configured_tenant_id, tenant_id_for_record

try:
    import jwt
except Exception:  # pragma: no cover - validated at startup in strict mode
    jwt = None  # type: ignore[assignment]


JWT_SECRET = "aicheck-dev-secret-change-me-unsafe"
JWT_ALGORITHM = "HS256"
JWT_ISSUER = "aicheck-api"
JWT_AUDIENCE = "aicheck-frontend"
DEFAULT_INITIAL_PASSWORD = "anyuekeji.123"
COMMON_PASSWORDS = {
    "123456",
    "12345678",
    "123456789",
    "admin",
    "admin123",
    "aicheck",
    "changeme",
    "letmein",
    "password",
    "password123",
    "qwerty",
    "qwerty123",
    "welcome",
    "welcome123",
}

ROLE_DEFAULT_PATHS = {
    "inspection": "/workbench/inspection",
    "contractor": "/workbench/contractor",
    "ndt": "/workbench/ndt",
    "owner": "/workbench/owner",
    "admin": "/admin/overview",
    "fde": "/fde/dashboard",
    "test": "/workbench/inspection",
}


def strict_production() -> bool:
    return os.getenv("AICHECK_STRICT_PRODUCTION", "false").lower() == "true"


def demo_users_enabled() -> bool:
    return os.getenv("AICHECK_ENABLE_DEMO_USERS", "true").lower() == "true"


def dev_tokens_allowed() -> bool:
    return (
        not strict_production()
        and demo_users_enabled()
        and os.getenv("AICHECK_ALLOW_DEV_TOKENS", "false").lower() == "true"
    )


def compatibility_mocks_enabled() -> bool:
    if strict_production():
        return False
    return os.getenv("AICHECK_ENABLE_COMPATIBILITY_MOCKS", "false").lower() == "true"


def user_record(
    user_id: str,
    username: str,
    role: str,
    role_id: str,
    role_label: str,
    display_name: str,
    org_unit_name: str,
    permissions: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": user_id,
        "username": username,
        "password": username,
        "passwordHash": f"plain:{username}",
        "role": role,
        "roleId": role_id,
        "roleLabel": role_label,
        "permissions": permissions or [f"{role}:default"],
        "displayName": display_name,
        "orgUnitName": org_unit_name,
        "defaultPath": ROLE_DEFAULT_PATHS.get(role, ROLE_DEFAULT_PATHS["inspection"]),
        "authVersion": 0,
        "mustChangePassword": False,
        "tenantId": configured_tenant_id(),
    }


USERS = {
    "inspection": user_record("USER-INSPECTION-001", "inspection", "inspection", "2", "监检人员", "张工", "省特检院一部"),
    "contractor": user_record("USER-CONTRACTOR-001", "contractor", "contractor", "3", "施工方", "李工", "中石化安装有限公司"),
    "ndt": user_record("USER-NDT-001", "ndt", "ndt", "4", "无损检测", "王工", "华测检测有限公司"),
    "owner": user_record("USER-OWNER-001", "owner", "owner", "5", "建设方", "赵经理", "华东管网建设公司"),
    "admin": user_record("USER-ADMIN-001", "admin", "admin", "1", "系统管理员", "系统管理员", "省特检院平台组", ["*.*.*"]),
    "fde": user_record("USER-FDE-001", "fde", "fde", "6", "FDE", "FDE 工程师", "AI 交付治理组", ["fde:dashboard:view", "fde:ai-run:view-masked", "fde:ai-run:replay", "fde:feedback:view", "fde:feedback:triage", "fde:evaluation:view", "fde:evaluation:manage", "fde:evaluation:run", "fde:business-pack:view", "fde:business-pack:validate", "fde:business-pack:install", "fde:capability-bundle:manage", "fde:release:view", "fde:release:submit", "fde:release:shadow", "fde:release:canary", "fde:release:rollback", "fde:ocr-quality:view", "fde:ocr-annotation:manage", "fde:vector-quality:view", "fde:vector-quality:review", "fde:vector-quality:apply", "fde:incident:manage", "fde:security:manage", "fde:cost:manage", "fde:config:draft"]),
    "test": user_record("USER-TEST-001", "test", "test", "9", "测试用户", "测试用户", "联调测试组", ["example:dialog:create", "example:dialog:delete"]),
}


def verify_password(password: str, stored_hash: str | None, legacy_password: str | None = None) -> bool:
    if stored_hash:
        if stored_hash.startswith("plain:"):
            return not strict_production() and password == stored_hash.removeprefix("plain:")
        if stored_hash.startswith("pbkdf2_sha256$"):
            try:
                _, iterations, salt, expected = stored_hash.split("$", 3)
                digest = hashlib.pbkdf2_hmac(
                    "sha256",
                    password.encode("utf-8"),
                    salt.encode("utf-8"),
                    int(iterations),
                ).hex()
            except Exception:
                return False
            return hmac.compare_digest(digest, expected)
    if legacy_password and not strict_production() and os.getenv("AICHECK_ALLOW_LEGACY_PLAIN_PASSWORDS", "false").lower() == "true":
        return hmac.compare_digest(password, legacy_password)
    return False


def hash_password(password: str) -> str:
    iterations = 210_000
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    ).hex()
    return f"pbkdf2_sha256${iterations}${salt}${digest}"


def password_strength_errors(username: str, password: str) -> list[str]:
    errors: list[str] = []
    normalized_username = username.strip().lower()
    if len(password) < 12:
        errors.append("密码长度至少为 12 位")
    if normalized_username and normalized_username in password.lower():
        errors.append("密码不得包含用户名")
    classes = (
        bool(re.search(r"[a-z]", password)),
        bool(re.search(r"[A-Z]", password)),
        bool(re.search(r"\d", password)),
        bool(re.search(r"[^A-Za-z0-9]", password)),
    )
    if sum(classes) < 3:
        errors.append("密码至少包含大写字母、小写字母、数字、特殊字符中的三类")
    normalized_password = re.sub(r"[^a-z0-9]", "", password.lower())
    normalized_username_password = re.sub(r"[^a-z0-9]", "", normalized_username)
    if normalized_password in COMMON_PASSWORDS or normalized_password == normalized_username_password:
        errors.append("密码过于常见")
    return errors


def jwt_secret() -> str:
    return os.getenv("AICHECK_JWT_SECRET", JWT_SECRET)


def jwt_issuer() -> str:
    return os.getenv("AICHECK_JWT_ISSUER", JWT_ISSUER)


def jwt_audience() -> str:
    return os.getenv("AICHECK_JWT_AUDIENCE", JWT_AUDIENCE)


def jwt_ttl_minutes() -> int:
    try:
        value = int(os.getenv("AICHECK_JWT_TTL_MINUTES", "720"))
    except ValueError:
        value = 720
    return max(5, min(value, 720))


def persistent_users() -> list[dict[str, Any]]:
    try:
        from libs.db.repository import repo
    except Exception:
        return []
    return repo.state.get("users", [])


def persistent_user_by_username(
    username: str | None,
    *,
    enabled_only: bool = True,
    tenant_id: str | None = None,
) -> dict[str, Any] | None:
    if not username:
        return None
    effective_tenant = str(tenant_id or current_tenant_id())
    return next(
        (
            user
            for user in persistent_users()
            if user.get("username") == username
            and tenant_id_for_record(user) == effective_tenant
            and (not enabled_only or user.get("status", "启用") == "启用")
        ),
        None,
    )


def user_record_by_username(username: str | None, *, tenant_id: str | None = None) -> dict[str, Any] | None:
    effective_tenant = str(tenant_id or current_tenant_id())
    persistent = persistent_user_by_username(username, tenant_id=effective_tenant)
    if persistent:
        return persistent
    if not demo_users_enabled() or not username:
        return None
    demo_user = USERS.get(username)
    if demo_user and tenant_id_for_record(demo_user) == effective_tenant:
        return demo_user
    return None


def public_user(user: dict[str, Any]) -> dict[str, Any]:
    safe_user = {
        key: value
        for key, value in user.items()
        if key not in {"password", "passwordHash", "authVersion"}
    }
    safe_user["mustChangePassword"] = bool(safe_user.get("mustChangePassword"))
    safe_user["defaultPath"] = ROLE_DEFAULT_PATHS.get(safe_user.get("role"), ROLE_DEFAULT_PATHS["inspection"])
    return safe_user


def user_by_username(username: str | None) -> dict[str, Any] | None:
    user = user_record_by_username(username)
    return public_user(user) if user else None


def authenticate(username: str, password: str, *, tenant_id: str | None = None) -> dict[str, Any] | None:
    user = user_record_by_username(username, tenant_id=tenant_id)
    if not user or not verify_password(password, user.get("passwordHash"), user.get("password")):
        return None
    return public_user(user)


def user_auth_version(username: str | None) -> int:
    user = user_record_by_username(username)
    return int((user or {}).get("authVersion") or 0)


def issue_token(user: dict[str, Any]) -> str:
    if jwt is None:
        raise RuntimeError("PyJWT is required to issue access tokens")
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user["username"],
        "role": user.get("role", "inspection"),
        "ver": user_auth_version(user.get("username")),
        "iss": jwt_issuer(),
        "aud": jwt_audience(),
        "iat": now,
        "exp": now + timedelta(minutes=jwt_ttl_minutes()),
        "jti": uuid4().hex,
        "tid": tenant_id_for_record(user),
    }
    return str(jwt.encode(payload, jwt_secret(), algorithm=JWT_ALGORITHM))


def decode_token(token: str) -> dict[str, Any] | None:
    if not token:
        return None
    if token.startswith("Bearer "):
        token = token[7:]
    if token.startswith("dev-token-"):
        if not dev_tokens_allowed():
            return None
        parts = token.split("-")
        return {
            "sub": parts[2] if len(parts) > 2 else "admin",
            "role": parts[-1],
            "ver": 0,
            "dev": True,
            "tid": configured_tenant_id(),
        }
    if jwt is None:
        return None
    try:
        claims = jwt.decode(
            token,
            jwt_secret(),
            algorithms=[JWT_ALGORITHM],
            issuer=jwt_issuer(),
            audience=jwt_audience(),
            options={"require": ["sub", "role", "ver", "tid", "iss", "aud", "iat", "exp", "jti"]},
        )
        if not isinstance(claims.get("sub"), str) or not claims["sub"].strip():
            return None
        if not isinstance(claims.get("role"), str) or not claims["role"].strip():
            return None
        if not isinstance(claims.get("tid"), str) or not claims["tid"].strip():
            return None
        if not isinstance(claims.get("jti"), str) or not claims["jti"].strip():
            return None
        if not isinstance(claims.get("ver"), int):
            return None
        return claims
    except Exception:
        return None
