from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from libs.db.repository import repo
from libs.security.auth import hash_password, password_strength_errors
from libs.security.runtime import security_runtime_problems
from libs.security.session import security_sessions
from scripts.migrate_auth_users import migrate_users


client = TestClient(app)


def setup_function() -> None:
    repo.reset()
    repo.postgres_enabled = False
    repo.sync_postgres = None
    repo.sqlite_enabled = False
    repo.sqlite_path = None


def payload(response):
    return response.json()


def add_user(
    username: str = "secure-user",
    password: str = "Secure!Password2026",
    *,
    role: str = "inspection",
    must_change: bool = False,
) -> dict:
    user = {
        "id": f"USER-{username.upper()}",
        "username": username,
        "name": username,
        "displayName": username,
        "passwordHash": hash_password(password),
        "role": role,
        "roleId": role,
        "status": "启用",
        "authVersion": 1,
        "mustChangePassword": must_change,
    }
    repo.state["users"].append(user)
    return user


def login(username: str, password: str) -> dict:
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    assert payload(response)["code"] == 0
    return payload(response)["data"]


def test_strict_mode_rejects_forged_dev_token(monkeypatch) -> None:
    add_user("auditlow", role="inspection")
    monkeypatch.setenv("AICHECK_REQUIRE_AUTH", "true")
    monkeypatch.setenv("AICHECK_STRICT_PRODUCTION", "true")
    monkeypatch.setenv("AICHECK_ENABLE_DEMO_USERS", "false")
    monkeypatch.setenv("AICHECK_ALLOW_DEV_TOKENS", "true")

    response = client.get(
        "/api/admin/users",
        headers={"Authorization": "Bearer dev-token-auditlow-admin"},
    )

    assert payload(response)["data"]["reason"] == "AUTH_REQUIRED"


def test_token_version_and_server_role_are_authoritative(monkeypatch) -> None:
    user = add_user("versioned")
    monkeypatch.setenv("AICHECK_REQUIRE_AUTH", "true")
    token = login("versioned", "Secure!Password2026")["token"]

    spoofed = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}", "X-Role": "admin"},
    )
    assert payload(spoofed)["code"] == 0
    assert payload(spoofed)["data"]["role"] == "inspection"

    user["authVersion"] = 2
    stale = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert payload(stale)["data"]["reason"] == "AUTH_REQUIRED"


def test_forced_password_change_rotates_token_and_unlocks_business_routes(monkeypatch) -> None:
    add_user("first-login", "Initial!Password2026", must_change=True)
    monkeypatch.setenv("AICHECK_REQUIRE_AUTH", "true")
    signed_in = login("first-login", "Initial!Password2026")
    old_token = signed_in["token"]

    blocked = client.get(
        "/api/projects/P-2026-HDCP-001",
        headers={"Authorization": f"Bearer {old_token}"},
    )
    assert blocked.status_code == 403
    assert payload(blocked)["data"]["reason"] == "PASSWORD_CHANGE_REQUIRED"

    changed = client.post(
        "/api/auth/change-password",
        headers={"Authorization": f"Bearer {old_token}"},
        json={
            "currentPassword": "Initial!Password2026",
            "newPassword": "Replacement!Safe2026",
        },
    )
    assert payload(changed)["code"] == 0
    new_token = payload(changed)["data"]["token"]
    assert payload(changed)["data"]["user"]["mustChangePassword"] is False

    stale = client.get("/api/auth/me", headers={"Authorization": f"Bearer {old_token}"})
    assert payload(stale)["data"]["reason"] == "AUTH_REQUIRED"
    current = client.get("/api/auth/me", headers={"Authorization": f"Bearer {new_token}"})
    assert payload(current)["code"] == 0


def test_logout_revokes_current_token(monkeypatch) -> None:
    add_user("logout-user")
    monkeypatch.setenv("AICHECK_REQUIRE_AUTH", "true")
    token = login("logout-user", "Secure!Password2026")["token"]

    logout = client.post("/api/auth/logout", headers={"Authorization": f"Bearer {token}"})
    assert payload(logout)["code"] == 0
    after = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert payload(after)["data"]["reason"] == "AUTH_REQUIRED"


