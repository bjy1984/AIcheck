from __future__ import annotations

import os
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

try:
    from jose import jwt
except Exception:  # pragma: no cover - optional until dependencies are installed
    jwt = None  # type: ignore[assignment]

try:
    from passlib.context import CryptContext
except Exception:  # pragma: no cover - optional until dependencies are installed
    CryptContext = None  # type: ignore[assignment]


JWT_SECRET = "aicheck-dev-secret-change-me"
JWT_ALGORITHM = "HS256"
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto") if CryptContext else None

ROLE_DEFAULT_PATHS = {
    "inspection": "/workbench/inspection",
    "contractor": "/workbench/contractor",
    "ndt": "/workbench/ndt",
    "owner": "/workbench/owner",
    "admin": "/admin/overview",
    "fde": "/fde/dashboard",
    "test": "/workbench/inspection",
}

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
    }


USERS = {
    "inspection": user_record("USER-INSPECTION-001", "inspection", "inspection", "2", "监检人员", "张工", "省特检院一部"),
    "contractor": user_record("USER-CONTRACTOR-001", "contractor", "contractor", "3", "施工方", "李工", "中石化安装有限公司"),
    "ndt": user_record("USER-NDT-001", "ndt", "ndt", "4", "无损检测", "王工", "华测检测有限公司"),
    "owner": user_record("USER-OWNER-001", "owner", "owner", "5", "建设方", "赵经理", "华东管网建设公司"),
    "admin": user_record("USER-ADMIN-001", "admin", "admin", "1", "系统管理员", "系统管理员", "省特检院平台组", ["*.*.*"]),
    "fde": user_record("USER-FDE-001", "fde", "fde", "6", "FDE", "FDE 工程师", "AI 交付治理组", ["fde:dashboard:view", "fde:ai-run:view-masked", "fde:ai-run:replay", "fde:feedback:view", "fde:feedback:triage", "fde:evaluation:view", "fde:evaluation:manage", "fde:evaluation:run", "fde:business-pack:view", "fde:business-pack:validate", "fde:business-pack:install", "fde:capability-bundle:manage", "fde:release:view", "fde:release:submit", "fde:release:shadow", "fde:release:canary", "fde:release:rollback", "fde:ocr-quality:view", "fde:incident:manage", "fde:security:manage", "fde:config:draft"]),
    "test": user_record("USER-TEST-001", "test", "test", "9", "测试用户", "测试用户", "联调测试组", ["example:dialog:create", "example:dialog:delete"]),
}


def demo_users_enabled() -> bool:
    return os.getenv("AICHECK_ENABLE_DEMO_USERS", "true").lower() == "true"


def verify_password(password: str, stored_hash: str | None, legacy_password: str | None = None) -> bool:
    if stored_hash:
        if stored_hash.startswith("plain:"):
            return password == stored_hash.removeprefix("plain:")
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
        if pwd_context is not None:
            try:
                return pwd_context.verify(password, stored_hash)
            except Exception:
                return False
    if legacy_password and os.getenv("AICHECK_ALLOW_LEGACY_PLAIN_PASSWORDS", "false").lower() == "true":
        return password == legacy_password
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


def jwt_secret() -> str:
    return os.getenv("AICHECK_JWT_SECRET", JWT_SECRET)


def persistent_users() -> list[dict[str, Any]]:
    try:
        from libs.db.repository import repo
    except Exception:
        return []
    return repo.state.get("users", [])


def persistent_user_by_username(username: str | None) -> dict[str, Any] | None:
    if not username:
        return None
    return next((user for user in persistent_users() if user.get("username") == username and user.get("status", "启用") == "启用"), None)


def public_user(user: dict[str, Any]) -> dict[str, Any]:
    safe_user = {key: value for key, value in user.items() if key not in {"password", "passwordHash"}}
    safe_user["defaultPath"] = ROLE_DEFAULT_PATHS.get(safe_user.get("role"), ROLE_DEFAULT_PATHS["inspection"])
    return safe_user


def user_by_username(username: str | None) -> dict[str, Any] | None:
    if not username:
        return None
    persistent_user = persistent_user_by_username(username)
    if persistent_user:
        return public_user(persistent_user)
    if not demo_users_enabled():
        return None
    user = USERS.get(username)
    return public_user(user) if user else None


def authenticate(username: str, password: str) -> dict[str, Any] | None:
    persistent_user = persistent_user_by_username(username)
    if persistent_user and verify_password(password, persistent_user.get("passwordHash"), persistent_user.get("password")):
        return public_user(persistent_user)
    if not demo_users_enabled():
        return None
    user = USERS.get(username)
    if not user or not verify_password(password, user.get("passwordHash"), user.get("password")):
        return None
    return public_user(user)


def issue_token(user: dict[str, Any]) -> str:
    payload = {
        "sub": user["username"],
        "role": user.get("role", "admin"),
        "exp": datetime.now(timezone.utc) + timedelta(hours=12),
    }
    if jwt is None:
        return f"dev-token-{payload['sub']}-{payload['role']}"
    return jwt.encode(payload, jwt_secret(), algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict[str, Any] | None:
    if not token:
        return None
    if token.startswith("Bearer "):
        token = token[7:]
    if token.startswith("dev-token-"):
        parts = token.split("-")
        return {"sub": parts[2] if len(parts) > 2 else "admin", "role": parts[-1]}
    if jwt is None:
        return None
    try:
        return jwt.decode(token, jwt_secret(), algorithms=[JWT_ALGORITHM])
    except Exception:
        return None
