from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

try:
    from jose import jwt
except Exception:  # pragma: no cover - optional until dependencies are installed
    jwt = None  # type: ignore[assignment]


JWT_SECRET = "aicheck-dev-secret-change-me"
JWT_ALGORITHM = "HS256"

ROLE_DEFAULT_PATHS = {
    "inspection": "/workbench/inspection",
    "contractor": "/workbench/contractor",
    "ndt": "/workbench/ndt",
    "owner": "/workbench/owner",
    "admin": "/admin/overview",
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
    "test": user_record("USER-TEST-001", "test", "test", "9", "测试用户", "测试用户", "联调测试组", ["example:dialog:create", "example:dialog:delete"]),
}


def public_user(user: dict[str, Any]) -> dict[str, Any]:
    safe_user = {key: value for key, value in user.items() if key != "password"}
    safe_user["defaultPath"] = ROLE_DEFAULT_PATHS.get(safe_user.get("role"), ROLE_DEFAULT_PATHS["inspection"])
    return safe_user


def user_by_username(username: str | None) -> dict[str, Any] | None:
    if not username:
        return None
    user = USERS.get(username)
    return public_user(user) if user else None


def authenticate(username: str, password: str) -> dict[str, Any] | None:
    user = USERS.get(username)
    if not user or user["password"] != password:
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
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


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
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except Exception:
        return None
