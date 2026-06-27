from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

try:
    from jose import jwt
except Exception:  # pragma: no cover - optional until dependencies are installed
    jwt = None  # type: ignore[assignment]


JWT_SECRET = "aicheck-dev-secret-change-me"
JWT_ALGORITHM = "HS256"

USERS = {
    "admin": {
        "username": "admin",
        "password": "admin",
        "role": "admin",
        "roleId": "1",
        "permissions": ["*.*.*"],
        "displayName": "系统管理员",
        "orgUnitName": "省特检院平台组",
    },
    "test": {
        "username": "test",
        "password": "test",
        "role": "test",
        "roleId": "2",
        "permissions": ["example:dialog:create", "example:dialog:delete"],
        "displayName": "测试用户",
        "orgUnitName": "联调测试组",
    },
}


def authenticate(username: str, password: str) -> dict[str, Any] | None:
    user = USERS.get(username)
    if not user or user["password"] != password:
        return None
    return {key: value for key, value in user.items() if key != "password"}


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