def test_login_audit_uses_scoped_persistence(monkeypatch) -> None:
    import apps.api.main as api_main

    full_flushes: list[bool] = []
    scoped_flushes: list[dict] = []
    monkeypatch.setattr(api_main, "flush_state", lambda: full_flushes.append(True))
    monkeypatch.setattr(
        api_main,
        "flush_mutation_records",
        lambda records, scopes: scoped_flushes.append(records),
    )

    response = client.post(
        "/api/auth/login",
        json={"username": "scoped-persistence-probe", "password": "invalid"},
    )

    assert payload(response)["data"]["reason"] == "AUTH_REQUIRED"
    assert full_flushes == []
    assert len(scoped_flushes) == 1
    assert set(scoped_flushes[0]) == {"audit_logs"}


@pytest.mark.asyncio
async def test_login_rate_limit_blocks_fifth_pair_failure() -> None:
    for _ in range(4):
        result = await security_sessions.record_login_failure("192.0.2.10", "limited")
        assert result.blocked is False
    blocked = await security_sessions.record_login_failure("192.0.2.10", "limited")
    assert blocked.blocked is True
    assert blocked.retry_after == 900


def test_mock_users_are_always_redacted() -> None:
    response = client.get("/mock/user/list")
    assert payload(response)["code"] == 0
    for user in payload(response)["data"]["list"]:
        assert "password" not in user
        assert "passwordHash" not in user
        assert "authVersion" not in user


