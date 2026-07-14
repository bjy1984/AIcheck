from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlsplit

from libs.security.auth import (
    JWT_SECRET,
    compatibility_mocks_enabled,
    demo_users_enabled,
    dev_tokens_allowed,
    jwt_secret,
    persistent_users,
    strict_production,
)
from libs.security.tenant import configured_tenant_id


def cors_allowed_origins() -> list[str]:
    raw = os.getenv(
        "AICHECK_CORS_ALLOWED_ORIGINS",
        "http://127.0.0.1:4000,http://localhost:4000",
    )
    return list(dict.fromkeys(item.strip() for item in raw.split(",") if item.strip()))


def allowed_hosts() -> list[str]:
    raw = os.getenv("AICHECK_ALLOWED_HOSTS", "127.0.0.1,localhost,testserver")
    return list(dict.fromkeys(item.strip() for item in raw.split(",") if item.strip()))


def allowlist_problems(origins: list[str], hosts: list[str]) -> list[str]:
    problems: list[str] = []
    for origin in origins:
        parsed = urlsplit(origin)
        try:
            parsed.port
            valid_port = True
        except ValueError:
            valid_port = False
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or not valid_port
            or parsed.username
            or parsed.password
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or "*" in origin
            or any(character.isspace() for character in origin)
        ):
            problems.append(f"invalid CORS origin: {origin}")
    for host in hosts:
        if "*" in host or "://" in host or "/" in host or any(character.isspace() for character in host):
            problems.append(f"invalid allowed host: {host}")
    return problems


def persistent_password_problems() -> list[str]:
    problems: list[str] = []
    for user in persistent_users():
        username = str(user.get("username") or user.get("id") or "unknown")
        password_hash = str(user.get("passwordHash") or "")
        enabled = user.get("status", "启用") == "启用"
        if not password_hash and enabled:
            problems.append(f"{username}:missing_password_hash")
        elif password_hash.startswith("plain:"):
            problems.append(f"{username}:plain_password_hash")
        if user.get("password"):
            problems.append(f"{username}:legacy_password_field")
    return problems


def security_runtime_problems() -> list[str]:
    if not strict_production():
        return []
    problems: list[str] = []
    if os.getenv("AICHECK_REQUIRE_AUTH", "false").lower() != "true":
        problems.append("AICHECK_REQUIRE_AUTH must be true")
    tenant_mode = os.getenv("AICHECK_TENANT_MODE", "shared").strip().lower()
    if tenant_mode not in {"shared", "isolated"}:
        problems.append("AICHECK_TENANT_MODE must be shared or isolated")
    if tenant_mode == "isolated" and not os.getenv("AICHECK_TENANT_ID", "").strip():
        problems.append("AICHECK_TENANT_ID must be explicitly configured for isolated mode")
    if not configured_tenant_id():
        problems.append("AICHECK_TENANT_ID must be non-empty")
    if os.getenv("AICHECK_REQUIRE_AUDIT_ANCHOR", "false").lower() != "true":
        problems.append("AICHECK_REQUIRE_AUDIT_ANCHOR must be true")
    if os.getenv("AICHECK_AUDIT_ANCHOR_OBJECT_LOCK", "false").lower() != "true":
        problems.append("AICHECK_AUDIT_ANCHOR_OBJECT_LOCK must confirm immutable bucket retention")
    if not os.getenv("AICHECK_MINIO_ENDPOINT", "").strip():
        problems.append("AICHECK_MINIO_ENDPOINT is required for audit anchoring")
    if demo_users_enabled():
        problems.append("AICHECK_ENABLE_DEMO_USERS must be false")
    if os.getenv("AICHECK_ENABLE_DEMO_DATA", "false").lower() == "true":
        problems.append("AICHECK_ENABLE_DEMO_DATA must be false")
    if dev_tokens_allowed() or os.getenv("AICHECK_ALLOW_DEV_TOKENS", "false").lower() == "true":
        problems.append("AICHECK_ALLOW_DEV_TOKENS must be false")
    if compatibility_mocks_enabled() or os.getenv("AICHECK_ENABLE_COMPATIBILITY_MOCKS", "false").lower() == "true":
        problems.append("AICHECK_ENABLE_COMPATIBILITY_MOCKS must be false")
    secret = jwt_secret()
    if secret == JWT_SECRET or secret.startswith("replace-with-") or len(secret) < 32:
        problems.append("AICHECK_JWT_SECRET must be a non-default secret of at least 32 characters")
    origins = cors_allowed_origins()
    if not origins or "*" in origins:
        problems.append("AICHECK_CORS_ALLOWED_ORIGINS must be a non-empty explicit allowlist")
    hosts = allowed_hosts()
    if not hosts or "*" in hosts:
        problems.append("AICHECK_ALLOWED_HOSTS must be a non-empty explicit allowlist")
    problems.extend(allowlist_problems(origins, hosts))
    problems.extend(persistent_password_problems())
    return problems


def validate_security_runtime() -> None:
    problems = security_runtime_problems()
    if problems:
        raise RuntimeError("Invalid strict production security configuration: " + "; ".join(problems))


def security_runtime_status(*, rate_limiter_ready: bool) -> dict[str, Any]:
    problems = security_runtime_problems()
    return {
        "strictProduction": strict_production(),
        "securityReady": not problems and rate_limiter_ready,
        "rateLimiterReady": rate_limiter_ready,
        "compatibilityMocksEnabled": compatibility_mocks_enabled(),
        "corsMode": "allowlist",
    }