def test_strict_mode_hides_mock_routes(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_STRICT_PRODUCTION", "true")
    response = client.get("/mock/user/list")
    assert response.status_code == 404


def test_admin_user_creation_requires_strong_password() -> None:
    response = client.post(
        "/api/admin/users",
        headers={"If-Match": "*", "Idempotency-Key": "weak-user"},
        json={"username": "weak-user", "name": "Weak", "role": "owner"},
    )
    assert payload(response)["data"]["reason"] == "VALIDATION_ERROR"
    assert payload(response)["data"]["field"] == "password"


def test_auth_migration_dry_run_and_apply_never_exposes_passwords() -> None:
    users = [
        {"id": "USER-PLAIN", "username": "plain-user", "passwordHash": "plain:secret"},
        {"id": "USER-EMPTY", "username": "empty-user"},
    ]
    dry_run = migrate_users(users, apply=False)
    assert users[0]["passwordHash"] == "plain:secret"
    assert dry_run["secretsIncluded"] is False

    applied = migrate_users(users, apply=True)
    assert users[0]["passwordHash"].startswith("pbkdf2_sha256$")
    assert users[0]["mustChangePassword"] is True
    assert users[1]["status"] == "停用"
    assert applied["disabled"] == 1
    assert "plain:secret" not in str(applied)


def test_disabled_missing_password_user_does_not_block_strict_startup(monkeypatch) -> None:
    repo.state["users"] = [{"id": "USER-RESET", "username": "reset-user", "status": "停用"}]
    monkeypatch.setenv("AICHECK_STRICT_PRODUCTION", "true")
    monkeypatch.setenv("AICHECK_ENABLE_DEMO_DATA", "false")
    monkeypatch.setenv("AICHECK_REQUIRE_AUTH", "true")
    monkeypatch.setenv("AICHECK_TENANT_ID", "TENANT-PRODUCTION")
    monkeypatch.setenv("AICHECK_ENABLE_DEMO_USERS", "false")
    monkeypatch.setenv("AICHECK_ALLOW_DEV_TOKENS", "false")
    monkeypatch.setenv("AICHECK_ENABLE_COMPATIBILITY_MOCKS", "false")
    monkeypatch.setenv("AICHECK_JWT_SECRET", "a" * 40)
    monkeypatch.setenv("AICHECK_CORS_ALLOWED_ORIGINS", "https://aicheck.example.com")
    monkeypatch.setenv("AICHECK_ALLOWED_HOSTS", "aicheck.example.com")
    monkeypatch.setenv("AICHECK_REQUIRE_AUDIT_ANCHOR", "true")
    monkeypatch.setenv("AICHECK_AUDIT_ANCHOR_OBJECT_LOCK", "true")
    monkeypatch.setenv("AICHECK_MINIO_ENDPOINT", "minio:9000")

    assert security_runtime_problems() == []


def test_password_policy_rejects_decorated_common_password() -> None:
    assert "密码过于常见" in password_strength_errors("secure-user", "Password123!")


def test_strict_security_runtime_rejects_malformed_allowlists(monkeypatch) -> None:
    repo.state["users"] = []
    monkeypatch.setenv("AICHECK_STRICT_PRODUCTION", "true")
    monkeypatch.setenv("AICHECK_REQUIRE_AUTH", "true")
    monkeypatch.setenv("AICHECK_ENABLE_DEMO_USERS", "false")
    monkeypatch.setenv("AICHECK_ALLOW_DEV_TOKENS", "false")
    monkeypatch.setenv("AICHECK_ENABLE_COMPATIBILITY_MOCKS", "false")
    monkeypatch.setenv("AICHECK_JWT_SECRET", "a" * 40)
    monkeypatch.setenv("AICHECK_CORS_ALLOWED_ORIGINS", "https://user:pass@aicheck.example.com/path")
    monkeypatch.setenv("AICHECK_ALLOWED_HOSTS", "https://aicheck.example.com")

    problems = security_runtime_problems()
    assert "invalid CORS origin: https://user:pass@aicheck.example.com/path" in problems
    assert "invalid allowed host: https://aicheck.example.com" in problems


def test_strict_health_fails_when_security_backend_is_unavailable(monkeypatch) -> None:
    repo.state["users"] = []
    monkeypatch.setenv("AICHECK_STRICT_PRODUCTION", "true")
    monkeypatch.setenv("AICHECK_REQUIRE_AUTH", "true")
    monkeypatch.setenv("AICHECK_ENABLE_DEMO_USERS", "false")
    monkeypatch.setenv("AICHECK_ALLOW_DEV_TOKENS", "false")
    monkeypatch.setenv("AICHECK_ENABLE_COMPATIBILITY_MOCKS", "false")
    monkeypatch.setenv("AICHECK_JWT_SECRET", "a" * 40)
    monkeypatch.setenv("AICHECK_CORS_ALLOWED_ORIGINS", "https://aicheck.example.com")
    monkeypatch.setenv("AICHECK_ALLOWED_HOSTS", "testserver")

    async def unavailable() -> bool:
        return False

    monkeypatch.setattr(security_sessions, "ready", unavailable)
    response = client.get("/healthz")

    assert response.status_code == 503
    assert payload(response)["data"]["reason"] == "SECURITY_BACKEND_UNAVAILABLE"
    assert payload(response)["data"]["securityReady"] is False


def test_strict_security_runtime_rejects_plain_users(monkeypatch) -> None:
    repo.state["users"] = [
        {"id": "USER-PLAIN", "username": "plain-user", "passwordHash": "plain:secret"}
    ]
    monkeypatch.setenv("AICHECK_STRICT_PRODUCTION", "true")
    monkeypatch.setenv("AICHECK_REQUIRE_AUTH", "true")
    monkeypatch.setenv("AICHECK_ENABLE_DEMO_USERS", "false")
    monkeypatch.setenv("AICHECK_ALLOW_DEV_TOKENS", "false")
    monkeypatch.setenv("AICHECK_ENABLE_COMPATIBILITY_MOCKS", "false")
    monkeypatch.setenv("AICHECK_JWT_SECRET", "a" * 40)
    monkeypatch.setenv("AICHECK_CORS_ALLOWED_ORIGINS", "https://aicheck.example.com")
    monkeypatch.setenv("AICHECK_ALLOWED_HOSTS", "aicheck.example.com")

    problems = security_runtime_problems()
    assert "plain-user:plain_password_hash" in problems
